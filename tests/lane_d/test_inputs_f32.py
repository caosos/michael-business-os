"""F-32 (R14): "Set my quote" and "Tell me about the job" over real HTTP, on a backend that connects as lane D's REAL Operator UI login
(`mbos_operator_ui`, non-superuser). The saved entries are read back from the stored Item and scored by 03's REAL engine
(C-27/C-28), exactly as the worker's re-check does: the drywall lead goes MAYBE -> YES on a $700 quote, and an unknown-category
item stops waiting on `scope_override_required` after the scope is saved. The worker itself is not run here (A-43 proves its trigger)."""

from __future__ import annotations

import copy
import json
import threading
from dataclasses import asdict
from http.server import ThreadingHTTPServer

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

from tests.conftest import FIXTURE, PIN
from tests.lane_d.test_ui_on_lane_d import req

pytestmark = pytest.mark.usefixtures("rtd")
_n = iter(range(10**6))


@pytest.fixture(scope="module")
def ui_role(rtd):
    eng = sa.create_engine(make_url(rtd.url).set(username="mbos_operator_ui", password=None))
    yield eng
    eng.dispose()


@pytest.fixture()
def ui(rtd, ui_role):
    from mbos.runtime import components

    from operator_ui.backend import SpineBackend
    from operator_ui.server import App, make_handler

    app = App(SpineBackend(ui_role, components(), lane="lane_d"), operator_pin=PIN)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


def post(ui, item_id, which, **f):
    return req(ui, "POST", f"/item/{item_id}/{which}", {"csrf": ui.csrf, "pin": PIN, "nonce": f"nonce{next(_n):08d}", **f})


def ingest(rtd, listing_id, category=None):
    from mbos import spine_d
    from mbos.reference.fixture_adapter import FixtureSourceAdapter
    from mbos.runtime import components

    comps = components()
    raw = next(r for r in FixtureSourceAdapter(FIXTURE, name="fixture").fetch() if r.source_listing_id == listing_id)
    norm = asdict(comps.normalizer.normalize(raw))
    tag = f"f32-{next(_n)}"
    if category:
        norm = {**norm, "category": category}
    norm = {**norm, "dedup_key": f"{norm['dedup_key']}|{tag}"}
    with rtd.engine.begin() as c:
        return spine_d.ingest(c, {**asdict(raw), "source_listing_id": f"{listing_id}-{tag}"}, norm, "fixture", "0.1.0", comps)["item_id"]


def attest(rtd, item_id, *keys):
    from mbos import spine_d

    with rtd.engine.begin() as c:
        for k in keys:
            spine_d.record_attestation(c, item_id, k, "I confirmed it", "michael")


def park(rtd, item_id, reason):
    """The trail entry the worker writes when research cannot estimate (a real receipted transition)."""
    from mbos import spine_d
    from mbos.ids import new_id

    with rtd.engine.begin() as c:
        pid = spine_d.record_lane_provenance(c, {"provenance_id": new_id("prov"), "created_at": "2026-10-08T12:00:00Z", "actor_type": "system",
                                                 "agent_name": "f32-test", "basis": "INFERENCE", "tool_name": "t", "tool_version": "1"})
        spine_d._to(c, item_id, "RESEARCHING", reason, [pid])


def stored(ui, item_id):
    return ui.store.item(item_id)


def engine_view(item):
    """What the worker's re-check computes from the stored Item: the estimate, then the score."""
    from mbos_economics.config import load_config
    from mbos_economics.engine import score_item
    from mbos_economics.estimate import estimate_item

    est = estimate_item(item, None, item["created_at"])
    it = copy.deepcopy(item)
    for k, v in est.get("item_patch", {}).items():
        it[k] = it.get(k, []) + v if k == "research" else v
    decision = score_item(it, load_config(), item["created_at"])["scores"]["scorecard"]["decision"] if est["status"] == "estimated" else None
    return est, decision


def test_quote_on_the_drywall_lead_moves_it_to_yes_over_http(rtd, ui):
    iid = ingest(rtd, "FIX-LEAD-DRYWALL-1")
    attest(rtd, iid, "scope_verified", "customer_screened")
    assert "Set my quote" in req(ui, "GET", f"/item/{iid}")[2]
    assert post(ui, iid, "quote", amount="-3", note="x y z")[0] == 200 and post(ui, iid, "quote", amount="700", note="x y z", pin="0000")[0] == 200
    s, loc, _ = post(ui, iid, "quote", amount="500", note="Quoted Pat $500 by phone", author="mallory")
    assert s == 303 and "Saved your quote of $500" in loc and "the verdict has not changed yet" in loc, loc
    assert engine_view(stored(ui, iid))[1] == "MAYBE"
    s, loc, _ = post(ui, iid, "quote", amount="700", note="Re-quoted Pat $700")
    assert s == 303 and "$700" in loc
    item = stored(ui, iid)
    q = [r for r in item["research"] if r["field"] == "quote:amount_usd"]
    assert [r["value"] for r in q] == [500, 700] and all(r["basis"] == "FACT" and r["entered_by"] == "michael" for r in q)
    est, decision = engine_view(item)
    assert decision == "YES" and est["item_patch"]["economics"]["job"]["quoted_revenue"] == 700
    with rtd.engine.connect() as c:
        n = c.execute(sa.text("SELECT count(*) FROM mbos.receipts WHERE entity_id = :i AND actor->>'type' = 'human' AND actor->>'id' = 'michael'"), {"i": iid}).scalar()
    assert n >= 2 + 2  # two attestations + two quotes, each receipted as the human (the mallory field was ignored)
    h = req(ui, "GET", f"/item/{iid}")[2]
    assert "Your quote on file: <b>$700</b>" in h


def test_scope_override_on_an_unknown_category_item_moves_it_over_http(rtd, ui):
    iid = ingest(rtd, "FIX-LEAD-DRYWALL-1", category="other_service")
    park(rtd, iid, "gaps: BLOCKING scope_override_required: category 'other_service' has no estimate; tell me the job cost, hours and skills")
    est, _ = engine_view(stored(ui, iid))
    assert est["status"] != "estimated" and any(g["code"] == "scope_override_required" for g in est["gaps"])
    assert "Tell me about the job" in req(ui, "GET", f"/item/{iid}")[2]
    bad = post(ui, iid, "scope", materials_cost="25", labor_hours="-2", required_skills="drywall", note="measured it")
    assert bad[0] == 200 and "Labour hours" in bad[2]
    s, loc, _ = post(ui, iid, "scope", materials_cost="25", labor_hours="4", required_skills="drywall, painting", note="walked the job with Pat")
    assert s == 303 and "Saved what you know about the job (3 figures)" in loc, loc
    item = stored(ui, iid)
    fields = {r["field"]: r["value"] for r in item["research"] if r["field"].startswith("scope_override:")}
    assert fields == {"scope_override:job.materials_cost": 25, "scope_override:job.labor_hours": 4, "scope_override:job.required_skills": ["drywall", "painting"]}
    est, _ = engine_view(item)
    assert est["status"] == "estimated" and not any(g["code"] == "scope_override_required" for g in est["gaps"])


def test_the_workflow_login_cannot_write_these_entries(rtd):
    from mbos import spine_d

    iid = ingest(rtd, "FIX-LEAD-DRYWALL-1")
    from mbos.runtime import components  # noqa: F401

    with pytest.raises(sa.exc.DBAPIError):
        with sa.create_engine(make_url(rtd.url).set(username="mbos_dbos", password=None)).begin() as c:
            spine_d.record_human_input(c, iid, "quote", "amount_usd", 700, "forged", "michael")
