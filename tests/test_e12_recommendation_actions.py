"""E-12: policy for the Deal Sniffer recommendation actions (CONTACT / OFFER / COUNTER / BUY) + R20."""
from __future__ import annotations

import copy

import pytest

from mbos_governance import PolicyStore, PolicyUnavailable, decide
from mbos_governance.gateway import GatewayRefused
from mbos_governance.ids import new_id, payload_hash
from mbos_governance.policy import step_up_required


def ar_for(env, capability, category, agent, **over):
    payload = over.pop("payload", {"to_ref": "relay:EXAMPLE-0001", "template_id": "t", "n": new_id("x")})
    ar = env.ar("email", payload=payload, **{k: v for k, v in over.items() if k != "estimated_cost"})
    ar.update(capability=capability, category=category, proposed_by=agent, payload_hash=payload_hash(payload))
    if "estimated_cost" in over:
        ar["estimated_cost"] = over["estimated_cost"]
    elif category in ("offer", "purchase"):
        ar["estimated_cost"] = {"amount": 400, "currency": "USD"}
    return ar


# (card action, capability, category, proposer, needs_step_up)
CARD = [
    ("CONTACT", "comms.email.send", "email", "agent-06-communications", False),
    ("CONTACT", "comms.sms.send", "sms", "agent-06-communications", False),
    ("OFFER", "offer.email.send", "offer", "agent-06-communications", True),
    ("OFFER", "offer.sms.send", "offer", "agent-06-communications", True),
    ("OFFER", "offer.message.send", "offer", "agent-06-communications", True),
    ("OFFER", "offer.submit", "offer", "agent-01-coordinator", True),
    ("COUNTER", "offer.email.counter", "offer", "agent-06-communications", True),
    ("COUNTER", "offer.sms.counter", "offer", "agent-06-communications", True),
    ("COUNTER", "offer.message.counter", "offer", "agent-01-coordinator", True),
    ("BUY", "purchase.create", "purchase", "agent-01-coordinator", True),
]


@pytest.mark.parametrize("action,cap,cat,agent,step_up", CARD, ids=[f"{c[0]}:{c[1]}" for c in CARD])
def test_card_actions_are_tier0_approval_with_step_up(env, action, cap, cat, agent, step_up):
    pol = PolicyStore(env.policy_path).current()
    d = decide(ar_for(env, cap, cat, agent, tier=1), pol)       # a requested tier 1 is forced to 0
    assert (d.decision, d.tier, d.step_up) == ("require_approval", 0, step_up), d
    assert step_up_required(ar_for(env, cap, cat, agent), pol) is step_up


@pytest.mark.parametrize("cap,cat,agent", [
    ("offer.carrier_pigeon.send", "offer", "agent-06-communications"),      # unknown capability
    ("purchase.wire", "purchase", "agent-01-coordinator"),
    ("offer.email.send", "offer", "agent-07-marketing"),                    # not granted
    ("purchase.create", "purchase", "agent-06-communications"),             # comms cannot BUY
    ("offer.email.counter", "email", "agent-06-communications"),            # category mismatch
])
def test_default_deny(env, cap, cat, agent):
    d = decide(ar_for(env, cap, cat, agent), PolicyStore(env.policy_path).current())
    assert d.decision == "deny" and d.tier == 0


@pytest.mark.parametrize("payload", [{"offer": 850}, {"counter_offer": 700}, {"nested": {"Offer_Amount": 1}}, {"binding": True}, {"x": [{"counter_offer": 1}]}])
def test_binding_offer_never_creatable_under_comms(env, payload):
    pol = PolicyStore(env.policy_path).current()
    for cap, cat in (("comms.email.send", "email"), ("comms.sms.send", "sms"), ("comms.message.send", "message")):
        d = decide(ar_for(env, cap, cat, "agent-06-communications", payload={"to_ref": "r", **payload}), pol)
        assert d.decision == "deny" and "BINDING_UNDER_COMMS" in d.reasons[-1], (cap, d)
    ok = decide(ar_for(env, "offer.email.send", "offer", "agent-06-communications", payload={"to_ref": "r", **payload}), pol)
    assert ok.decision == "require_approval"                    # the same content is fine on the binding capability


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d["capabilities"].__setitem__("comms.offer.send", {"category": "offer", "effector": "dryrun"}), "under comms"),
    (lambda d: d["capabilities"]["offer.sms.send"].__setitem__("category", "sms"), "binding namespace"),
    (lambda d: d["capabilities"]["purchase.create"].__setitem__("category", "money"), "binding namespace"),
    (lambda d: d["approval"]["step_up_required"]["categories"].remove("offer"), "step-up"),
])
def test_policy_cannot_be_edited_to_break_the_namespaces(env, mutate, match):
    env.policy_edit(mutate)
    with pytest.raises(PolicyUnavailable, match=match):
        PolicyStore(env.policy_path).current()


def test_full_flow_offer_counter_buy_dry_run(env):
    for cap, cat, agent in (("offer.email.send", "offer", "agent-06-communications"),
                            ("offer.sms.counter", "offer", "agent-06-communications"),
                            ("purchase.create", "purchase", "agent-01-coordinator")):
        ar = ar_for(env, cap, cat, agent, estimated_cost={"amount": 300, "currency": "USD"})
        assert env.gw.propose(ar, agent).outcome == "pending_approval"
        weak = env.gw.record_approval(env.approval(ar, auth_context={"method": "webauthn", "step_up": False}))
        assert weak.outcome == "refused" and "STEP_UP_REQUIRED" in weak.reasons
        assert env.gw.record_approval(env.approval(ar)).status == "approved"
        assert env.gw.execute(ar["action_request_id"]).outcome == "executed"


def test_proposal_via_gateway_refuses_binding_under_comms(env):
    ar = ar_for(env, "comms.email.send", "email", "agent-06-communications", payload={"to_ref": "r", "offer": 850})
    res = env.gw.propose(ar, "agent-06-communications")
    assert res.outcome == "rejected" and "BINDING_UNDER_COMMS" in " ".join(res.reasons)


# ---------------------------------------------------------------- cash at risk (MICHAEL_DECISIONS #1 defaults)
def test_cash_at_risk_per_flip(env):
    item = env.item()
    a = ar_for(env, "offer.submit", "offer", "agent-01-coordinator", estimated_cost={"amount": 1000, "currency": "USD"})
    b = ar_for(env, "purchase.create", "purchase", "agent-01-coordinator", estimated_cost={"amount": 600, "currency": "USD"})
    a["item_id"] = b["item_id"] = item                        # the SAME flip
    for ar in (a, b):
        assert env.gw.propose(ar, "agent-01-coordinator").outcome == "pending_approval"
    assert env.gw.record_approval(env.approval(a)).reasons == []
    res = env.gw.record_approval(env.approval(b))
    assert res.reasons == [f"CASH_AT_RISK_PER_FLIP:{item}"]   # 1,000 + 600 > 1,500
    assert env.gw.execute(b["action_request_id"]).outcome == "refused"


def test_cash_at_risk_total_across_flips(env):
    env.policy_edit(lambda d: d["recommendation_actions"]["cash_at_risk"].update(max_total_active_usd=1200))
    env.policy_edit(lambda d: d["budgets"]["velocity"].__setitem__("money_bucket_actions_per_hour", 50))
    first = env.approved("purchase", estimated_cost={"amount": 700, "currency": "USD"})
    second = env.propose("offer", estimated_cost={"amount": 600, "currency": "USD"})        # a different flip
    assert env.gw.record_approval(env.approval(second)).reasons == ["CASH_AT_RISK_TOTAL"]
    third = env.propose("offer", estimated_cost={"amount": 500, "currency": "USD"})
    assert env.gw.record_approval(env.approval(third)).reasons == []                          # 700 + 500 = 1,200 fits
    assert first


def test_released_cash_frees_the_limit(env):
    item = env.item()
    a = ar_for(env, "offer.submit", "offer", "agent-01-coordinator", estimated_cost={"amount": 1400, "currency": "USD"})
    a["item_id"] = item
    env.gw.propose(a, "agent-01-coordinator"); env.gw.record_approval(env.approval(a))
    env.gw.engage_panic("L3", None, "michael", "stop")                       # cancels + releases the reservation
    env.gw.release_panic("L3", None, "michael", "go")
    b = ar_for(env, "purchase.create", "purchase", "agent-01-coordinator", estimated_cost={"amount": 1400, "currency": "USD"})
    b["item_id"] = item
    env.gw.propose(b, "agent-01-coordinator")
    assert env.gw.record_approval(env.approval(b)).reasons == []


# ---------------------------------------------------------------- R20
@pytest.mark.parametrize("freeze", [("L2", "comms.*"), ("L1", "agent-06-communications"), ("L2", "category:email")])
def test_r20_freeze_refused_approval_becomes_cancelled_and_stays_dead_after_release(env, freeze):
    ar = env.approved("email")
    areq = ar["action_request_id"]
    env.gw.engage_panic(*freeze, "michael", "incident")
    res = env.gw.execute(areq)
    assert res.outcome == "refused" and res.status == "cancelled_by_freeze" and any(r.startswith("G7:PANIC_") for r in res.reasons)
    assert env.status(areq) == "cancelled_by_freeze"
    failed = [r for r in env.store.receipts(areq) if r["type"] == "ACTION_FAILED"][-1]
    assert failed["after_state"]["status"] == "cancelled_by_freeze" and failed["approval_id"]
    assert "BUDGET_RELEASED" in [r["type"] for r in env.store.receipts(areq)]
    env.gw.release_panic(*freeze, "michael", "all clear")                    # an UNRELATED release
    again = env.gw.execute(areq)
    assert again.outcome == "refused" and again.status == "cancelled_by_freeze"      # the approval is NOT reusable
    assert env.sql("SELECT count(*) FROM mbos.effector_calls WHERE action_request_id=%s", (areq,))[0][0] == 0
    fresh = env.ar("email")                                                   # Michael re-approves a new proposal
    assert env.gw.propose(fresh, fresh["proposed_by"]).outcome == "pending_approval"
    env.gw.record_approval(env.approval(fresh))
    assert env.gw.execute(fresh["action_request_id"]).outcome == "executed"


def test_r20_not_applied_to_pending_or_unrelated_failures(env):
    pending = env.propose("email")
    env.gw.engage_panic("L2", "comms.*", "michael", "incident")
    assert env.gw.execute(pending["action_request_id"]).status == "pending_approval"      # no approval yet: untouched
    env.gw.release_panic("L2", "comms.*", "michael", "ok")
    ar = env.approved("email")
    env.policy_path.write_text("{")                                                       # policy unreadable: NOT a freeze
    assert env.gw.execute(ar["action_request_id"]).status == "approved"


def test_r20_through_spine_adapter_reports_frozen(env):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent / "vendor/agent01_mbos"))
    from mbos_governance.spine_adapter import SpineGateway
    ar = env.approved("email")
    appr = env.sql("SELECT approval_id FROM mbos.approvals WHERE action_request_id=%s", (ar["action_request_id"],))[0][0]
    env.gw.engage_panic("L2", "comms.*", "michael", "incident")
    r = SpineGateway(env.gw).execute(None, ar["action_request_id"], appr)
    assert not r.ok and r.frozen and r.checks["kill_switch_clear"] is False
    assert env.status(ar["action_request_id"]) == "cancelled_by_freeze"
