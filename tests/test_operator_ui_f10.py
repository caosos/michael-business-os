"""F-10: morning digest page rendering lane C's C-08 ranking (mbos_economics @ a81a989, installed, not merged)."""

from __future__ import annotations

import re
import sys
import time

import pytest

pytest.importorskip("mbos_economics")

from mbos.adapters.economics import EconomicsEngineScorer  # noqa: E402
from mbos.clock import iso, utcnow  # noqa: E402
from mbos.runtime import components  # noqa: E402
from mbos_economics.digest import build_digest  # noqa: E402
from operator_ui import digest as dv, server  # noqa: E402
from tests.test_operator_ui import item_state, q, req  # noqa: E402

SETTLED = {"AWAITING_APPROVAL", "RESEARCHING", "ARCHIVED", "HELD"}


def _settle(rt, item_id, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if item_state(rt.engine, item_id) in SETTLED:
            return
        time.sleep(0.1)
    raise AssertionError(f"{item_id} did not settle")


@pytest.fixture()
def lane_c(rt, monkeypatch):
    monkeypatch.setattr(components(), "scorer", EconomicsEngineScorer())  # 03's packaged config @ a81a989


def test_digest_page_renders_lane_c_ranking_unchanged(rt, discover, ui, lane_c):
    ids = discover("FIX-TRAILER-1", "FIX-LEAD-DRYWALL-1", "FIX-MOWER-1", "FIX-LEAD-SMARTHOME-1")
    for i in ids.values():
        _settle(rt, i)
    s, _, body = req(ui, "GET", "/digest")
    assert s == 200 and "Morning digest" in body and "mbos_economics.digest" in body
    view = dv.build(ui.store, iso(utcnow()))
    assert view["error"] is None
    open_ours = [i for i in ids.values() if item_state(rt.engine, i) in dv.OPEN_STATES]
    ranked = [r["item_id"] for r in view["digest"]["rows"]]
    assert set(open_ours) <= set(ranked) | {x["item_id"] for x in view["digest"]["excluded"]}
    # the page shows lane C's order unchanged: same as calling build_digest directly on the same items
    eligible = [it for it in ui.store.items_in_states(dv.OPEN_STATES) if dv._engine_scorecard(it) is None]
    direct = build_digest(eligible, view["digest"]["as_of"])
    assert [r["item_id"] for r in direct["rows"]] == ranked and direct["digest_hash"] == view["digest"]["digest_hash"]
    positions = [body.find(f"<code>{r['refs']['scorecard_id']}</code>") for r in view["digest"]["rows"]]
    assert all(p > 0 for p in positions) and positions == sorted(positions)
    for r in view["digest"]["rows"]:
        if r["item_id"] in view["cards"]:
            assert f"/areq/{view['cards'][r['item_id']]}" in body
        pid = r["refs"]["provenance_id"]
        if pid:
            s, _, pbody = req(ui, "GET", f"/provenance/{pid}")
            assert s == 200 and "not found" not in pbody and pid in pbody


def test_placeholder_scored_items_are_listed_not_ranked(rt, discover, ui):
    item_id = discover("FIX-TRAILER-1")["FIX-TRAILER-1"]  # default Components: placeholder scorer
    _settle(rt, item_id)
    view = dv.build(ui.store, iso(utcnow()))
    reasons = {x["item_id"]: x["reason"] for x in view["precheck_excluded"] + (view["digest"] or {}).get("excluded", [])}
    if item_state(rt.engine, item_id) in dv.OPEN_STATES:
        assert item_id not in [r["item_id"] for r in view["digest"]["rows"]]
        assert "not lane C engine output" in reasons[item_id]
    body = req(ui, "GET", "/digest")[2]
    assert "Not ranked" in body


def _fake_view(title):
    row = {"rank": 1, "bucket": "act", "lane": "flip", "category": "trailer", "title": title, "item_id": "itm_X",
           "action": "decide: offer at or below $800", "reason": "YES; EV ...", "window": "later", "deadline": None,
           "value_per_hour": 40.0, "refs": {"scorecard_id": "scr_X", "inputs_hash": "sha256:" + "0" * 64,
                                            "recommendation_id": "rec_X", "provenance_id": None}}
    d = {"as_of": "2026-10-07T17:00:00Z", "horizon_hours": 72, "rows": [row], "excluded": [],
         "counts": {"act_alert": 0, "act": 1, "research": 0, "research_r13": 0}, "digest_hash": "sha256:" + "1" * 64,
         "provenance": {"tool_name": "mbos_economics.digest", "tool_version": "0.3.0", "basis": "INFERENCE"}}
    return {"digest": d, "error": None, "precheck_excluded": [], "cards": {}}


def test_untrusted_title_is_escaped():
    html = server.render_digest(_fake_view("<script>alert(1)</script><a href=x>"))
    assert "<script>" not in html and "&lt;script&gt;" in html and "<a href=x>" not in html


def test_missing_engine_and_engine_failure_are_reported(ui, monkeypatch):
    monkeypatch.setitem(sys.modules, "mbos_economics.digest", None)
    assert dv.build(ui.store, "2026-10-07T17:00:00Z")["error"] == "lane C package mbos_economics is not installed"
    monkeypatch.delitem(sys.modules, "mbos_economics.digest")
    import mbos_economics.digest as real

    monkeypatch.setattr(real, "build_digest", lambda *a, **k: (_ for _ in ()).throw(KeyError("lane")))
    v = dv.build(ui.store, "2026-10-07T17:00:00Z")
    assert v["error"].startswith("build_digest failed: KeyError") and v["digest"] is None
    assert "build_digest failed" in server.render_digest(v)


def test_digest_and_provenance_pages_are_read_only_and_guarded(rt, ui):
    for path in ("/digest", "/provenance/prov_01JA0000000000000000000000"):
        assert req(ui, "GET", path, host="evil.example")[0] == 403
        s, _, body = req(ui, "GET", path)
        assert s == 200 and "<form" not in body.split("<main>")[1]
    assert "not found in mbos.provenance" in req(ui, "GET", "/provenance/prov_01JA0000000000000000000000")[2]
