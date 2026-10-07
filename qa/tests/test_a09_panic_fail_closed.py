"""A9 — the L3 PANIC fails closed. With the flag unreadable, the gateway denies everything.
Also covers L1/L2 scoping and L3 cancellation of unstarted actions (ADR-0005 §5)."""
import os

import pytest

from mbos_qa.mocks.governance import GuardDenied

from .conftest import approve, effector_attempts, pending


def _approved(h, **kw):
    item_id, areq = pending(h, **kw)
    return item_id, areq, approve(h, areq)


def _denied_by_kill_switch(h, areq, appr):
    with pytest.raises(GuardDenied) as e:
        h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    assert e.value.check == "7-kill-switch", e.value
    assert effector_attempts(h) == 0
    deny = h.store.receipts(type="POLICY_DECIDED", action_request_id=areq["action_request_id"])[-1]
    assert deny["after_state"]["check"] == "7-kill-switch", "denial must itself leave a receipt"
    return e.value.reason


@pytest.mark.parametrize("breakage", ["missing", "garbage", "empty", "bad_value", "wrong_types", "unreadable"])
def test_unreadable_flag_denies_everything(h, breakage):
    _, areq, appr = _approved(h)
    path = h.kill.path
    if breakage == "missing":
        path.unlink()
    elif breakage == "garbage":
        path.write_text("{not json")
    elif breakage == "empty":
        path.write_text("")
    elif breakage == "bad_value":
        path.write_text('{"global": "MAYBE", "agents_frozen": [], "capabilities_frozen": []}')
    elif breakage == "wrong_types":
        path.write_text('{"global": "CLEAR", "agents_frozen": "none", "capabilities_frozen": []}')
    elif breakage == "unreadable":
        if os.geteuid() == 0:
            pytest.skip("root ignores file permissions")
        path.chmod(0)
    reason = _denied_by_kill_switch(h, areq, appr)
    assert "fail closed" in reason


def test_l3_global_freeze_denies(h):
    _, areq, appr = _approved(h)
    h.kill.set(level="L3", target=None, frozen=True)
    assert "L3" in _denied_by_kill_switch(h, areq, appr)


def test_l2_capability_freeze_is_scoped(h):
    _, areq, appr = _approved(h)  # comms.email.send
    h.kill.set(level="L2", target="comms", frozen=True)
    assert "L2" in _denied_by_kill_switch(h, areq, appr)
    _, areq2, appr2 = _approved(h, action_index=1, listing="B")  # publish.listing.create still allowed
    assert h.gateway.execute(areq2["action_request_id"], appr2["approval_id"]).status == "executed"


def test_l1_agent_freeze_is_scoped(h):
    _, areq, appr = _approved(h)  # proposed_by agent-06-communications
    h.kill.set(level="L1", target="agent-06-communications", frozen=True)
    assert "L1" in _denied_by_kill_switch(h, areq, appr)


def test_l3_panic_cancels_unstarted_actions_and_they_stay_dead(h):
    _, areq, appr = _approved(h)
    _, pend = pending(h, action_index=1, listing="B")
    n = h.gateway.panic_l3({"type": "human", "id": "michael"}, "QA drill")
    assert n == 2
    for a in (areq, pend):
        assert h.store.get("action-request", a["action_request_id"])["status"] == "cancelled_by_freeze"
    assert h.store.receipts(type="KILL_SWITCH_CHANGED")
    h.kill.set(level="L3", target=None, frozen=False)  # even after un-freezing…
    with pytest.raises(GuardDenied):
        h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    assert effector_attempts(h) == 0
