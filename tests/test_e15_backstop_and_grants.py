"""E-15: F-40 backstop (non-freeze refusals settle `failed`, never stay approved) + F-41 least-privilege grants."""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).parent / "vendor/agent01_mbos"))
from mbos_governance import PolicyStore, decide  # noqa: E402
from mbos_governance import spine_adapter as sa  # noqa: E402

from .conftest import REPO  # noqa: E402
from .test_e12_recommendation_actions import ar_for  # noqa: E402


def record_yes_directly(env, ar, **over):
    """What a spine that records decisions itself (lane D record_approval) can do: store a YES the gateway would
    have refused (F-40: no step-up)."""
    appr = env.approval(ar, **over)
    with env.store.tx("approver") as cur:
        env.store.record_approval(cur, appr, {"type": "human", "id": "michael"}, "Michael decided YES", f"{appr['approval_id']}:DECIDED")
    return appr


# ---------------------------------------------------------------- F-40 backstop
def test_yes_without_step_up_recorded_by_the_spine_settles_failed(env):
    """07's F-40 case: a publishing/offer YES lacking step-up is accepted upstream, then refused at the gateway."""
    ar = ar_for(env, "offer.email.send", "offer", "agent-06-communications")
    assert env.gw.propose(ar, "agent-06-communications").outcome == "pending_approval"
    record_yes_directly(env, ar, auth_context={"method": "webauthn", "step_up": False})
    assert env.status(ar["action_request_id"]) == "approved"
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and res.status == "failed" and "G1:STEP_UP_REQUIRED" in res.reasons
    assert env.status(ar["action_request_id"]) == "failed"
    failed = [r for r in env.store.receipts(ar["action_request_id"]) if r["type"] == "ACTION_FAILED"][-1]
    assert failed["before_state"]["status"] == "approved" and failed["after_state"]["status"] == "failed"
    assert failed["approval_id"] and failed["effector_response"]["status"] == "guard_refused"
    assert env.sql("SELECT count(*) FROM mbos.effector_calls WHERE action_request_id=%s", (ar["action_request_id"],))[0][0] == 0
    # it stays dead: a second call cannot revive it, and Michael re-decides on a NEW request
    assert env.gw.execute(ar["action_request_id"]).outcome == "refused" and env.status(ar["action_request_id"]) == "failed"


@pytest.mark.parametrize("over,reason", [
    ({"auth_context": {"step_up": True}}, "G1:AUTH_CONTEXT_REQUIRED"),
    ({"scope": "session"}, "G1:SCOPE_NOT_ALLOWED"),
    ({"channel": "sms_reply"}, "G1:CHANNEL_NOT_ALLOWED"),
    ({"decider": "agent-06-communications"}, "G1:DECIDER_NOT_APPROVER"),
])
def test_other_approval_defects_settle_failed(env, over, reason):
    ar = env.propose("purchase")
    record_yes_directly(env, ar, **over)
    res = env.gw.execute(ar["action_request_id"])
    assert res.status == "failed" and any(reason in r for r in res.reasons)
    assert env.status(ar["action_request_id"]) == "failed"


def test_grant_revoked_after_approval_settles_failed(env):
    ar = env.approved("sms")
    env.policy_edit(lambda d: d["agent_grants"].__setitem__("agent-06-communications", ["comms.email.send"]))
    res = env.gw.execute(ar["action_request_id"])
    assert res.status == "failed" and any("CAPABILITY_NOT_HELD" in r for r in res.reasons)


def test_secret_appearing_after_approval_settles_failed(env):
    ar = env.approved("email")
    env.tamper_payload(ar["action_request_id"], "leak", "AKIA" + "IOSFODNN7EXAMPLE")
    res = env.gw.execute(ar["action_request_id"])
    assert res.status == "failed"          # payload mutation (G3) and secret (G6) are both terminal


def test_transient_refusals_keep_the_approval(env):
    """Quiet hours, budget caps and an unreadable policy are NOT approval defects: Michael's YES must survive."""
    sms = env.approved("sms")
    env.clock.advance(hours=11, minutes=30)                                  # 21:30 America/Chicago
    res = env.gw.execute(sms["action_request_id"])
    assert res.status == "approved" and "G6:QUIET_HOURS" in res.reasons
    env.clock.advance(hours=12)                                              # next morning: it can go
    env.approval(sms)                                                        # (approval TTL 24 h: still valid)
    assert env.gw.execute(sms["action_request_id"]).outcome == "executed"

    a = env.approved("purchase", estimated_cost={"amount": 1000, "currency": "USD"})
    b = env.propose("purchase", estimated_cost={"amount": 600, "currency": "USD"})
    env.gw.record_approval(env.approval(b))                                  # daily cap refuses the reservation
    env.gw.execute(a["action_request_id"])
    res = env.gw.execute(b["action_request_id"])
    assert res.status == "approved" and any("BUDGET_DAILY_CAP" in r for r in res.reasons)

    ok = env.approved("email")
    env.policy_path.write_text("{")
    assert env.gw.execute(ok["action_request_id"]).status == "approved"


def test_freeze_precedence_over_failed(env):
    """A freeze still wins: cancelled_by_freeze (R20), not failed."""
    ar = ar_for(env, "offer.email.send", "offer", "agent-06-communications")
    env.gw.propose(ar, "agent-06-communications")
    record_yes_directly(env, ar, auth_context={"method": "webauthn", "step_up": False})
    env.gw.engage_panic("L2", "offer.*", "michael", "incident")
    assert env.gw.execute(ar["action_request_id"]).status == "cancelled_by_freeze"


def test_failed_via_spine_adapter_reports_not_ok_not_frozen(env):
    ar = ar_for(env, "offer.sms.send", "offer", "agent-06-communications")
    env.gw.propose(ar, "agent-06-communications")
    appr = record_yes_directly(env, ar, auth_context={"method": "webauthn", "step_up": False})
    r = sa.SpineGateway(env.gw).execute(None, ar["action_request_id"], appr["approval_id"])
    assert not r.ok and not r.frozen and r.checks["approval_valid"] is False
    assert env.status(ar["action_request_id"]) == "failed"


# ---------------------------------------------------------------- F-41 least privilege
EXPECTED_GRANTS = {
    "agent-01-coordinator": {"comms.email.send", "comms.sms.send", "offer.submit", "offer.email.send", "offer.sms.send",
                             "offer.message.send", "offer.email.counter", "offer.sms.counter", "offer.message.counter",
                             "purchase.create", "publish.listing.create", "publish.content.post"},
    "agent-06-communications": {"comms.sms.send", "comms.email.send", "comms.voice.call", "comms.message.send",
                                "schedule.appointment.create", "offer.email.send", "offer.sms.send", "offer.message.send",
                                "offer.email.counter", "offer.sms.counter", "offer.message.counter"},
    "agent-07-marketing": {"publish.listing.create", "publish.content.post"},
    "agent-02-opportunity": set(), "agent-03-economics": set(), "agent-04-state": set(), "agent-05-governance": set(),
}
NEVER_GRANTED = {"money.payment.send", "price.change", "commit.external"}


SHIPPED = REPO / "policy" / "policy.v1.json"      # the real policy file, not a test copy


def test_no_unneeded_grant_matrix():
    grants = PolicyStore(SHIPPED).current().data["agent_grants"]
    assert {a: set(c) for a, c in grants.items()} == EXPECTED_GRANTS          # exactly the expected matrix, nothing more
    held = set().union(*grants.values())
    assert not (NEVER_GRANTED & held)                                         # nobody holds the money-moving capabilities
    spine = set(grants["agent-01-coordinator"])
    assert not (spine & {"comms.voice.call", "comms.message.send", "schedule.appointment.create"})


@pytest.mark.parametrize("cap", sorted(NEVER_GRANTED))
@pytest.mark.parametrize("agent", sorted(EXPECTED_GRANTS))
def test_money_moving_capabilities_are_denied_for_everyone(env, cap, agent):
    category = PolicyStore(SHIPPED).current().data["capabilities"][cap]["category"]
    d = decide(ar_for(env, cap, category, agent), PolicyStore(SHIPPED).current())
    assert d.decision == "deny" and "CAPABILITY_NOT_HELD" in d.reasons[-1]


@pytest.mark.parametrize("cap", ["comms.voice.call", "comms.message.send", "schedule.appointment.create"])
def test_spine_identity_cannot_propose_voice_message_scheduling(env, cap):
    pol = PolicyStore(SHIPPED).current()
    category = pol.data["capabilities"][cap]["category"]
    d = decide(ar_for(env, cap, category, "agent-01-coordinator"), pol)
    assert d.decision == "deny"
    d6 = decide(ar_for(env, cap, category, "agent-06-communications"), pol)
    assert d6.decision == "require_approval"                                   # the drafting lane itself may


def test_every_card_action_still_has_a_proposer():
    """Narrowing must not strand the planners: every capability the spine/planners emit has at least one holder."""
    grants = PolicyStore(SHIPPED).current().data["agent_grants"]
    for cap in ("comms.email.send", "comms.sms.send", "offer.submit", "offer.email.send", "offer.sms.counter",
                "purchase.create", "publish.listing.create", "publish.content.post"):
        assert any(cap in g for g in grants.values()), cap


# ---------------------------------------------------------------- per-lane proposer identity
def test_proposer_for_prefers_the_lane(env):
    gov = sa.build(env.dsns, str(SHIPPED), egress_file=None, litellm_file=None)
    assert sa.proposer_for(gov, "offer.email.send", "agent-06-communications") == "agent-06-communications"
    assert sa.proposer_for(gov, "publish.listing.create", "agent-07-marketing") == "agent-07-marketing"
    assert sa.proposer_for(gov, "purchase.create", "agent-03-economics") == "agent-01-coordinator"     # lane lacks it: spine
    assert sa.proposer_for(gov, "purchase.create", None) == "agent-01-coordinator"
    assert sa.proposer_for(gov, "comms.voice.call", None) is None             # spine lacks it: nobody
    assert sa.proposer_for(gov, "comms.voice.call", "agent-06-communications") == "agent-06-communications"
    assert sa.proposer_for(gov, "money.payment.send", "agent-06-communications") is None
    bad = sa.build(env.dsns, str(env.tmp / "missing.json"), egress_file=None, litellm_file=None)
    assert sa.proposer_for(bad, "offer.email.send", "agent-06-communications") is None     # fail closed
