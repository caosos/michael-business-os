import copy
import json

import pytest

from mbos import mission
from mbos.contracts.schemas import ContractViolation, contracts_dir

EX = contracts_dir() / "examples" / "mission"


def load(name):
    return json.loads((EX / name).read_text())


def test_examples_validate():
    mission.validate_mission(load("mission-unknown-target.example.json"))
    mission.validate_ledger(load("capital-ledger.example.json"))
    mission.validate_plan(load("mission-plan.example.json"))


@pytest.mark.parametrize("mut,frag", [
    (lambda l: l.update(available_to_deploy=500), "available_to_deploy"),
    (lambda l: l.update(protected_principal=-1), "minimum"),
    (lambda l: l.update(capital_deployed=900, available_to_deploy=-400), "minimum"),
    (lambda l: l.pop("realized_profit"), "required"),
    (lambda l: l.update(extra=1), "Additional"),
])
def test_ledger_invariants_reject(mut, frag):
    l = load("capital-ledger.example.json")
    mut(l)
    errs = mission.ledger_errors(l)
    assert errs and any(frag in e for e in errs), errs


def test_earned_capital_adds_to_available():
    l = {"protected_principal": 500, "earned_working_capital": 120, "capital_deployed": 200, "realized_profit": 120, "available_to_deploy": 420}
    assert mission.ledger_errors(l) == []


@pytest.mark.parametrize("mut,frag", [
    (lambda p: p["legs"][0].update(cash_at_risk=9999), "available_to_deploy"),
    (lambda p: p.update(recommendation="DO_NOT_SPEND"), "DO_NOT_SPEND"),
    (lambda p: p["legs"].append(copy.deepcopy(p["legs"][0])), "more than one leg"),
    (lambda p: p["legs"][0]["expected_net"].update(low=99), "low <= likely"),
    (lambda p: p["projected_week"].update(low=900), "projected_week"),
    (lambda p: p.update(remaining_gap=1), "remaining_gap"),
    (lambda p: p["mission"].update(weekly_target_usd=None), "UNKNOWN"),
    (lambda p: p.update(recommendation="BUY_NOW"), "BUY_NOW"),
    (lambda p: p["legs"][0].pop("scorecard_id"), "scorecard_id"),
])
def test_plan_invariants_reject(mut, frag):
    p = load("mission-plan.example.json")
    mut(p)
    errs = mission.plan_errors(p)
    assert errs and any(frag in e for e in errs), errs


def test_unknown_target_keeps_gap_unknown():
    p = load("mission-plan.example.json")
    p["mission"]["weekly_target_usd"] = None
    p["remaining_gap"] = None
    assert mission.plan_errors(p) == []


def test_do_not_spend_is_a_valid_plan():
    p = load("mission-plan.example.json")
    p["recommendation"] = "DO_NOT_SPEND"
    p["legs"] = [l for l in p["legs"] if l["cash_at_risk"] == 0]
    p["replace_if_stale"] = []
    assert mission.plan_errors(p) == []


def test_validate_raises_contract_violation():
    with pytest.raises(ContractViolation):
        mission.validate_ledger({"protected_principal": 1})
