"""B-09: source freeze round-trips on lanes D/E's Postgres tables (E-02 landed @ agent-05 1c554cb).

discovery blocks → side-channel freeze_request → lane E gateway applies it (receipted KILL_SWITCH_CHANGED in
lane D's ledger) → discovery, reading PANIC through a READ-ONLY login, skips exactly that source → only a human
release restores it. Unreachable DB = fail closed."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("pgserver")
gov = pytest.importorskip("mbos_governance")
if not hasattr(gov, "PgPanicStore"):
    pytest.skip("mbos_governance < E-02 (no PgPanicStore)", allow_module_level=True)

from conftest import FIX, FLIP, SERVICE, StaticAdapter, World  # noqa: E402
from lane_de import Cluster, LaneE  # noqa: E402
from mbos_discovery import AGENT_ID  # noqa: E402
from mbos_discovery.adapter import SourceError  # noqa: E402
from mbos_discovery.adapters import ServiceIntakeAdapter  # noqa: E402
from mbos_discovery.health import capability_for  # noqa: E402
from mbos_discovery.spine import SideChannel  # noqa: E402

EXAMPLES = FIX.parent.parent / "docs" / "integration" / "freeze-request" / "examples"


@pytest.fixture(scope="module")
def cluster():
    c = Cluster()
    yield c
    c.stop()


@pytest.fixture
def lane_e(cluster, tmp_path):
    e = LaneE(cluster, tmp_path)
    yield e
    e.close()


def _receipts(lane_e, type_):
    """Lane D's ledger (typed columns), read as superuser for verification only."""
    import psycopg
    with psycopg.connect(lane_e.dsn("superuser"), autocommit=True) as c:
        return [{"actor": a, "intent": i} for a, i in c.execute(
            "SELECT actor, intent FROM mbos.receipts WHERE type = %s ORDER BY seq", (type_,)).fetchall()]


def test_freeze_round_trip_on_postgres(lane_e, tmp_path, world, intake_copy):
    from mbos_governance.freeze_requests import apply_side_channel

    # 1. a source pushes back twice → lane B freezes locally and writes a request to its side channel
    blocked = StaticAdapter("craigslist", [SourceError("rate_limited", "429", 429)], world.clock)
    side = SideChannel(tmp_path / "side.jsonl")
    for _ in range(2):
        for fr in world.run([(blocked, FLIP)], enabled=frozenset({"craigslist"}), panic=lane_e.reader_panic).freeze_requests:
            side.emit("freeze_request", source=fr["source"], at=fr["requested_at"], freeze_request=fr)
    assert len(side.freeze_requests()) == 1

    # 2. lane E applies it (agents have no PANIC write rights; the gateway does, and receipts it in lane D)
    outcomes = apply_side_channel(lane_e.gw, tmp_path / "side.jsonl")
    assert [o.applied for o in outcomes] == [True]
    ks = _receipts(lane_e, "KILL_SWITCH_CHANGED")
    assert any(r["actor"]["id"] == AGENT_ID and "craigslist" in r["intent"] for r in ks)

    # 3. discovery honours it through a READ-ONLY login, even after a human clears the LOCAL freeze
    world.health.clear_freeze("craigslist", "michael", world.clock())
    lead = ServiceIntakeAdapter("website_lead", intake_copy / "website_form", world.clock)
    n = blocked.fetch_calls
    r = world.run([(blocked, FLIP), (lead, SERVICE)], enabled=frozenset({"craigslist"}), panic=lane_e.reader_panic)
    assert r.sources[0].status == "skipped" and "PANIC_L2_CAPABILITY:discovery.source.craigslist.read" in r.sources[0].skipped_reason
    assert blocked.fetch_calls == n and r.sources[1].status == "ok"          # zero requests; others unaffected

    # 4. only a human releases it in lane E; then collection resumes
    with pytest.raises(Exception):
        lane_e.gw.release_panic("L2", capability_for("craigslist"), AGENT_ID, "self-release")
    lane_e.gw.release_panic("L2", capability_for("craigslist"), "michael", "source healthy again")
    ok = StaticAdapter("craigslist", [[{"id": "c1", "title": "air compressor", "price": 90, "city": "Conway"}]], world.clock)
    assert world.run([(ok, FLIP)], enabled=frozenset({"craigslist"}), panic=lane_e.reader_panic).sources[0].created == 1


@pytest.mark.parametrize("name", ["freeze-request-429.json", "freeze-request-captcha.json"])
def test_shared_examples_round_trip(lane_e, name, world):
    from mbos_governance.freeze_requests import apply_freeze_request
    req = json.loads((EXAMPLES / name).read_text())
    assert apply_freeze_request(lane_e.gw, req).applied
    ad = StaticAdapter(req["source"], [[]], world.clock)
    r = world.run([(ad, FLIP)], enabled=frozenset({req["source"]}), panic=lane_e.reader_panic)
    assert r.sources[0].status == "skipped" and ad.fetch_calls == 0


@pytest.mark.parametrize("level,target", [("L2", "discovery.source.*"), ("L1", AGENT_ID), ("L3", None)])
def test_broader_freezes_from_lane_e_stop_all_discovery(lane_e, world, level, target):
    lane_e.gw.engage_panic(level, target, "michael", "test")
    ads = [StaticAdapter(s, [[]], world.clock) for s in ("craigslist", "govdeals")]
    r = world.run([(a, FLIP) for a in ads], enabled=frozenset({"craigslist", "govdeals"}), panic=lane_e.reader_panic)
    assert all(s.status == "skipped" and "PANIC" in s.skipped_reason for s in r.sources)
    assert all(a.fetch_calls == 0 for a in ads)


def test_unreachable_database_fails_closed(world, tmp_path):
    from mbos_governance import PgPanicStore
    dead = PgPanicStore(f"host={tmp_path} port=1 dbname=x user=y", connect_timeout=1)
    ad = StaticAdapter("craigslist", [[]], world.clock)
    r = world.run([(ad, FLIP)], enabled=frozenset({"craigslist"}), panic=dead)
    assert "PANIC_STATE_UNREADABLE" in r.sources[0].skipped_reason and ad.fetch_calls == 0


def test_cli_wires_postgres_panic_from_dsn(lane_e, monkeypatch):
    from mbos_discovery.cli import _panic
    monkeypatch.setenv("MBOS_PANIC_STATE", lane_e.dsn("reader"))
    p = _panic()
    assert type(p).__name__ == "PgPanicStore" and p.read().blocks(AGENT_ID, capability_for("ebay"), "discovery") == []
