"""A9 (real spine): PANIC fails closed. A frozen or unreadable switch denies execution, with a receipt, and the
effector is never invoked."""
import pytest

from .conftest import effector_calls_for, invocations


def _act_after_yes(qa, led, mutate):
    from mbos import spine

    out = led.seed(act=False)
    mutate(led)
    with led.engine.begin() as c:
        spine.begin_act(c, out["item_id"], out["action_request_id"], out["approval"])
    g = led.gateway(out["action_request_id"], out["approval"]["approval_id"])
    with led.engine.begin() as c:
        spine.finish_act(c, out["item_id"], out["action_request_id"], out["approval"], g)
    return out, g


BREAKAGES = {
    "global row missing": lambda led: led.superuser_sql("DELETE FROM mbos.governance_flags WHERE key = 'global_freeze'"),
    "malformed value": lambda led: led.superuser_sql(
        "UPDATE mbos.governance_flags SET value = '{\"frozen\": \"no\"}' WHERE key = 'global_freeze'"),
    "value not an object": lambda led: led.superuser_sql(
        "UPDATE mbos.governance_flags SET value = '\"clear\"' WHERE key = 'global_freeze'"),
    "table unreadable": lambda led: led.superuser_sql("ALTER TABLE mbos.governance_flags RENAME TO governance_flags_gone"),
    "L3 frozen": lambda led: led.superuser_sql(
        "UPDATE mbos.governance_flags SET value = '{\"frozen\": true}' WHERE key = 'global_freeze'"),
}


@pytest.mark.parametrize("breakage", sorted(BREAKAGES))
def test_unreadable_or_frozen_switch_denies(qa, led, breakage):
    out, g = _act_after_yes(qa, led, BREAKAGES[breakage])
    assert not g["ok"] and g["checks"]["kill_switch_clear"] is False and g["frozen"], g
    areq = qa.areq(out["action_request_id"], led.engine)
    assert areq["status"] == "cancelled_by_freeze"
    assert qa.item(out["item_id"], led.engine)["state"] == "FAILED"
    assert effector_calls_for(qa, out["action_request_id"], led.engine) == 0 and invocations(qa, areq) == 0
    failed = [r for r in qa.receipts(led.engine, action_request_id=out["action_request_id"]) if r["type"] == "ACTION_FAILED"]
    assert failed, "a denial must itself leave a receipt"


@pytest.mark.parametrize("key", ["capability_freeze:comms.email.send", "agent_freeze:agent-01-coordinator"])
def test_l2_and_l1_freezes_deny(qa, led, key):
    import sqlalchemy as sa

    def freeze(led):
        led.superuser_sql("INSERT INTO mbos.governance_flags (key, value) VALUES (:k, '{\"frozen\": true}')", k=key)

    out, g = _act_after_yes(qa, led, freeze)
    assert not g["ok"] and key in g["reason"]
    del sa


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
