"""F-11: follow-up / offer / quote buttons on the card. Each creates its OWN step-up ActionRequest through the public API
(workflows.propose_followup, A-15) on lane D + lane E. Nothing is sent until Michael's separate YES."""

from __future__ import annotations

import re

import pytest

from tests.conftest import PIN
from tests.lane_d.test_ui_on_lane_d import post, q, ready, req, state, wait


def acted(ui, discover_d, listing="FIX-TRAILER-1"):
    item_id, areq = ready(ui, discover_d, listing)
    post(ui, areq, "YES", pin=PIN)
    wait(lambda: state(ui, item_id) == "ACTED")
    return item_id, areq


def fu(ui, item_id, **form):
    return req(ui, "POST", f"/item/{item_id}/followup", {"csrf": ui.csrf, **form})


def new_request(ui, item_id, old_id):
    return wait(lambda: next((a for a in ui.store.action_requests_for_item(item_id)
                              if a["action_request_id"] != old_id and a["status"] == "pending_approval"), None))


@pytest.fixture()
def comms(monkeypatch):
    from comms_spec.planner import CommsActionPlanner
    from mbos.runtime import components

    monkeypatch.setattr(components(), "planner", CommsActionPlanner())


def test_buttons_appear_only_once_the_first_action_has_acted(rtd, discover_d, ui_d):
    item_id, areq = ready(ui_d, discover_d)
    body = req(ui_d, "GET", f"/item/{item_id}")[2]
    assert "Draft follow-up questions" not in body                      # a request is still waiting on Michael
    post(ui_d, areq, "YES", pin=PIN)
    wait(lambda: state(ui_d, item_id) == "ACTED")
    body = req(ui_d, "GET", f"/item/{item_id}")[2]
    assert "Draft follow-up questions" in body and "Draft an offer (BINDING)" in body and "Draft a quote" not in body
    assert body.index("<h2>Recommendation</h2>") < body.index("Draft follow-up questions")


def test_followup_questions_become_their_own_request_and_run_after_a_fresh_yes(rtd, discover_d, ui_d, comms):
    item_id, first = acted(ui_d, discover_d)
    s, loc, _ = fu(ui_d, item_id, kind="followup")
    assert s == 303 and loc.startswith(f"/item/{item_id}?msg=Follow-up questions drafted (areq_"), loc
    new = new_request(ui_d, item_id, first["action_request_id"])
    assert new["proposed_by"] == "agent-06-communications" and new["payload"]["comms"]["template_id"] == "seller_followup_questions"
    assert new["action_request_id"] != first["action_request_id"] and "lane" not in new["payload"]
    assert state(ui_d, item_id) == "AWAITING_APPROVAL"
    assert q(rtd, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a", a=new["action_request_id"])[0][0] == 0   # nothing sent
    body = req(ui_d, "GET", f"/item/{item_id}")[2]
    assert ">YES<" in body and "Draft follow-up questions" not in body       # decide it first
    _, loc, _ = post(ui_d, new, "YES")
    assert "err=" in loc and "PIN" in loc                                       # irreversible: step-up still required
    _, loc, _ = post(ui_d, new, "YES", pin=PIN)
    assert "msg=YES recorded" in loc
    wait(lambda: state(ui_d, item_id) == "ACTED" and ui_d.store.action_request(new["action_request_id"])["status"] == "executed")
    assert q(rtd, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a", a=new["action_request_id"])[0][0] == 1
    assert [r["type"] for r in ui_d.store.receipts(areq_id=new["action_request_id"])].count("ACTION_EXECUTED") == 1


def test_offer_is_binding_tier0_step_up_and_never_above_the_ask(rtd, discover_d, ui_d, comms):
    item_id, first = acted(ui_d, discover_d)
    ask = ui_d.store.item(item_id)["normalized"]["price"]["amount"]
    before = len(ui_d.store.action_requests_for_item(item_id))
    for form, reason in [({"amount": str(ask + 100)}, "above the asking price"), ({"amount": "abc"}, "must be a number"),
                         ({"amount": "0"}, "positive dollar amount")]:
        s, _, body = fu(ui_d, item_id, kind="offer", **form)
        assert s == 200 and "Not created." in body and reason in body, (form, body[-800:])
    assert len(ui_d.store.action_requests_for_item(item_id)) == before            # nothing created by a refusal
    s, loc, _ = fu(ui_d, item_id, kind="offer", amount=str(ask - 100), pickup_window="Saturday", expires="Sunday 6pm")
    assert s == 303 and "Offer drafted" in loc
    off = new_request(ui_d, item_id, first["action_request_id"])
    assert off["category"] == "offer" and off["tier"] == 0 and off["reversibility"] == "irreversible"
    assert off["payload"]["comms"]["is_binding"] is True and off["proposed_by"] == "agent-06-communications"
    _, loc, _ = post(ui_d, off, "YES")
    assert "err=" in loc and "PIN" in loc
    assert q(rtd, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a", a=off["action_request_id"])[0][0] == 0
    post(ui_d, off, "NO", reason="test cleanup")


def test_quote_on_a_service_item(rtd, discover_d, ui_d, comms):
    item_id, first = acted(ui_d, discover_d, "FIX-LEAD-SMARTHOME-1")
    body = req(ui_d, "GET", f"/item/{item_id}")[2]
    assert "Draft a quote (BINDING)" in body and "Draft an offer" not in body
    s, _, out = fu(ui_d, item_id, kind="quote", amount="450", scope="two patches", deposit_pct="80")
    assert s == 200 and "Not created." in out and "deposit_pct must be an integer 0-50" in out
    s, loc, _ = fu(ui_d, item_id, kind="quote", amount="450", scope="two 12in patches + texture match", deposit_pct="25", expires="Friday")
    assert s == 303 and "Quote drafted" in loc
    q_ = new_request(ui_d, item_id, first["action_request_id"])
    assert q_["category"] == "offer" and q_["payload"]["comms"]["template_id"] == "customer_quote"
    post(ui_d, q_, "NO", reason="test cleanup")


def test_guards_and_refusals(rtd, discover_d, ui_d, comms):
    item_id, first = ready(ui_d, discover_d)                                       # NOT acted yet
    s, _, body = fu(ui_d, item_id, kind="followup")                                # a forged POST while a request is open
    assert s == 200 and "Not created." in body and "already acted" in body
    assert req(ui_d, "POST", f"/item/{item_id}/followup", {"kind": "followup"})[2].count("invalid form token") >= 1
    assert req(ui_d, "POST", f"/item/{item_id}/followup", {"csrf": ui_d.csrf, "kind": "followup"}, host="evil.example")[0] == 403
    s, _, body = fu(ui_d, item_id, kind="gossip")
    assert "unknown follow-up kind" in body
    s, _, body = req(ui_d, "POST", "/item/itm_01JA0000000000000000009999/followup", {"csrf": ui_d.csrf, "kind": "followup"})
    assert s == 404
    assert len([a for a in ui_d.store.action_requests_for_item(item_id)]) == 1


def test_ui_process_path_creates_the_request_and_the_worker_runs_its_gate(rtd, discover_d, ui_d, comms, policy_path, tmp_path):
    """The real deployment shape: the UI is a SEPARATE process (runtime initialised with launch=False, gate enqueued through
    a DBOS client); the launched worker (this test process) picks the gate up. Run `make_backend` in a child process."""
    import json
    import os
    import subprocess
    import sys

    item_id, first = acted(ui_d, discover_d)
    script = (
        "import json,sys\n"
        "from operator_ui.__main__ import make_backend\n"
        "from operator_ui import ux\n"
        f"b = make_backend()\nitem = b.item({item_id!r})\n"
        "pa = ux.build_followup(item, {'kind': 'followup'}, b.asked_question_ids(item['item_id']))\n"
        "out = b.propose_followup(item['item_id'], pa)\n"
        "print('RESULT ' + json.dumps(out), flush=True)\n"
        "import os; os._exit(0)\n")
    env = {**os.environ, "MBOS_DATABASE_URL": rtd.settings.database_url, "MBOS_SYSTEM_DATABASE_URL": rtd.settings.system_database_url,
           "MBOS_STATE_BACKEND": "lane_d", "MBOS_POLICY_PATH": policy_path}
    cp = subprocess.run([sys.executable, "-c", script], env=env, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]),
                        capture_output=True, text=True, timeout=120)
    assert cp.returncode == 0, cp.stdout[-1500:] + cp.stderr[-2500:]
    out = json.loads(next(ln for ln in cp.stdout.splitlines() if ln.startswith("RESULT ")).split(" ", 1)[1])
    assert out["policy_denied"] is False and out["action_request_id"]
    new = new_request(ui_d, item_id, first["action_request_id"])
    assert new["action_request_id"] == out["action_request_id"]
    post(ui_d, new, "YES", pin=PIN)                                                  # the worker's gate (enqueued by the child) executes it
    wait(lambda: ui_d.store.action_request(new["action_request_id"])["status"] == "executed")
