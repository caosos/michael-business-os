"""A-15: a follow-up action on an item that already acted goes through the same policy path and approval gate."""

import time

import pytest

from mbos import spine, workflows
from tests.helpers.common import STEP_UP, pending_request, receipts_for, scalar, wait_state


def _acted(rt, run_discovery):
    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    a = pending_request(rt.engine, item_id)
    workflows.record_decision(a["action_request_id"], "YES", a["payload_hash"], auth_context=STEP_UP)
    wait_state(rt.engine, item_id, "ACTED")
    return item_id, a


PA = {"capability": "comms.email.send", "summary": "Follow up: still available? (DRY-RUN draft)",
      "reversibility": "irreversible", "estimated_cost": {"amount": 0, "currency": "USD"}}


def test_followup_goes_through_the_same_gate_and_acts_again(rt, run_discovery):
    item_id, first = _acted(rt, run_discovery)
    out = workflows.propose_followup(item_id, PA)
    assert out["policy_denied"] is False
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    second = pending_request(rt.engine, item_id)
    assert second["action_request_id"] != first["action_request_id"] and second["payload"]["summary"].startswith("Follow up")
    workflows.record_decision(second["action_request_id"], "YES", second["payload_hash"], auth_context=STEP_UP)
    for _ in range(80):  # the gate runs on the `followups` queue worker
        if len(receipts_for(rt.engine, item_id=item_id, type="ACTION_EXECUTED")) == 2:
            break
        time.sleep(0.25)
    assert len(receipts_for(rt.engine, item_id=item_id, type="ACTION_EXECUTED")) == 2, "one execution per request"
    wait_state(rt.engine, item_id, "ACTED")
    assert scalar(rt.engine, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a", a=second["action_request_id"]) == 1


def test_followup_needs_an_item_that_has_acted(rt, run_discovery):
    item_id = run_discovery("FIX-LEAD-SMARTHOME-1")["FIX-LEAD-SMARTHOME-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    with pytest.raises(spine.DecisionRefused, match="already acted"):
        workflows.propose_followup(item_id, PA)
    a = pending_request(rt.engine, item_id)
    workflows.record_decision(a["action_request_id"], "NO", a["payload_hash"], reason="cleanup")
    wait_state(rt.engine, item_id, "ARCHIVED")
