"""E-13: 07's G-04 release blockers — F-24 (denied approvals die), F-25/R22 (durable provider; see test_e05),
F-22 (publish.* propose-only grants)."""
from __future__ import annotations

import pytest

from mbos_governance import PolicyStore, decide
from mbos_governance.ids import new_id, payload_hash
from mbos_governance.panic import FROZEN, PanicState

from .test_e12_recommendation_actions import ar_for


def _sends(env, areq):
    return env.sql("SELECT count(*) FROM mbos.effector_calls WHERE action_request_id=%s", (areq,))[0][0]


# ---------------------------------------------------------------- F-24
SWITCH_FAULTS = ["L3 frozen before the YES", "state emptied", "checksum corrupted", "reader unavailable", "L2", "L1"]


def break_switch(env, how):
    if how == "L3 frozen before the YES":
        env.freeze_sql("L3", reason="frozen before the YES")
    elif how == "state emptied":
        env.sql("DELETE FROM mbos.panic_state", replica=True)
    elif how == "checksum corrupted":
        env.sql("UPDATE mbos.panic_state SET body = jsonb_set(body, '{agents}', '{\"x\": {}}') "
                "WHERE revision = (SELECT max(revision) FROM mbos.panic_state)", replica=True)
    elif how == "reader unavailable":
        env.gw.panic.read = lambda: PanicState(FROZEN, readable=False, error="UndefinedFunction: mbos.panic_read() does not exist")
    elif how == "L2":
        env.gw.engage_panic("L2", "comms.email.send", "michael", "incident")
    elif how == "L1":
        env.gw.engage_panic("L1", "agent-06-communications", "michael", "incident")


def repair_switch(env, how):
    """The switch becomes readable / released again (an UNRELATED PANIC release)."""
    if how == "reader unavailable":
        del env.gw.panic.read                                    # back to the class method
    if how in ("L3 frozen before the YES", "state emptied", "checksum corrupted", "reader unavailable"):
        env.gw.release_panic("L3", None, "michael", "repaired / all clear")
    elif how == "L2":
        env.gw.release_panic("L2", "comms.email.send", "michael", "all clear")
    else:
        env.gw.release_panic("L1", "agent-06-communications", "michael", "all clear")


@pytest.mark.parametrize("how", SWITCH_FAULTS)
def test_a_request_denied_by_a_freeze_cannot_fire_once_the_switch_is_readable_again(env, how):
    """07's regression (F-24): the denial settles the approval; repairing the switch must not revive it."""
    ar = env.propose("email")
    areq = ar["action_request_id"]
    if how == "L3 frozen before the YES":
        break_switch(env, how)
        assert env.gw.record_approval(env.approval(ar)).status == "approved"       # YES recorded while frozen
    else:
        assert env.gw.record_approval(env.approval(ar)).status == "approved"
        break_switch(env, how)
    res = env.gw.execute(areq)
    assert res.outcome == "refused" and any(r.startswith("G7:PANIC_") for r in res.reasons), res
    assert res.status == "cancelled_by_freeze" and env.status(areq) == "cancelled_by_freeze"   # settled, not left approved
    failed = [r for r in env.store.receipts(areq) if r["type"] == "ACTION_FAILED"][-1]       # same txn as the status move
    assert failed["after_state"]["status"] == "cancelled_by_freeze" and failed["before_state"]["status"] == "approved"
    assert "BUDGET_RELEASED" in [r["type"] for r in env.store.receipts(areq)]
    repair_switch(env, how)
    again = env.gw.execute(areq)
    assert again.outcome == "refused" and again.status == "cancelled_by_freeze"
    assert _sends(env, areq) == 0 and env.status(areq) == "cancelled_by_freeze"             # the stale approval did NOT fire
    fresh = env.ar("email")                                                                   # Michael re-approves
    assert env.gw.propose(fresh, fresh["proposed_by"]).outcome == "pending_approval"
    env.gw.record_approval(env.approval(fresh))
    assert env.gw.execute(fresh["action_request_id"]).outcome == "executed"


def test_status_move_and_receipt_commit_together(env):
    """Lane D's deferred trigger makes 'status changed without a receipt' impossible; so the settle is atomic."""
    ar = env.approved("email")
    with pytest.raises(Exception, match="receipt"):
        with env.store.tx("gateway") as cur:
            cur.execute("UPDATE mbos.action_requests SET status='cancelled_by_freeze' WHERE action_request_id=%s",
                        (ar["action_request_id"],))
    assert env.status(ar["action_request_id"]) == "approved"


def test_unreadable_policy_is_not_a_freeze_and_keeps_the_approval(env):
    ar = env.approved("email")
    env.policy_path.write_text("{")
    assert env.gw.execute(ar["action_request_id"]).status == "approved"


def test_freeze_denial_through_spine_adapter_is_frozen_and_settled(env):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent / "vendor/agent01_mbos"))
    from mbos_governance.spine_adapter import SpineGateway
    ar = env.approved("email")
    appr = env.sql("SELECT approval_id FROM mbos.approvals WHERE action_request_id=%s", (ar["action_request_id"],))[0][0]
    env.sql("DELETE FROM mbos.panic_state", replica=True)
    r = SpineGateway(env.gw).execute(None, ar["action_request_id"], appr)
    assert not r.ok and r.frozen and env.status(ar["action_request_id"]) == "cancelled_by_freeze"


# ---------------------------------------------------------------- F-22
@pytest.mark.parametrize("cap,agent", [("publish.listing.create", "agent-01-coordinator"),
                                       ("publish.content.post", "agent-01-coordinator"),
                                       ("publish.listing.create", "agent-07-marketing"),
                                       ("publish.content.post", "agent-07-marketing")])
def test_publish_is_propose_only_tier0_publishing(env, cap, agent):
    ar = ar_for(env, cap, "publishing", agent, tier=1)
    d = decide(ar, PolicyStore(env.policy_path).current())
    assert (d.decision, d.tier, d.step_up) == ("require_approval", 0, False)


@pytest.mark.parametrize("cap,cat,agent", [
    ("publish.listing.create", "publishing", "agent-06-communications"),    # not a drafting agent
    ("publish.listing.create", "publishing", "agent-02-opportunity"),
    ("publish.video.upload", "publishing", "agent-07-marketing"),            # unknown capability
    ("publish.listing.create", "offer", "agent-07-marketing"),               # category mismatch
])
def test_publish_default_deny(env, cap, cat, agent):
    assert decide(ar_for(env, cap, cat, agent), PolicyStore(env.policy_path).current()).decision == "deny"


@pytest.mark.parametrize("payload", [{"offer": 900}, {"counter_offer": 700}, {"binding": True}, {"listing": {"offer_usd": 5}}])
def test_binding_offers_never_through_publish(env, payload):
    d = decide(ar_for(env, "publish.listing.create", "publishing", "agent-07-marketing", payload={"title": "x", **payload}),
               PolicyStore(env.policy_path).current())
    assert d.decision == "deny" and "BINDING_UNDER_PUBLISH" in d.reasons[-1]
    assert decide(ar_for(env, "offer.email.send", "offer", "agent-06-communications", payload={"to_ref": "r", **payload}),
                  PolicyStore(env.policy_path).current()).decision == "require_approval"


def test_publish_namespace_cannot_map_to_a_binding_category(env):
    from mbos_governance import PolicyUnavailable
    env.policy_edit(lambda d: d["capabilities"].__setitem__("publish.offer.create", {"category": "offer", "effector": "dryrun"}))
    with pytest.raises(PolicyUnavailable, match="publish.* may only map to publishing"):
        PolicyStore(env.policy_path).current()


def test_publish_full_dry_run_flow_for_the_spines_proposer(env):
    """F-22: the spine proposes as agent-01 — the flip/publishing path now runs end to end (dry-run)."""
    ar = ar_for(env, "publish.listing.create", "publishing", "agent-01-coordinator")
    assert env.gw.propose(ar, "agent-01-coordinator").outcome == "pending_approval"
    assert env.gw.record_approval(env.approval(ar)).status == "approved"
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "executed" and res.effector_response["dry_run"] is True
    assert env.store.receipts(ar["action_request_id"])[-1]["effect"] == "publish"
