"""B-05: wake-event producer. Detector semantics (no DB), the standalone pipeline hook, and the acceptance
test on Agent 01's real DBOS workflow (@ aa88e7a): a HOLD with wake_on=price_change wakes from a lane-B fixture
re-sighting, and nothing ever executes."""

from __future__ import annotations

import dataclasses
import json
import time
import uuid
from datetime import timedelta
from pathlib import Path

import pytest

from conftest import FIX, FLIP, T0, Clock, World
from mbos_discovery.adapters import EbayBrowseAdapter
from mbos_discovery.events import WakeEventDetector
from mbos_discovery.http import CallbackTransport, HttpResponse

BASE = {"title": "6x12 enclosed trailer", "condition": "used", "listing_status": "active",
        "price": {"amount": 1200.0, "currency": "USD", "type": "fixed"}}


def _obs(det, normalized, at=T0, raw="sha256:" + "0" * 64):
    return det.observe(source="ebay", source_listing_id="L1", url="https://x.invalid/L1", normalized=normalized,
                       fetched_at=at, raw_ref=raw)


# ---------------------------------------------------------------- detector
def test_first_sighting_is_never_an_event():
    det = WakeEventDetector()
    assert _obs(det, BASE) == []
    assert _obs(WakeEventDetector(), {**BASE, "ends_at": "2026-10-07T20:00:00Z"}) == []   # already ending: no change


def test_price_change_then_new_info_then_quiet():
    det = WakeEventDetector()
    _obs(det, BASE)
    ev, = _obs(det, {**BASE, "price": {**BASE["price"], "amount": 999.0}}, raw="sha256:" + "1" * 64)
    assert ev["event"] == "price_change" and ev["summary"] == "price 1200.0 → 999.0 USD"
    ev, = _obs(det, {**BASE, "price": {**BASE["price"], "amount": 999.0}, "listing_status": "ended"},
               raw="sha256:" + "2" * 64)
    assert ev["event"] == "new_info" and ev["summary"] == "changed: listing_status"
    assert _obs(det, {**BASE, "price": {**BASE["price"], "amount": 999.0}, "listing_status": "ended"},
                raw="sha256:" + "2" * 64) == []
    assert [e["event"] for e in det.outbox] == ["price_change", "new_info"]


def test_auction_ending_announced_once_per_end_time():
    det = WakeEventDetector()
    lot = {**BASE, "ends_at": "2026-10-09T12:00:00Z"}
    _obs(det, lot)                                                    # 48 h out: outside the window
    assert [e["event"] for e in _obs(det, lot, at=T0 + timedelta(hours=30))] == ["auction_ending"]
    assert _obs(det, lot, at=T0 + timedelta(hours=40)) == []          # same end time: announced already
    extended = {**lot, "ends_at": "2026-10-09T13:00:00Z"}
    assert {e["event"] for e in _obs(det, extended, at=T0 + timedelta(hours=41))} == {"new_info", "auction_ending"}


def test_outbox_survives_reload_without_duplicates(tmp_path):
    p = tmp_path / "events.json"
    det = WakeEventDetector(p)
    _obs(det, BASE)
    _obs(det, {**BASE, "price": {**BASE["price"], "amount": 900.0}}, raw="sha256:" + "3" * 64)
    det.save()
    again = WakeEventDetector.load(p)
    assert len(again.outbox) == 1
    again.snapshots.clear()                                           # even re-detecting the same evidence…
    _obs(again, BASE)
    _obs(again, {**BASE, "price": {**BASE["price"], "amount": 900.0}}, raw="sha256:" + "3" * 64)
    assert len(again.outbox) == 1                                     # …never queues it twice


def _ebay(clock, price_box):
    base = FIX / "ebay"

    def handler(method, url, headers, body):
        if method == "POST":
            return HttpResponse(200, (base / "token.json").read_bytes())
        if "utility+trailer" in url and "offset=0" in url:
            data = json.loads((base / "search-utility-trailer.json").read_text())
            data["itemSummaries"][0]["price"]["value"] = price_box[0]
            data.pop("next")
            data["itemSummaries"] = data["itemSummaries"][:1]
            return HttpResponse(200, json.dumps(data).encode())
        return HttpResponse(200, b'{"itemSummaries":[]}')

    return EbayBrowseAdapter("id", "secret", transport=CallbackTransport(handler), clock=clock)


def test_standalone_pipeline_queues_price_change(world):
    det, price = WakeEventDetector(), ["1200.00"]
    ad = _ebay(world.clock, price)
    from mbos_discovery.pipeline import run_discovery
    run_discovery([(ad, FLIP)], world.store, world.raw, world.health, world.clock(), events=det)
    price[0] = "999.00"
    world.clock.advance(hours=1)
    run_discovery([(ad, FLIP)], world.store, world.raw, world.health, world.clock(), events=det)
    ev, = det.outbox
    assert ev["event"] == "price_change" and ev["source_listing_id"] == "v1|110000000001|0"
    assert world.raw.exists(ev["raw_ref"])                            # evidence is retained


# ---------------------------------------------------------------- acceptance on the real DBOS workflow
pytest.importorskip("mbos")
import os  # noqa: E402

os.environ.setdefault("MBOS_CONTRACTS_DIR", str(FIX / "mbos_contracts_99e9ec0"))


@pytest.fixture(scope="module")
def rt(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    from dbos import DBOS
    from mbos.config import Settings
    from mbos.runtime import Components, init_runtime, shutdown

    server = pgserver.get_server(str(tmp_path_factory.mktemp("pgw")), cleanup_mode="stop")

    def db(prefix):
        name = f"{prefix}_{uuid.uuid4().hex[:8]}"
        server.psql(f"CREATE DATABASE {name};")
        return server.get_uri().replace("/postgres?", f"/{name}?")

    runtime = init_runtime(Settings(database_url=db("app"), system_database_url=db("sys"), approval_poll_seconds=0.5),
                           Components())
    yield runtime
    pending = [w.workflow_id for w in DBOS.list_workflows(status="PENDING", load_input=False, load_output=False)]
    if pending:
        DBOS.cancel_workflows(pending)
        time.sleep(1.0)
    shutdown()
    server.cleanup()


def _state(engine, item_id):
    import sqlalchemy as sa
    with engine.connect() as c:
        return c.execute(sa.text("SELECT body->>'state' FROM mbos.items WHERE item_id = :i"), {"i": item_id}).scalar_one()


def _wait(engine, item_id, want, timeout=30.0):
    end, st = time.monotonic() + timeout, None
    while time.monotonic() < end:
        st = _state(engine, item_id)
        if st == want:
            return
        time.sleep(0.1)
    raise AssertionError(f"{item_id} stuck in {st}, wanted {want}")


def _rows(engine, sql, **kw):
    import sqlalchemy as sa
    with engine.connect() as c:
        return [r[0] for r in c.execute(sa.text(sql), kw)]


def test_hold_wakes_on_lane_b_price_change_and_never_executes(rt, tmp_path):
    from dbos import DBOS, SetWorkflowID
    from mbos import workflows
    from mbos.clock import iso, utcnow
    from mbos.runtime import components
    from mbos_discovery.events import deliver_wake_events
    from mbos_discovery.spine import discovery_components

    econ = json.loads((FIX / "illustrative_trailer_economics_aa88e7a.json").read_text())["economics"]
    clock, price = Clock(), ["950.00"]
    det = WakeEventDetector(tmp_path / "events.json")
    adapters, normalizer, deduper, _ = discovery_components([(_ebay(clock, price), FLIP)], raw_dir=tmp_path / "raw",
                                                            clock=clock, events=det)

    class WithEconomics:                      # stands in for the RESEARCH step (A-05) — see fixture provenance
        def normalize(self, raw):
            n = normalizer.normalize(raw)
            return dataclasses.replace(n, economics=econ) if n else n

    comps = components()
    name = next(iter(adapters))
    comps.adapters[name] = adapters[name]
    comps.normalizer, comps.deduper = WithEconomics(), deduper

    def discover(tag):
        with SetWorkflowID(f"discover:{name}:{tag}"):
            return DBOS.start_workflow(workflows.discover, name).get_result()

    item_id = next(r["item_id"] for r in discover("1") if r["created"])
    _wait(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = _rows(rt.engine, "SELECT body FROM mbos.action_requests WHERE item_id = :i AND status = 'pending_approval'",
                 i=item_id)[0]
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": iso(utcnow() + timedelta(hours=6)), "wake_on": ["price_change"],
                                    "renotify_after": "PT6H"})
    _wait(rt.engine, item_id, "HELD")

    price[0] = "800.00"                       # the seller drops the price; lane B re-sights the listing
    clock.advance(hours=2)
    assert discover("2") == [{"item_id": item_id, "created": False, "merged": False, "dropped": False}]
    assert [e["event"] for e in det.outbox] == ["price_change"]
    out = deliver_wake_events(rt.engine, det)
    ev, = out["delivered"]
    assert ev["item_id"] == item_id and not out["pending"] and det.outbox == []

    _wait(rt.engine, item_id, "AWAITING_APPROVAL")                     # the HOLD woke up
    intents = _rows(rt.engine, "SELECT body->>'intent' FROM mbos.receipts WHERE action_request_id = :a "
                    "AND type = 'APPROVAL_REQUESTED' ORDER BY seq", a=areq["action_request_id"])
    assert any("price_change" in i for i in intents)
    prov = _rows(rt.engine, "SELECT body FROM mbos.provenance WHERE body->>'provenance_id' = :p",
                 p=ev["evidence_provenance_id"])[0]
    assert (prov["basis"], prov["agent_name"], prov["source_uri"]) == ("FACT", "agent-02-opportunity",
                                                                     "https://www.ebay.com/itm/110000000001")
    assert not _rows(rt.engine, "SELECT 1 FROM mbos.receipts WHERE action_request_id = :a AND type IN "
                     "('ACTION_EXECUTING','ACTION_EXECUTED')", a=areq["action_request_id"])   # never executes
    assert deliver_wake_events(rt.engine, det) == {"delivered": [], "pending": []}            # idempotent
    workflows.record_decision(areq["action_request_id"], "NO", areq["payload_hash"], reason="test cleanup")
    _wait(rt.engine, item_id, "ARCHIVED")
