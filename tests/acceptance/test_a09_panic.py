"""A9. The L3 PANIC fails closed. With the flag unreadable, the gateway denies everything."""

import pytest
import sqlalchemy as sa

from mbos import spine, workflows
from mbos.reference.governance import DryRunEffector, ReferenceGateway, TableKillSwitch
from tests.helpers.common import pending_request, receipts_for, scalar, wait_state
from tests.helpers.seed import seed_flow

pytestmark = pytest.mark.acceptance


def _approved(engine):
    ids = seed_flow(engine, act=False)
    with engine.begin() as c:
        h = c.execute(sa.text("SELECT payload_hash FROM mbos.action_requests")).scalar_one()
        appr = spine.decide(c, ids["action_request_id"], "YES", h, ids["components"])["approval"]
    return ids["action_request_id"], appr["approval_id"]


def _flag(engine, sql):
    with engine.begin() as c:
        c.execute(sa.text(sql))


@pytest.mark.parametrize("breakage", [
    "DELETE FROM mbos.governance_flags WHERE key = 'global_freeze'",                       # missing
    "UPDATE mbos.governance_flags SET value = '\"no\"' WHERE key = 'global_freeze'",         # malformed
    "UPDATE mbos.governance_flags SET value = '{\"frozen\": null}' WHERE key = 'global_freeze'",
    "ALTER TABLE mbos.governance_flags RENAME TO governance_flags_gone",                    # unreadable
    "UPDATE mbos.governance_flags SET value = '{\"frozen\": true}' WHERE key = 'global_freeze'",  # PANIC on
])
def test_gateway_fails_closed(ledger_db, breakage):
    areq_id, appr_id = _approved(ledger_db)
    _flag(ledger_db, breakage)
    res = ReferenceGateway(DryRunEffector(), TableKillSwitch()).execute(ledger_db, areq_id, appr_id)
    assert not res.ok and res.frozen and res.checks["kill_switch_clear"] is False
    assert scalar(ledger_db, "SELECT count(*) FROM mbos.effector_calls") == 0


def test_capability_freeze_l2(ledger_db):
    areq_id, appr_id = _approved(ledger_db)
    with ledger_db.begin() as c:
        spine.set_kill_switch(c, "capability_freeze:comms.email.send", True, reason="A9 L2 test")
    res = ReferenceGateway(DryRunEffector(), TableKillSwitch()).execute(ledger_db, areq_id, appr_id)
    assert not res.ok and "capability_freeze" in res.reason


def test_panic_end_to_end_cancels_the_action(rt, run_discovery):
    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    with rt.engine.begin() as c:
        spine.set_kill_switch(c, "global_freeze", True, reason="A9 PANIC drill")
    try:
        workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"])
        wait_state(rt.engine, item_id, "FAILED")
    finally:
        with rt.engine.begin() as c:
            spine.set_kill_switch(c, "global_freeze", False, reason="A9 drill over")
    assert scalar(rt.engine, "SELECT status FROM mbos.action_requests WHERE action_request_id = :a",
                  a=areq["action_request_id"]) == "cancelled_by_freeze"
    assert scalar(rt.engine, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a",
                  a=areq["action_request_id"]) == 0
    failed = receipts_for(rt.engine, areq=areq["action_request_id"], type="ACTION_FAILED")
    assert len(failed) == 1 and failed[0]["effect"] == "none"
    assert receipts_for(rt.engine, type="KILL_SWITCH_CHANGED")
