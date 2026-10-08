import pytest

from mbos.router import TaskProfile, escalate, load_policy, route


def T(**kw):
    base = dict(task_id="X-1", lane="03")
    base.update(kw)
    return TaskProfile(**base)


def test_default_is_sonnet():
    r = route(T(kind="implement"))
    assert (r.model, r.tier, r.rule_id) == ("sonnet", "default", "R-SONNET")


def test_cross_lane_integration_gets_opus():
    assert route(T(kind="integration", cross_lane=True)).model == "opus"


def test_high_risk_review_gets_opus_but_high_risk_implementation_stays_sonnet_with_more_turns():
    assert route(T(kind="review", risk="high")).model == "opus"
    r = route(T(kind="implement", risk="high"))
    assert r.model == "sonnet" and r.max_turns > route(T(kind="implement")).max_turns


def test_fable_only_for_long_horizon_hard_kinds():
    assert route(T(kind="architecture", long_horizon=True)).model == "fable"
    assert route(T(kind="migration", long_horizon=True)).model == "fable"
    assert route(T(kind="implement", long_horizon=True)).model == "sonnet"      # routine work never uses Fable
    assert route(T(kind="architecture", long_horizon=False, cross_lane=True)).model == "opus"


def test_failed_debug_goes_to_opus_and_two_failures_do_not_auto_pick_fable():
    assert route(T(kind="debug", prior_failures=1)).model == "opus"
    r = route(T(kind="implement", prior_failures=2))
    assert r.model == "opus" and r.escalate_to is None


def test_cheap_model_for_low_risk_classification_with_fallback_note():
    assert route(T(kind="classification", risk="low")).model == "haiku"
    r = route(T(kind="classification", risk="low"), available={"sonnet", "opus", "fable"})
    assert r.model == "sonnet" and r.notes
    assert route(T(kind="classification", risk="medium")).model == "sonnet"


def test_escalation_ladder_stops_before_fable_unless_long_horizon():
    r0 = route(T(kind="implement"))
    r1 = escalate(r0, T(kind="implement"))
    assert r1 and r1.model == "opus"
    assert escalate(r1, T(kind="implement")) is None
    r2 = escalate(r1, T(kind="architecture", long_horizon=True))
    assert r2 and r2.model == "fable"
    assert escalate(r2, T(kind="architecture", long_horizon=True)) is None


def test_bad_inputs_rejected():
    with pytest.raises(ValueError):
        route(T(kind="vibes"))
    with pytest.raises(ValueError):
        route(T(risk="spicy"))


def test_policy_is_data_with_a_catch_all_last():
    p = load_policy()
    assert p["rules"][-1]["if"] == {}
    assert all(v in ("sonnet", "opus", "fable", "haiku") for v in p["aliases"].values())
    assert p["efficiency"]["avoid_context_over_tokens"] == 150000
