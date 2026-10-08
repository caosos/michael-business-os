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
    p["projected_week"] = {"low": 250, "likely": 400, "high": 500}   # must equal what the remaining legs can produce (F-64)
    p["remaining_gap"] = 1100
    p["replace_if_stale"] = []
    assert mission.plan_errors(p) == []


def test_validate_raises_contract_violation():
    with pytest.raises(ContractViolation):
        mission.validate_ledger({"protected_principal": 1})


def test_loss_beyond_earned_is_an_impairment_not_a_rewrite():
    l = {"protected_principal": 500, "earned_working_capital": 0, "capital_deployed": 0, "realized_profit": -60,
         "principal_impairment": 60, "available_to_deploy": 440}
    assert mission.ledger_errors(l) == []
    l["earned_working_capital"] = 20
    l["available_to_deploy"] = 460
    assert any("earned capital first" in e for e in mission.ledger_errors(l))


def test_f63_nan_and_infinity_rejected():
    for bad in (float("nan"), float("inf"), float("-inf")):
        l = load("capital-ledger.example.json"); l["protected_principal"] = bad
        assert mission.ledger_errors(l)
        p = load("mission-plan.example.json"); p["legs"][0]["cash_at_risk"] = bad
        assert mission.plan_errors(p)


def test_f64_projection_must_be_supported_by_legs_and_recommendation_rules():
    p = load("mission-plan.example.json"); p["projected_week"] = {"low": 9000, "likely": 9500, "high": 9900}; p["remaining_gap"] = -8000
    assert any("not supported by the legs" in e for e in mission.plan_errors(p))
    p = load("mission-plan.example.json"); p["projected_week"] = {"low": None, "likely": None, "high": None}; p["remaining_gap"] = 0
    assert any("remaining_gap must be null" in e for e in mission.plan_errors(p))
    p = load("mission-plan.example.json"); p["legs"] = []; p["projected_week"] = {"low": None, "likely": None, "high": None}; p["remaining_gap"] = None
    assert any("DEPLOY but there are no legs" in e for e in mission.plan_errors(p))
    for rec in ("HOLD", "UNKNOWN"):
        p = load("mission-plan.example.json"); p["recommendation"] = rec
        assert any("only DEPLOY may commit cash" in e for e in mission.plan_errors(p))


@pytest.mark.parametrize("mut,frag", [
    (lambda p: p["mission"].update(hours_available=2), "h but only"),
    (lambda p: p["mission"]["period"].update(start="2026-10-11", end="2026-10-05"), "inverted"),
    (lambda p: p["legs"][1].update(scorecard_id=p["legs"][0]["scorecard_id"]), "scorecard"),
    (lambda p: p["ledger"].update(as_of="2020-01-01T00:00:00Z"), "stale"),
    (lambda p: p["ledger"].update(principal_impairment=100, available_to_deploy=370), "impaired"),
])
def test_a35_plan_coherence(mut, frag):
    p = load("mission-plan.example.json")
    mut(p)
    assert any(frag in e for e in mission.plan_errors(p)), mission.plan_errors(p)


def test_zero_projection_with_no_legs_is_honest_but_a_positive_one_is_not():
    p = load("mission-plan.example.json")
    p["recommendation"] = "DO_NOT_SPEND"; p["legs"] = []; p["replace_if_stale"] = []
    p["projected_week"] = {"low": 0.0, "likely": 0.0, "high": 0.0}; p["remaining_gap"] = 1500
    assert mission.plan_errors(p) == []
    p["projected_week"] = {"low": 0.0, "likely": 5.0, "high": 9.0}; p["remaining_gap"] = 1495
    assert any("not supported" in e for e in mission.plan_errors(p))


def test_f94_deploy_needs_a_yes_leg_and_undecided_legs_say_what_they_wait_on():
    p = load("mission-plan.example.json")
    for l in p["legs"]:
        l["title"] = "A named job"
        l["verdict"] = "MAYBE"
        l["waiting_on"] = ["customer_screened"]
    assert any("no leg has a YES" in e for e in mission.plan_errors(p))
    p["recommendation"] = "HOLD"
    p["legs"] = [dict(l, cash_at_risk=0) for l in p["legs"]]
    assert mission.plan_errors(p) == []
    p["legs"][0].pop("waiting_on")
    assert any("needs a non-empty waiting_on" in e for e in mission.plan_errors(p))
    q = load("mission-plan.example.json")
    q["legs"][0].update(title="Replace sticking doorbell", verdict="YES")
    assert mission.plan_errors(q) == []
