"""A9 (real spine): PANIC fails closed. A frozen or unreadable switch denies execution, with a receipt, and the
effector is never invoked. Backend-neutral: the breakage is applied through `LedgerDB.break_kill_switch`, which
damages whatever PANIC state the gateway under test actually reads (reference: governance_flags; lane E: lane D's
sealed panic_state / panic_read())."""
import pytest

from mbos_qa.impl_spine import LANE_E

from .conftest import effector_calls_for, invocations


def _act_after_yes(qa, led, mutate):
    out = led.seed(act=False)
    mutate(led)
    spine = led._use()
    with led.engine.begin() as c:
        spine.begin_act(c, out["item_id"], out["action_request_id"], out["approval"])
    g = led.gateway(out["action_request_id"], out["approval"]["approval_id"])
    with led.engine.begin() as c:
        spine.finish_act(c, out["item_id"], out["action_request_id"], out["approval"], g)
    return out, g


BREAKAGES = ["L3 frozen", "state emptied", "checksum corrupted", "reader unavailable"]


@pytest.mark.parametrize("breakage", BREAKAGES)
def test_unreadable_or_frozen_switch_denies(qa, led, breakage):
    out, g = _act_after_yes(qa, led, lambda led: led.break_kill_switch(breakage))
    assert not g["ok"], g
    areq = qa.areq(out["action_request_id"], led.engine)
    assert areq["status"] == "cancelled_by_freeze", (areq["status"], g.get("reason"))
    assert qa.item(out["item_id"], led.engine)["state"] == "FAILED"
    assert effector_calls_for(qa, out["action_request_id"], led.engine) == 0 and invocations(qa, areq) == 0
    failed = [r for r in qa.receipts(led.engine, action_request_id=out["action_request_id"]) if r["type"] == "ACTION_FAILED"]
    assert failed, "a denial must itself leave a receipt"
    if not LANE_E:
        assert g["checks"]["kill_switch_clear"] is False and g["frozen"]


@pytest.mark.parametrize("level,target", [("L2", "comms.email.send"), ("L1", "agent-01-coordinator")])
def test_l2_and_l1_freezes_deny(qa, led, level, target):
    out, g = _act_after_yes(qa, led, lambda led: led.freeze_scoped(level, target))
    assert not g["ok"], g
    areq = qa.areq(out["action_request_id"], led.engine)
    assert areq["status"] == "cancelled_by_freeze", (areq["status"], g.get("reason"))
    assert effector_calls_for(qa, out["action_request_id"], led.engine) == 0 and invocations(qa, areq) == 0


def test_l3_freeze_through_the_real_workflow(qa, pending_flip):
    item_id, areq = pending_flip
    qa.freeze("global_freeze", True)
    try:
        qa.decide(areq["action_request_id"], "YES")
        assert qa.wait_state(item_id, {"ACTED", "FAILED"}) == "FAILED"
    finally:
        qa.freeze("global_freeze", False)
    assert qa.areq(areq["action_request_id"])["status"] == "cancelled_by_freeze"
    assert invocations(qa, areq) == 0
    assert [r for r in qa.receipts() if r["type"] == "KILL_SWITCH_CHANGED"], "freeze must be receipted"


def test_a_request_denied_by_a_freeze_cannot_fire_once_the_switch_is_readable_again(qa, led):
    """A denial at execution time must be final. If the denied request stays `approved`, the stale approval executes
    the moment the freeze lifts, although the item already reported FAILED (F-24)."""
    out, g = _act_after_yes(qa, led, lambda led: led.break_kill_switch("reader unavailable"))
    assert not g["ok"]
    led.repair_kill_switch()
    again = led.gateway(out["action_request_id"], out["approval"]["approval_id"])
    areq = qa.areq(out["action_request_id"], led.engine)
    assert not again["ok"] or not qa.effector_rows(led.engine, out["action_request_id"]), \
        f"denied request executed after release: request={areq['status']}, item={qa.item(out['item_id'], led.engine)['state']}"
    assert effector_calls_for(qa, out["action_request_id"], led.engine) == 0 and invocations(qa, areq) == 0
