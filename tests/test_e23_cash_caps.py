"""E-23: cash caps never exceed the owner-set protected principal (operator profile mission)."""
from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from tests.test_e12_recommendation_actions import ar_for

ROOT = Path(__file__).resolve().parent.parent
PRINCIPAL = json.loads((Path(__file__).parent / "data/operator_profile.v1.json").read_text())["mission"]["protected_principal_usd"]
POLICY = json.loads((ROOT / "policy/policy.v1.json").read_text())
SCHEMA = json.loads((ROOT / "policy/policy.schema.json").read_text())


def test_policy_validates_against_schema():
    jsonschema.Draft202012Validator(SCHEMA).validate(POLICY)


def test_caps_never_exceed_protected_principal():
    assert PRINCIPAL == 500
    car = POLICY["recommendation_actions"]["cash_at_risk"]
    dry = POLICY["budgets"]["dry_run"]
    money = dry["buckets"]["money"]
    caps = [car["max_per_flip_usd"], car["max_total_active_usd"], money["per_action_hard_cap"], money["daily_hard_cap"]]
    assert all(c <= PRINCIPAL for c in caps), caps
    assert dry["global_daily_hard_cap"] <= 600
    assert "1,500" not in json.dumps(POLICY) and "2x" not in car["basis"]


def test_600_offer_denied_450_passes_to_approval(env):
    big = ar_for(env, "offer.submit", "offer", "agent-01-coordinator", estimated_cost={"amount": 600, "currency": "USD"})
    assert env.gw.propose(big, "agent-01-coordinator").outcome == "pending_approval"
    res = env.gw.record_approval(env.approval(big))
    assert res.reasons and any(r.startswith(("BUDGET_PER_ACTION_CAP", "CASH_AT_RISK")) for r in res.reasons)
    ok = ar_for(env, "offer.submit", "offer", "agent-01-coordinator", estimated_cost={"amount": 450, "currency": "USD"})
    assert env.gw.propose(ok, "agent-01-coordinator").outcome == "pending_approval"
    assert env.gw.record_approval(env.approval(ok)).reasons == []
