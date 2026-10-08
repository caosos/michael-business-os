"""E-17: campaign autonomy -> governance. A campaign authorises nothing; only ASSISTED_DEAL may DRAFT, through step-up."""
from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

sys.path.insert(0, str(Path(__file__).parent / "vendor/agent01_mbos"))
from mbos_governance import PolicyStore, PolicyUnavailable  # noqa: E402
from mbos_governance import spine_adapter as sa  # noqa: E402
from mbos_governance.campaigns import decide_campaign  # noqa: E402
from mbos_governance.gateway import GatewayRefused  # noqa: E402
from mbos_governance.ids import fmt_ts, new_id  # noqa: E402

from .conftest import NOON, REPO  # noqa: E402
from .test_e12_recommendation_actions import ar_for  # noqa: E402

SCHEMA_SHA = "3239dc9af2c4da0eb77f55e256da91baa335a3e6cd775edba18486fd23f7648d"
EXAMPLE = json.loads((REPO / "tests/data/campaign-trailer-wanted.example.json").read_text())
LIMITS = {"max_total_spend_usd": 600, "max_offer_usd": 450, "expires_at": fmt_ts(NOON + timedelta(days=30))}


def campaign(level="ASSISTED_DEAL", **over):
    c = copy.deepcopy(EXAMPLE)
    c["campaign_id"] = new_id("cmp")
    c["autonomy"] = {"level": level, **({"limits": LIMITS} if level == "BOUNDED_AUTOPILOT" else {})}
    c.update(over)
    return c


def policy(env):
    return PolicyStore(env.policy_path).current()


def test_vendored_campaign_schema_is_pinned_and_the_example_is_valid():
    assert hashlib.sha256((REPO / "src/mbos_governance/schemas/campaign.schema.json").read_bytes()).hexdigest() == SCHEMA_SHA
    from mbos_governance.campaigns import _validator
    assert list(_validator().iter_errors(EXAMPLE)) == []


# ---------------------------------------------------------------- policy decision per level
@pytest.mark.parametrize("level", ["WATCH_ONLY", "RECOMMEND"])
def test_watch_and_recommend_request_no_action(env, level):
    d = decide_campaign(campaign(level), policy(env), now=env.clock())
    assert (d.decision, d.may_request_action, d.tier) == ("no_action", False, None) and d.reasons == ["CAMPAIGN_LEVEL_NO_ACTION"]


def test_assisted_deal_drafts_through_step_up(env):
    d = decide_campaign(campaign("ASSISTED_DEAL"), policy(env), capability="offer.email.send", cost_usd=450, now=env.clock())
    assert (d.decision, d.may_request_action, d.tier, d.step_up) == ("require_approval", True, 0, True)


def test_bounded_autopilot_is_denied_even_with_valid_limits(env):
    c = campaign("BOUNDED_AUTOPILOT")
    assert c["autonomy"]["limits"] == LIMITS                       # valid, complete limits
    d = decide_campaign(c, policy(env), capability="offer.email.send", cost_usd=1, now=env.clock())
    assert d.decision == "deny" and d.reasons == ["AUTOPILOT_NOT_AUTHORIZED"] and not d.may_request_action
    no_limits = campaign("BOUNDED_AUTOPILOT")
    del no_limits["autonomy"]["limits"]
    assert decide_campaign(no_limits, policy(env), now=env.clock()).decision == "deny"       # schema-invalid: still denied


@pytest.mark.parametrize("bad", [None, {}, "ASSISTED_DEAL", {"autonomy": None}, {"autonomy": {"level": "FULL_AUTO"}},
                                 {"autonomy": {"level": "autopilot"}}, {"autonomy": {"level": 3}}, {"autonomy": {}}])
def test_unknown_or_malformed_fails_closed(env, bad):
    d = decide_campaign(bad, policy(env), capability="offer.email.send", now=env.clock())
    assert d.decision == "deny" and not d.may_request_action and d.reasons[0] == "CAMPAIGN_LEVEL_UNKNOWN"


@pytest.mark.parametrize("over,reason", [
    ({"status": "PAUSED"}, "CAMPAIGN_NOT_ACTIVE:PAUSED"), ({"status": "FULFILLED"}, "CAMPAIGN_NOT_ACTIVE:FULFILLED"),
    ({"status": "CANCELLED"}, "CAMPAIGN_NOT_ACTIVE:CANCELLED"),
    ({"stop_conditions": {"expires_at": "2000-01-01T00:00:00Z"}}, "CAMPAIGN_EXPIRED"),
    ({"criteria": {"category": "trailer"}}, "CAMPAIGN_INVALID"),
    ({"extra": 1}, "CAMPAIGN_INVALID"),
])
def test_inactive_expired_or_invalid_campaigns_are_denied(env, over, reason):
    d = decide_campaign(campaign("ASSISTED_DEAL", **over), policy(env), now=env.clock())
    assert d.decision == "deny" and d.reasons[0] == reason


@pytest.mark.parametrize("cap,allowed", [("offer.email.send", True), ("offer.sms.counter", True), ("comms.sms.send", True),
                                         ("purchase.create", False), ("publish.listing.create", False),
                                         ("money.payment.send", False), ("commit.external", False), ("price.change", False)])
def test_assisted_deal_is_draft_only_for_offer_and_contact(env, cap, allowed):
    d = decide_campaign(campaign("ASSISTED_DEAL"), policy(env), capability=cap, now=env.clock())
    assert (d.decision == "require_approval") is allowed
    if not allowed:
        assert d.reasons[0].startswith("CAMPAIGN_CAPABILITY_NOT_ALLOWED")


def test_offer_over_the_campaign_max_is_denied(env):
    c = campaign("ASSISTED_DEAL")                                   # max_price_usd 600
    assert decide_campaign(c, policy(env), capability="offer.email.send", cost_usd=600, now=env.clock()).decision == "require_approval"
    d = decide_campaign(c, policy(env), capability="offer.email.send", cost_usd=600.01, now=env.clock())
    assert d.decision == "deny" and d.reasons[0].startswith("OFFER_EXCEEDS_CAMPAIGN_MAX")


# ---------------------------------------------------------------- the policy data cannot be loosened
@pytest.mark.parametrize("mutate", [
    lambda c: c["levels"]["BOUNDED_AUTOPILOT"].update(decision="require_approval", may_request_action=True, tier=0),
    lambda c: c["levels"]["BOUNDED_AUTOPILOT"].update(reason="OK"),
    lambda c: c["levels"]["ASSISTED_DEAL"].update(step_up=False),
    lambda c: c["levels"]["ASSISTED_DEAL"].update(tier=1),
    lambda c: c["levels"]["ASSISTED_DEAL"].update(allowed_capability_prefixes=["purchase."]),
    lambda c: c["levels"]["RECOMMEND"].update(may_request_action=True),
    lambda c: c.update(unknown_level={"decision": "allow", "reason": "x"}),
    lambda c: c.update(enforce_max_price=False),
    lambda c: c["levels"].update(SUPER_AUTOPILOT={"may_request_action": True}),
    lambda c: c["levels"].pop("WATCH_ONLY"),
])
def test_campaign_policy_cannot_be_loosened_by_editing_data(env, mutate):
    env.policy_edit(lambda d: mutate(d["campaigns"]))
    with pytest.raises(PolicyUnavailable):
        PolicyStore(env.policy_path).current()


def test_missing_campaigns_block_makes_policy_unavailable(env):
    env.policy_edit(lambda d: d.pop("campaigns"))
    with pytest.raises(PolicyUnavailable):
        PolicyStore(env.policy_path).current()


# ---------------------------------------------------------------- through the gateway: no campaign request skips approval
def drafted(env, cap="offer.email.send", agent="agent-06-communications", **kw):
    return ar_for(env, cap, "offer" if cap.startswith("offer.") else "email", agent, **kw)


@pytest.mark.parametrize("level,reason", [("WATCH_ONLY", "CAMPAIGN_LEVEL_NO_ACTION"), ("RECOMMEND", "CAMPAIGN_LEVEL_NO_ACTION"),
                                          ("BOUNDED_AUTOPILOT", "AUTOPILOT_NOT_AUTHORIZED")])
def test_non_assisted_campaigns_cannot_produce_a_pending_or_approved_request(env, level, reason):
    ar = drafted(env, estimated_cost={"amount": 100, "currency": "USD"})
    res = env.gw.propose(ar, ar["proposed_by"], campaign=campaign(level))
    assert res.outcome == "rejected" and reason in res.reasons and env.status(ar["action_request_id"]) == "rejected"
    note = [r for r in env.store.receipts(ar["action_request_id"]) if r["type"] == "POLICY_DECIDED"][0]
    assert note["details"]["campaign"]["level"] == level and reason in note["details"]["campaign"]["reasons"]
    with pytest.raises(GatewayRefused):                                    # no decision can be recorded on it
        env.gw.record_approval(env.approval(ar))
    with pytest.raises(psycopg.Error):                                     # and lane D refuses a direct approval
        with env.store.tx("approver") as cur:
            env.store.record_approval(cur, env.approval(ar), {"type": "human", "id": "michael"}, "forced", new_id("k"))
    assert env.gw.execute(ar["action_request_id"]).outcome == "refused"
    assert env.sql("SELECT count(*) FROM mbos.effector_calls WHERE action_request_id=%s", (ar["action_request_id"],))[0][0] == 0


def test_assisted_deal_request_is_tainted_tier0_and_needs_step_up_and_yes(env):
    ar = drafted(env, estimated_cost={"amount": 450, "currency": "USD"})
    assert env.gw.propose(ar, ar["proposed_by"], campaign=campaign("ASSISTED_DEAL")).outcome == "pending_approval"
    stored = env.store.action_request(ar["action_request_id"])
    assert stored["tier"] == 0 and stored["untrusted_inputs_present"] is True and stored["status"] == "pending_approval"
    note = [r for r in env.store.receipts(ar["action_request_id"]) if r["type"] == "POLICY_DECIDED"][0]
    assert note["details"]["campaign"]["level"] == "ASSISTED_DEAL" and note["details"]["campaign"]["step_up"] is True
    assert env.gw.execute(ar["action_request_id"]).outcome == "refused"                       # no YES => cannot run
    weak = env.gw.record_approval(env.approval(ar, auth_context={"method": "webauthn", "step_up": False}))
    assert weak.outcome == "refused" and "STEP_UP_REQUIRED" in weak.reasons                   # even a reversible-looking offer
    assert env.gw.record_approval(env.approval(ar)).status == "approved"
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "executed" and res.effector_response["dry_run"] is True


def test_assisted_deal_with_the_wrong_capability_or_price_is_rejected(env):
    over = drafted(env, estimated_cost={"amount": 900, "currency": "USD"})
    r1 = env.gw.propose(over, over["proposed_by"], campaign=campaign("ASSISTED_DEAL"))
    assert r1.outcome == "rejected" and any(x.startswith("OFFER_EXCEEDS_CAMPAIGN_MAX") for x in r1.reasons)
    buy = ar_for(env, "purchase.create", "purchase", "agent-01-coordinator", estimated_cost={"amount": 100, "currency": "USD"})
    r2 = env.gw.propose(buy, "agent-01-coordinator", campaign=campaign("ASSISTED_DEAL"))
    assert r2.outcome == "rejected" and any(x.startswith("CAMPAIGN_CAPABILITY_NOT_ALLOWED") for x in r2.reasons)


def test_unknown_level_through_the_gateway_fails_closed(env):
    ar = drafted(env, estimated_cost={"amount": 100, "currency": "USD"})
    res = env.gw.propose(ar, ar["proposed_by"], campaign={"autonomy": {"level": "FULL_AUTO"}})
    assert res.outcome == "rejected" and "CAMPAIGN_LEVEL_UNKNOWN" in res.reasons


def test_the_gateway_role_cannot_approve_and_auto_approval_is_impossible(env):
    """Structural backstop: no campaign path (or any path) reaches `approved` except Michael's YES via the approver role."""
    ar = drafted(env, estimated_cost={"amount": 100, "currency": "USD"})
    env.gw.propose(ar, ar["proposed_by"], campaign=campaign("ASSISTED_DEAL"))
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with env.store.tx("gateway") as cur:
            env.store.set_status(cur, ar["action_request_id"], "approved", "APPROVAL_DECIDED", {"type": "system", "id": "x"},
                                 "self-approve", ar["provenance_ids"], new_id("k"))
    with pytest.raises(psycopg.Error):
        with env.store.tx("gateway") as cur:
            env.store.set_status(cur, ar["action_request_id"], "auto_approved", "POLICY_DECIDED", {"type": "system", "id": "x"},
                                 "auto", ar["provenance_ids"], new_id("k"))
    assert env.status(ar["action_request_id"]) == "pending_approval"


def test_a_request_without_a_campaign_is_unchanged(env):
    ar = drafted(env)
    assert env.gw.propose(ar, ar["proposed_by"]).outcome == "pending_approval"
    assert env.store.action_request(ar["action_request_id"]).get("untrusted_inputs_present") is not True


def test_spine_adapter_campaign_decision_is_plain_json_and_fails_closed(env):
    gov = sa.build(env.dsns, str(env.policy_path), egress_file=None, litellm_file=None, clock=env.clock)
    out = sa.campaign_decision(gov, campaign("BOUNDED_AUTOPILOT"), capability="offer.email.send")
    json.dumps(out)
    assert out["decision"] == "deny" and out["reasons"] == ["AUTOPILOT_NOT_AUTHORIZED"]
    assert sa.campaign_decision(gov, campaign("ASSISTED_DEAL"), capability="offer.email.send", cost_usd=100)["step_up"] is True
    bad = sa.build(env.dsns, str(env.tmp / "missing.json"), egress_file=None, litellm_file=None)
    assert sa.campaign_decision(bad, campaign("ASSISTED_DEAL"))["reasons"] == ["POLICY_UNREADABLE"]
