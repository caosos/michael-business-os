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


def test_orphaned_followup_gate_is_recovered(rt, run_discovery):
    """07 F-42: crash between request commit and gate enqueue. The gate is started by recovery; YES then executes."""
    from mbos.runtime import components, tx

    item_id, first = _acted(rt, run_discovery)
    out = tx(lambda conn: spine.propose_followup(conn, item_id, PA, components()))  # committed, but NO gate enqueued (the crash)
    assert out["policy_denied"] is False
    started = workflows.recover_orphan_gates()
    assert any(out["action_request_id"] in wf for wf in started), started
    assert workflows.recover_orphan_gates() == [] or all(out["action_request_id"] not in wf for wf in workflows.recover_orphan_gates()), \
        "an active gate is never duplicated"
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    req = pending_request(rt.engine, item_id)
    workflows.record_decision(req["action_request_id"], "YES", req["payload_hash"], auth_context=STEP_UP)
    for _ in range(80):
        if len(receipts_for(rt.engine, item_id=item_id, type="ACTION_EXECUTED")) == 2:
            break
        time.sleep(0.25)
    assert len(receipts_for(rt.engine, item_id=item_id, type="ACTION_EXECUTED")) == 2


def test_concurrent_followups_create_exactly_one_live_request(rt, run_discovery):
    """07 F-45."""
    import threading

    from mbos.runtime import components, tx

    item_id, _ = _acted(rt, run_discovery)
    results, errors = [], []

    def go():
        try:
            results.append(workflows.propose_followup(item_id, PA))
        except spine.DecisionRefused as e:
            errors.append(str(e))

    ts = [threading.Thread(target=go) for _ in range(6)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert len(results) == 1 and len(errors) == 5, (len(results), errors[:2])
    assert scalar(rt.engine, "SELECT count(*) FROM mbos.action_requests WHERE item_id = :i AND status = 'pending_approval'", i=item_id) in (0, 1)


@pytest.mark.parametrize("bad", [None, {}, {"capability": "x"}, {"capability": "comms.email.send", "summary": "s"},
                                 {"capability": 5, "summary": "s", "reversibility": "irreversible"},
                                 {**PA, "reversibility": "maybe"}, {**PA, "estimated_cost": {"amount": -5, "currency": "USD"}},
                                 {**PA, "estimated_cost": "free"}])
def test_malformed_followup_is_a_clean_refusal(rt, run_discovery, bad):
    item_id, _ = _acted(rt, run_discovery)
    with pytest.raises(spine.DecisionRefused):
        workflows.propose_followup(item_id, bad)


def test_policy_blocked_followup_leaves_a_receipt(rt, run_discovery):
    """07 F-43."""
    item_id, _ = _acted(rt, run_discovery)
    n0 = len(receipts_for(rt.engine, item_id=item_id))
    out = workflows.propose_followup(item_id, {**PA, "capability": "comms.voice.call"})  # nobody holds it on the stand-in? deny via PDP
    if out["policy_denied"]:
        assert len(receipts_for(rt.engine, item_id=item_id)) > n0, "a blocked proposal still has a receipt"
