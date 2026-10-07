"""F-04: the Operator UI on lane D with lane E's REAL gateway, PDP and kill switch (human channel only, R14).

Every decision goes through mbos.spine_d.decide; execution happens only in the DBOS item workflow → Agent 05's
ActionGateway → dry-run effector (R4: the gateway owns the action-status receipts)."""

from __future__ import annotations

import http.client
import json
import re
import time
from urllib.parse import unquote, urlencode

import pytest
import sqlalchemy as sa

from mbos import spine_d
from mbos.hashing import sha256_of
from tests.conftest import PIN

pytestmark = pytest.mark.lane_d


# ---------------------------------------------------------------- helpers
def req(ui, method, path, form=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", ui.port, timeout=20)
    body = urlencode(form) if form else None
    hdr = {"Host": host or f"127.0.0.1:{ui.port}"}
    if body:
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
    c.request(method, path, body=body, headers=hdr)
    r = c.getresponse()
    return r.status, unquote(r.getheader("Location") or ""), r.read().decode()


def wait(fn, timeout=40.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    raise AssertionError("condition not reached")


def state(ui, item_id):
    return ui.store.item(item_id)["state"]


def ready(ui, discover_d, listing="FIX-TRAILER-1"):
    item_id = discover_d(listing)[listing]
    wait(lambda: state(ui, item_id) == "AWAITING_APPROVAL")
    areq = wait(lambda: next((a for a in ui.store.action_requests_for_item(item_id) if a["status"] == "pending_approval"), None))
    return item_id, areq


def post(ui, areq, decision, **f):
    return req(ui, "POST", f"/areq/{areq['action_request_id']}/decide",
               {"csrf": ui.csrf, "decision": decision, "payload_hash_seen": areq["payload_hash"], **f})


def rtypes(ui, areq_id):
    return [r["type"] for r in ui.store.receipts(areq_id=areq_id)]


def q(rtd, sql, **p):
    with rtd.engine.connect() as c:
        return c.execute(sa.text(sql), p).all()


# ---------------------------------------------------------------- wiring
def test_components_are_lane_e_and_backend_is_lane_d(rtd, ui_d):
    from mbos.runtime import components

    c = components()
    assert type(c.gateway).__module__.startswith("mbos_governance") and type(c.pdp).__module__.startswith("mbos_governance")
    assert type(c.kill_switch).__module__.startswith("mbos_governance")
    assert ui_d.store.lane == "lane_d" and ui_d.store.components is c  # the UI uses the worker's Components
    assert ui_d.store._spine is spine_d
    assert ui_d.store.system_state() == "RUNNING"


def test_queue_card_and_pages_render_on_lane_d(rtd, discover_d, ui_d):
    item_id, areq = ready(ui_d, discover_d)
    s, _, body = req(ui_d, "GET", "/")
    assert s == 200 and "Needs your decision" in body and "System says" in body and "system RUNNING" in body
    s, _, card = req(ui_d, "GET", f"/areq/{areq['action_request_id']}")
    for text in ("Why the system recommends this", "Economics", "Provenance", areq["payload_hash"], "Step-up PIN",
                 "verified (MBOS-CJSON-1)", "ACTION_PROPOSED"):
        assert text in card, text
    assert "MISSING" not in card
    for path in ("/ledger", "/holds", "/outcomes", "/sources", "/summary", "/digest"):
        assert req(ui_d, "GET", path)[0] == 200, path
    ledger = req(ui_d, "GET", "/ledger")[2]
    assert "chain verified" in ledger and "independent MBOS-RH-1 check (vendored reference): " in ledger
    assert "FAILED" not in ledger.split("independent MBOS-RH-1 check")[1].split("</span>")[0]
    assert req(ui_d, "GET", "/", host="evil.example")[0] == 403


# ---------------------------------------------------------------- YES through lane E's real gateway
def test_yes_runs_through_the_real_gateway_exactly_once(rtd, discover_d, ui_d):
    item_id, areq = ready(ui_d, discover_d)
    _, loc, _ = post(ui_d, areq, "YES")
    assert "err=" in loc and "PIN" in loc                               # step-up still required
    assert ui_d.store.approvals_for(areq["action_request_id"]) == []
    _, loc, _ = post(ui_d, areq, "YES", pin=PIN)
    assert "msg=YES recorded" in loc, loc
    wait(lambda: state(ui_d, item_id) == "ACTED")
    (appr,) = ui_d.store.approvals_for(areq["action_request_id"])
    assert appr["channel"] == "web" and appr["auth_context"]["step_up"] is True
    t = rtypes(ui_d, areq["action_request_id"])
    assert t.count("ACTION_EXECUTING") == 1 and t.count("ACTION_EXECUTED") == 1       # R4: one per edge, by the gateway
    ((calls, live),) = q(rtd, "SELECT count(*), count(*) FILTER (WHERE dry_run IS NOT TRUE) FROM mbos.effector_calls "
                              "WHERE action_request_id = :a", a=areq["action_request_id"])
    assert (calls, live) == (1, 0)
    ex = next(r for r in ui_d.store.receipts(areq_id=areq["action_request_id"]) if r["type"] == "ACTION_EXECUTED")
    assert ex["effector_response"]["dry_run"] is True and ex["payload_hash"] == areq["payload_hash"]
    assert sha256_of(areq["payload"]) == areq["payload_hash"]
    assert ui_d.store.verify_chain()["ok"] is True
    ok, msg = ui_d.store.verify_chain_independent()
    assert ok, msg
    _, loc, _ = post(ui_d, areq, "YES", pin=PIN)                         # double submit
    assert "err=" in loc
    assert q(rtd, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a", a=areq["action_request_id"])[0][0] == 1


def test_frozen_system_denies_at_the_real_gateway(rtd, discover_d, ui_d):
    item_id, areq = ready(ui_d, discover_d)
    with rtd.engine.begin() as c:
        spine_d.set_kill_switch(c, "global_freeze", True, reason="F-04 test: freeze before YES")
    try:
        assert ui_d.store.system_state() == "FROZEN" and "system FROZEN" in req(ui_d, "GET", "/")[2]
        _, loc, _ = post(ui_d, areq, "YES", pin=PIN)
        assert "msg=YES recorded" in loc                                  # the human decision is recorded...
        wait(lambda: state(ui_d, item_id) == "FAILED")                    # ...and the real gateway refuses to act
        # R20 / E-12 (Agent 05 @ 408bcad): a freeze-refused approved request becomes `cancelled_by_freeze`, so the
        # approval is not silently reusable after a release. Michael re-approves. (This pinned `approved` before E-12.)
        assert ui_d.store.action_request(areq["action_request_id"])["status"] == "cancelled_by_freeze"
        assert "ACTION_FAILED" in rtypes(ui_d, areq["action_request_id"])
        assert q(rtd, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a", a=areq["action_request_id"])[0][0] == 0
        assert "ACTION_EXECUTED" not in rtypes(ui_d, areq["action_request_id"])
    finally:
        with rtd.engine.begin() as c:
            spine_d.set_kill_switch(c, "global_freeze", False, reason="F-04 test: release")


# ---------------------------------------------------------------- NO / MODIFY / HOLD on lane D
def test_no_requires_reason_and_archives(rtd, discover_d, ui_d):
    item_id, areq = ready(ui_d, discover_d, "FIX-LEAD-SMARTHOME-1")
    _, loc, _ = post(ui_d, areq, "NO", reason="  ")
    assert "err=NO requires a reason" in loc
    _, loc, _ = post(ui_d, areq, "NO", reason="outside service area")
    assert "msg=NO recorded" in loc
    wait(lambda: state(ui_d, item_id) == "ARCHIVED")
    assert ui_d.store.approvals_for(areq["action_request_id"])[0]["reason"] == "outside service area"


def test_modify_creates_successor_classified_by_the_real_pdp(rtd, discover_d, ui_d):
    item_id, old = ready(ui_d, discover_d)
    edited = dict(old["payload"], summary="Offer $700 cash, pickup Saturday (DRY-RUN draft)")
    _, loc, _ = post(ui_d, old, "MODIFY", new_payload=json.dumps(edited), note="start lower")
    new_id = re.search(r"/areq/(areq_\w+)\?msg=MODIFY recorded", loc).group(1)
    new = wait(lambda: (lambda a: a if a and a["status"] == "pending_approval" else None)(ui_d.store.action_request(new_id)))
    assert new["derived_from"] == old["action_request_id"] and new["payload"] == edited
    assert new["payload_hash"] == sha256_of(edited) != old["payload_hash"]
    assert ui_d.store.action_request(old["action_request_id"])["status"] == "rejected"
    assert "POLICY_DECIDED" in rtypes(ui_d, new_id)                         # Agent 05's PDP decided the successor
    pol = next(r for r in ui_d.store.receipts(areq_id=new_id) if r["type"] == "POLICY_DECIDED")
    assert pol.get("policy_decision_ref") or "policy" in json.dumps(pol).lower()
    assert q(rtd, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = ANY(:a)", a=[old["action_request_id"], new_id])[0][0] == 0
    post(ui_d, new, "YES", pin=PIN)
    wait(lambda: state(ui_d, item_id) == "ACTED")


def test_hold_then_wake_now_re_presents_and_never_executes(rtd, discover_d, ui_d):
    item_id, areq = ready(ui_d, discover_d)
    _, loc, _ = post(ui_d, areq, "HOLD", hold_preset="3d", reason="waiting for photos")
    assert "msg=HOLD recorded" in loc
    wait(lambda: state(ui_d, item_id) == "HELD")
    assert areq["action_request_id"] in req(ui_d, "GET", "/holds")[2]
    assert "Wake now" in req(ui_d, "GET", f"/areq/{areq['action_request_id']}")[2]
    _, loc, _ = req(ui_d, "POST", f"/areq/{areq['action_request_id']}/wake", {"csrf": ui_d.csrf})
    assert "msg=Wake sent" in loc
    wait(lambda: state(ui_d, item_id) == "AWAITING_APPROVAL")
    assert q(rtd, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a", a=areq["action_request_id"])[0][0] == 0


def test_outcome_entry_on_lane_d_records_web_channel(rtd, discover_d, ui_d):
    item_id, areq = ready(ui_d, discover_d)
    post(ui_d, areq, "YES", pin=PIN)
    wait(lambda: state(ui_d, item_id) == "ACTED")
    _, loc, _ = req(ui_d, "POST", f"/areq/{areq['action_request_id']}/outcome",
                    {"csrf": ui_d.csrf, "kind": "flip_sold", "revenue": "2050", "total_cost": "1100", "hours": "7.5"})
    assert "msg=Outcome flip_sold recorded" in loc, loc
    (o,) = ui_d.store.outcomes(item_id)
    assert o["realized"]["net_profit"] == 950 and o["predicted_vs_actual"]
    assert state(ui_d, item_id) == "OUTCOME_RECORDED"
    assert ui_d.store.provenance(o["provenance_ids"][0])["tool_name"] == "mbos.web.outcome"
    assert "flip_sold" in req(ui_d, "GET", "/outcomes")[2]


# ---------------------------------------------------------------- comms ledger on lane D (D-10 / migration 0011)
def test_comms_ledger_schema_is_owner_managed_on_lane_d(rtd):
    from comms_spec import ledger as L

    assert L.ensure_schema(rtd.engine) == "skipped"                          # migration 0011 owns mbos_comms


# ---------------------------------------------------------------- F-13: the opportunity card on lane D + lane E
def test_opportunity_card_on_lane_d_with_zero_enrichment(rtd, discover_d, ui_d):
    item_id, areq = ready(ui_d, discover_d)
    s, _, body = req(ui_d, "GET", f"/item/{item_id}")
    assert s == 200
    for h in ("Listing activity", "Seller", "Why it is interesting", "Estimated numbers", "Value-add plan", "Seasonality",
              "Transport", "System status", "Recommendation", "Your decision", "Activity trail", "UNKNOWN ("):
        assert h in body, h
    res = ui_d.store.opportunity_card(item_id)
    assert res["errors"] == [] and res["card"]["unknowns"]
    for r in ui_d.store.receipts(item_id=item_id):                   # R17: every receipt is in the trail
        assert r["receipt_id"] in body, r["type"]
    assert body.index("<h2>Recommendation</h2>") < body.index(">YES<") and 'name="return" value="item"' in body
    assert f'href="/item/{item_id}"' in req(ui_d, "GET", "/")[2]


def test_decide_from_the_card_on_lane_d_returns_to_the_card_and_executes_once(rtd, discover_d, ui_d):
    item_id, areq = ready(ui_d, discover_d)
    _, loc, _ = post(ui_d, areq, "YES", pin=PIN, **{"return": "item"})
    assert loc.startswith(f"/item/{item_id}?msg=YES recorded"), loc
    wait(lambda: state(ui_d, item_id) == "ACTED")
    body = req(ui_d, "GET", f"/item/{item_id}")[2]
    assert "ACTION_EXECUTED" in body or "executed" in body.lower()
    assert q(rtd, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a", a=areq["action_request_id"])[0][0] == 1
    for r in ui_d.store.receipts(item_id=item_id):
        assert r["receipt_id"] in body
    assert req(ui_d, "GET", "/item/itm_01JA0000000000000000009999")[0] == 404


# ---------------------------------------------------------------- F-15: lane E stamps proposed_by from the drafting lane
def test_proposed_by_is_the_drafting_lane_in_the_ledger(rtd, discover_d, ui_d, monkeypatch):
    from comms_spec.planner import CommsActionPlanner
    from mbos.runtime import components

    monkeypatch.setattr(components(), "planner", CommsActionPlanner())
    item_id, areq = ready(ui_d, discover_d)
    assert areq["proposed_by"] == "agent-06-communications", areq["proposed_by"]
    assert "lane" not in areq["payload"] and areq["payload"]["comms"]["template_id"] == "seller_first_inquiry"
    ((pb,),) = q(rtd, "SELECT proposed_by FROM mbos.action_requests WHERE action_request_id = :a", a=areq["action_request_id"])
    assert pb == "agent-06-communications"                                          # the ledger row names the drafting lane
    assert any(r["type"] == "ACTION_PROPOSED" for r in ui_d.store.receipts(areq_id=areq["action_request_id"]))


def test_capability_nobody_holds_creates_no_request(rtd, discover_d, ui_d, monkeypatch):
    from mbos.runtime import components

    class Rogue:  # an action tagged with our lane for a capability lane E gives to nobody
        def plan(self, item):
            return [{"capability": "comms.fax.send", "summary": "fax the seller", "reversibility": "irreversible",
                     "estimated_cost": {"amount": 0, "currency": "USD"}, "lane": "agent-06-communications"}]

    monkeypatch.setattr(components(), "planner", Rogue())
    item_id = discover_d("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait(lambda: any(r["type"] == "RECOMMENDATION_RECORDED" for r in ui_d.store.receipts(item_id=item_id)))
    time.sleep(3)                                                                  # give the workflow every chance to propose
    assert ui_d.store.action_requests_for_item(item_id) == []                      # no request, so nothing to approve
    assert state(ui_d, item_id) != "AWAITING_APPROVAL"
    card = ui_d.store.opportunity_card(item_id)
    assert card["errors"] == [] and "policy blocked" in card["card"]["recommendation"]["why"]
    body = req(ui_d, "GET", f"/item/{item_id}")[2]
    assert "No open request is waiting for a decision" in body and ">YES<" not in body     # nothing to decide on
    assert "policy blocked" in body                                                # the card says why


def test_planner_payloads_never_carry_a_key_lane_e_reserves_for_binding_offers(policy_path):
    """Found with F-15: 05's PDP denies any comms.*/publish.* payload that has a key named `binding` (even `binding: false`)
    at ANY depth, so a flag named `binding` made every first contact 'policy blocked'. Pin ours against the real policy."""
    from comms_spec.planner import CommsActionPlanner
    from mbos_governance.policy import _payload_keys
    import json as _json

    reserved = {k.lower() for k in _json.load(open(policy_path))["recommendation_actions"]["binding_payload_keys"]}
    item = _json.loads((__import__("pathlib").Path(__file__).resolve().parents[2] / "docs/research/contracts/examples/item-flip-trailer.example.json").read_text())
    p = CommsActionPlanner()
    acts = p.plan(item) + p.plan_followup(item) + p.plan_offer(item, 900, "Saturday", "Sunday")
    assert acts
    for a in acts:
        if a["capability"].startswith(("comms.", "publish.")):
            keys = {str(k).lower() for k in _payload_keys({"comms": a["comms"]})}
            assert not (keys & reserved), (a["capability"], keys & reserved)
