"""F-38: the glanceable Today cards. All data here is LABELLED TEST DATA (hosts under .invalid; titles say TEST)."""
import re

from operator_ui import glance_view as gv
from tests.conftest import PIN
from tests.test_operator_ui import approvals, post, ready, req, wait_state, q


def item(**kw):
    base = {"item_id": "itm_T1", "type": "flip", "state": "AWAITING_APPROVAL",
            "normalized": {"title": "TEST DATA <b>mower</b>", "location": {"city": "Conway", "state": "AR"}},
            "sources": [{"source": "craigslist", "url": "https://example.invalid/x"}],
            "economics": {"acquisition": {"expected_buy_price": 100, "buy_fees": 5}, "rehab": {"parts_cost": 20, "materials_cost": 10},
                          "resale": {"target_sell_price": 300}},
            "recommendation": {"verdict": "YES", "confidence": 0.7, "rationale": ["TEST reason"], "cheapest_decisive_evidence": "TEST: check it starts"},
            "scores": {"scorecard": {"derived": {"ev_net_profit": 120, "ev_profit_per_hour": 30}}}}
    base.update(kw)
    return base


AREQ = {"action_request_id": "areq_T1", "status": "pending_approval", "capability": "x", "payload": {"summary": "TEST step"},
        "payload_hash": "sha256:" + "a" * 64, "reversibility": "reversible", "category": "read", "tier": 1}


def test_opportunity_fields_and_labels():
    o = gv.opportunity(item(), AREQ)
    assert (o["buy"], o["all_in"], o["sell"], o["net"], o["pph"]) == (100, 135, 300, 120, 30)
    assert o["label"] == "SIMULATED" and o["verdict"] == "YES"  # .invalid host = test data
    real = gv.opportunity(item(sources=[{"source": "s", "url": "https://real.test/x"}]), AREQ)
    assert real["label"] == "UNVERIFIED"  # a stored estimate is never "confirmed"


def test_missing_figures_are_unknown_not_invented():
    it = item(economics={}, scores={})
    o = gv.opportunity(it, AREQ)
    assert o["all_in"] is None and o["net"] is None and o["pph"] is None
    assert o["verdict"] == "MAYBE" and o["verdict_note"]  # YES without a stored profit is shown as MAYBE
    assert gv.opportunity(item(sources=[{"source": "s", "url": "https://real.test"}], economics={}, scores={}), AREQ)["label"] == "SPECULATIVE"
    h = gv.render({"done": [], "working": [], "blocked": [], "opportunities": [dict(o, hash_ok=True)], "next": None}, "tok")
    assert "UNKNOWN" in h


def test_unsafe_url_and_html_are_not_rendered_live():
    o = gv.opportunity(item(sources=[{"source": "s", "url": "javascript:alert(1)"}]), AREQ)
    assert o["url"] is None
    h = gv.render({"done": [], "working": [], "blocked": [], "opportunities": [dict(o, hash_ok=True)], "next": None}, "tok")
    assert "<b>mower" not in h and "javascript:" not in h


def test_top3_visible_rest_collapsed_and_controls_are_existing_ones():
    opps = [dict(gv.opportunity(item(item_id=f"itm_{i}"), dict(AREQ, action_request_id=f"areq_{i}")), hash_ok=True) for i in range(5)]
    h = gv.render({"done": [], "working": [], "blocked": [], "opportunities": opps, "next": None}, "tok")
    assert h.count('class="opp"') == 5 and "<details><summary>2 more" in h
    assert h.index("<details>") > h.index("itm_2") and h.index("itm_3") > h.index("<details>")
    assert set(re.findall(r'name="decision" value="(\w+)"', h)) == {"YES", "HOLD", "NO"}
    assert "More details" in h and "Approve" in h and "Pass" in h and "MODIFY" not in h
    assert "type=\"password\"" not in h  # reversible: no PIN box


def test_done_is_receipt_backed_and_blocked_is_the_only_red():
    done = [{"item_id": "i", "title": "TEST done", "seq": 7, "receipt_type": "ACTION_EXECUTED", "net": None, "label": "SIMULATED", "dry_run": True}]
    h = gv.render({"done": done, "working": [], "blocked": [], "opportunities": [], "next": None}, "t")
    assert "receipt #7" in h and "&#10003;" in h and "dry-run: nothing real happened" in h and "CONFIRMED" not in h
    assert "Nothing is blocked" in h and 'class="gc blk' not in h
    b = gv.render({"done": [], "working": [], "blocked": [{"what": "TEST", "action": "do X", "red": True}], "opportunities": [], "next": None}, "t")
    assert 'gc blk"' in b and "Your action: do X" in b


# ---- real server, real spine: every click is a real transition ----
def test_today_http_shows_cards_and_pass_click_is_real(rt, discover, ui):
    item_id, areq = ready(rt, discover, "FIX-LEAD-SMARTHOME-1")
    s, _, body = req(ui, "GET", "/queue?demo=1")
    assert s == 200
    for t in ("<h2>Done</h2>", "<h2>Working</h2>", "<h2>Blocked</h2>", "<h2>Opportunities</h2>", "<h2>Next</h2>", "More details", "Approve", "SIMULATED"):
        assert t in body, t
    assert f'/areq/{areq["action_request_id"]}/decide' in body
    assert "CONFIRMED" not in body  # no earnings claim without an outcome receipt
    _, loc, _ = post(ui, areq, "NO", reason="TEST: outside area", **{"return": "item"})
    assert "msg=NO recorded" in loc
    wait_state(rt.engine, item_id, "ARCHIVED")
    assert approvals(rt.engine, areq["action_request_id"])[0]["decision"] == "NO"


def test_today_http_approve_needs_pin_then_done_shows_receipt(rt, discover, ui):
    item_id, areq = ready(rt, discover, "FIX-TRAILER-1")
    _, _, body = req(ui, "GET", "/queue?demo=1")
    assert 'placeholder="PIN"' in body  # the irreversible YES still asks for the PIN
    _, loc, _ = post(ui, areq, "YES")
    assert "err=" in loc and approvals(rt.engine, areq["action_request_id"]) == []
    post(ui, areq, "YES", pin=PIN)
    wait_state(rt.engine, item_id, "ACTED")
    _, _, body = req(ui, "GET", "/queue?demo=1")
    seq = q(rt.engine, "SELECT seq FROM mbos.receipts WHERE action_request_id = :a AND type='ACTION_EXECUTED'", a=areq["action_request_id"])[0][0]
    assert f"receipt #{seq}" in body and "dry-run: nothing real happened" in body and "CONFIRMED" not in body
