"""G-10 / ADR-0012 (card half): capital-velocity fields are honest, class thresholds are DATA with exact boundaries, malformed
numbers never produce invented values or a crash, Michael's cash context is never assumed, and no code path rejects or downgrades
a deal because its absolute profit is under any constant. Strict xfails are tied to findings F-51..F-56 (owner 01)."""
from __future__ import annotations

import copy
import json
import pathlib
import re

import pytest

from .conftest import base_item, independent_schema_errors, unknowns_match, world

NEW = ["opportunity_class", "cash_multiple", "capital_velocity", "parts_out_floor", "catastrophic_downside_probability",
       "repair_uncertainty", "liquidity", "skill_fit", "personal_use_value", "current_cash_context"]
NAN, INF = float("nan"), float("inf")


def build(mc, profile, *, cash=30, days=1, net=60, prof=None, econ=None, derived=None, state="RECOMMENDED", item=None):
    it = item or base_item()
    d = it["scores"]["scorecard"]["derived"]
    d.update(cash_tied_up=cash, time_to_cash_days=days, ev_net_profit=net)
    d.update(derived or {})
    for blk, kv in (econ or {}).items():
        it["economics"].setdefault(blk, {}).update(kv)
    i, rs, ar = world(it, state=state)
    return mc.build_card(i, rs, ar, None, profile=prof or profile)


def E(card):
    return card["economics"]


def with_profile(profile, **cc):
    p = copy.deepcopy(profile)
    p["current_cash_context"] = cc
    return p


def with_classes(profile, **kw):
    p = copy.deepcopy(profile)
    for k, v in kw.items():
        if v == "DEL":
            p["deal_classes"].pop(k, None)
        else:
            p["deal_classes"][k] = v
    return p


# ------------------------------------------------------------------ honesty
def test_without_numbers_every_new_field_is_unknown_and_listed(mc, profile):
    it = base_item()
    it["economics"] = {}
    it["scores"] = {}
    i, rs, ar = world(it)
    c = mc.build_card(i, rs, ar, None, profile=profile)
    assert independent_schema_errors(c) == []
    for f in NEW:
        assert E(c)[f]["value"] == "UNKNOWN", f"{f} invented from nothing: {E(c)[f]}"
        assert f"economics.{f}" in c["unknowns"], f"{f} is UNKNOWN but not listed"
    assert unknowns_match(c)


@pytest.mark.xfail(strict=True, reason="F-69: A-35 regression, cash_multiple is UNKNOWN when only days is missing")
def test_each_derived_field_is_unknown_when_only_its_own_input_is_missing(mc, profile):
    c = build(mc, profile, cash=None)
    assert E(c)["cash_multiple"]["value"] == "UNKNOWN" and E(c)["capital_velocity"]["value"] == "UNKNOWN"
    assert E(c)["opportunity_class"]["value"] == "UNKNOWN"
    c = build(mc, profile, days=None)
    assert E(c)["capital_velocity"]["value"] == "UNKNOWN" and E(c)["opportunity_class"]["value"] == "UNKNOWN"
    assert E(c)["cash_multiple"]["value"] != "UNKNOWN"  # needs no days
    c = build(mc, profile, net=None)
    assert E(c)["cash_multiple"]["value"] == "UNKNOWN" and E(c)["capital_velocity"]["value"] == "UNKNOWN"
    c = build(mc, profile, econ={"downside": {"salvage_if_repair_fails": None}})
    assert E(c)["parts_out_floor"]["value"] == "UNKNOWN"


def test_cash_context_is_never_assumed(mc, profile):
    """Whatever else is on the card, the cash situation is UNKNOWN unless Michael's profile states it."""
    for kw in (dict(cash=0, net=1000), dict(cash=10**6, net=-10**5), dict(cash=30, days=1, net=60)):
        c = build(mc, profile, **kw)
        assert E(c)["current_cash_context"]["value"] == "UNKNOWN"
        assert "economics.current_cash_context" in c["unknowns"]
    p = copy.deepcopy(profile)
    p["current_cash_context"] = {"note": "no value key at all"}
    assert E(build(mc, profile, prof=p))["current_cash_context"]["value"] == "UNKNOWN"
    p["current_cash_context"] = None
    assert E(build(mc, profile, prof=p))["current_cash_context"]["value"] == "UNKNOWN"
    p.pop("current_cash_context")
    assert E(build(mc, profile, prof=p))["current_cash_context"]["value"] == "UNKNOWN"


def test_a_stated_cash_context_is_shown_as_michaels_fact(mc, profile):
    c = build(mc, profile, prof=with_profile(profile, value=400))
    assert E(c)["current_cash_context"]["value"] == 400 and E(c)["current_cash_context"]["basis"] == "FACT"
    assert independent_schema_errors(c) == []


def test_derived_fields_are_inference_with_provenance_never_fact(mc, profile):
    c = build(mc, profile)
    for f in ("cash_multiple", "capital_velocity", "parts_out_floor", "catastrophic_downside_probability", "repair_uncertainty", "liquidity"):
        d = E(c)[f]
        assert d["basis"] == "INFERENCE" and d.get("provenance_id"), f"{f}: {d}"
    assert E(c)["opportunity_class"]["basis"] == "RECOMMENDATION"  # provisional thresholds are not a fact


def test_the_arithmetic_is_what_the_note_says(mc, profile):
    c = build(mc, profile, cash=40, days=2, net=60)
    assert E(c)["cash_multiple"]["value"] == 2.5 and E(c)["capital_velocity"]["value"] == 0.75


# ------------------------------------------------------------------ class thresholds are data, boundaries exact
@pytest.mark.parametrize("cash,days,cls", [
    (30, 1, "MICRO_FLIP"), (100, 3, "MICRO_FLIP"), (100.01, 3, "QUICK_TURN"), (100, 3.01, "QUICK_TURN"), (200, 10, "QUICK_TURN"),
    (200, 10.01, "STANDARD_FLIP"), (749.99, 44.99, "STANDARD_FLIP"), (750, 5, "CAPITAL_INTENSIVE_FLIP"),
    (50, 45, "CAPITAL_INTENSIVE_FLIP"), (749.99, 45, "CAPITAL_INTENSIVE_FLIP"), (750, 1, "CAPITAL_INTENSIVE_FLIP")])
def test_class_boundaries_follow_the_profile_data(mc, profile, cash, days, cls):
    assert E(build(mc, profile, cash=cash, days=days))["opportunity_class"]["value"] == cls


def test_class_follows_edited_thresholds_not_constants(mc, profile):
    p = with_classes(profile, micro_flip={"max_cash_at_risk": 10, "max_days_to_cash": 1}, quick_turn={"max_days_to_cash": 2},
                     capital_intensive_flip={"min_cash_at_risk": 50, "or_min_days_to_cash": 4})
    assert E(build(mc, profile, cash=30, days=1, prof=p))["opportunity_class"]["value"] == "QUICK_TURN"  # 30 > 10 cash, 1 <= 2 days
    assert E(build(mc, profile, cash=60, days=1, prof=p))["opportunity_class"]["value"] == "CAPITAL_INTENSIVE_FLIP"
    assert E(build(mc, profile, cash=5, days=4, prof=p))["opportunity_class"]["value"] == "CAPITAL_INTENSIVE_FLIP"
    assert E(build(mc, profile, cash=10, days=1, prof=p))["opportunity_class"]["value"] == "MICRO_FLIP"
    assert E(build(mc, profile, cash=20, days=2, prof=p))["opportunity_class"]["value"] == "QUICK_TURN"
    assert E(build(mc, profile, cash=20, days=3, prof=p))["opportunity_class"]["value"] == "STANDARD_FLIP"


def test_class_does_not_depend_on_profit(mc, profile):
    base = E(build(mc, profile, cash=30, days=1, net=0.01))["opportunity_class"]["value"]
    for net in (5, 29.99, 300, 5000, -50):
        assert E(build(mc, profile, cash=30, days=1, net=net))["opportunity_class"]["value"] == base


def test_a_service_item_is_its_own_class_not_a_flip_class(mc, profile):
    it = base_item()
    it["type"] = "service"
    c = build(mc, profile, item=it)
    assert E(c)["opportunity_class"]["value"] == "SERVICE_JOB"



# ------------------------------------------------------------------ malformed numbers
@pytest.mark.parametrize("name,kw", [("cash-nan", dict(cash=NAN)), pytest.param("days-nan", dict(days=NAN)), pytest.param("net-nan", dict(net=NAN)), ("cash-inf", dict(cash=INF)),
                                     ("cash-string", dict(cash="50")), pytest.param("net-string", dict(net="60")), pytest.param("cash-huge", dict(cash=1e308, net=1e308))])
def test_a_malformed_number_never_crashes_the_card(mc, profile, name, kw):
    c = build(mc, profile, **kw)
    assert independent_schema_errors(c) == [] and mc.validate_card(c) == []
    for f in ("cash_multiple", "capital_velocity", "opportunity_class"):
        assert E(c)[f]["value"] == "UNKNOWN", f"{f} was derived from a malformed number: {E(c)[f]}"


@pytest.mark.parametrize("name,kw", [("cash-zero", dict(cash=0)), ("cash-bool", dict(cash=True)), ("days-zero", dict(days=0)),
                                     ("net-none", dict(net=None)), ("cash-none", dict(cash=None))])
def test_zero_bool_and_none_never_produce_a_multiple_or_velocity(mc, profile, name, kw):
    c = build(mc, profile, **kw)
    assert independent_schema_errors(c) == [] and mc.validate_card(c) == []
    assert E(c)["capital_velocity"]["value"] == "UNKNOWN"
    if "days" not in kw:
        assert E(c)["cash_multiple"]["value"] == "UNKNOWN"


@pytest.mark.parametrize("name,kw", [("cash-negative", dict(cash=-100)), ("days-negative", dict(days=-5)), pytest.param("days-zero", dict(days=0)),
                                     pytest.param("cash-tiny", dict(cash=1e-9)), ("cash-zero", dict(cash=0))])
def test_a_nonsensical_cash_or_time_is_unknown_not_a_class(mc, profile, name, kw):
    e = E(build(mc, profile, **kw))
    assert e["opportunity_class"]["value"] == "UNKNOWN", f"classified from {kw}: {e['opportunity_class']}"
    if "days" not in kw:
        assert e["cash_multiple"]["value"] == "UNKNOWN", f"multiple from {kw}: {e['cash_multiple']}"


@pytest.mark.parametrize("name,v", [("nan", NAN), ("negative", -50), ("bool", True), ("list", []), ("dict", {}), ("inf", INF)])
def test_a_malformed_cash_context_is_unknown_not_a_fact(mc, profile, name, v):
    c = build(mc, profile, prof=with_profile(profile, value=v))
    assert E(c)["current_cash_context"]["value"] == "UNKNOWN", E(c)["current_cash_context"]


@pytest.mark.parametrize("name,p", [
    ("strings", dict(micro_flip={"max_cash_at_risk": "100", "max_days_to_cash": "3"})), ("none", dict(micro_flip=None)),
    ("nan", dict(micro_flip={"max_cash_at_risk": NAN, "max_days_to_cash": 3})), ("negative", dict(micro_flip={"max_cash_at_risk": -1, "max_days_to_cash": -1})),
    ("ci-missing", dict(capital_intensive_flip="DEL")), ("all-missing", dict(micro_flip="DEL", quick_turn="DEL", capital_intensive_flip="DEL"))])
def test_malformed_class_thresholds_give_unknown_never_a_crash_or_a_silent_class(mc, profile, name, p):
    c = build(mc, profile, prof=with_classes(profile, **p))
    assert E(c)["opportunity_class"]["value"] == "UNKNOWN", f"thresholds {name} produced {E(c)['opportunity_class']}"


@pytest.mark.parametrize("name,r", [("prob-1.5", dict(sale_prob=1.5)), ("prob-negative", dict(sale_prob=-0.2)), ("dom-negative", dict(expected_dom_days=-3)),
                                    pytest.param("dom-zero", dict(expected_dom_days=0))])
def test_an_impossible_liquidity_is_unknown(mc, profile, name, r):
    assert E(build(mc, profile, econ={"resale": r}))["liquidity"]["value"] == "UNKNOWN"


@pytest.mark.parametrize("name,econ,field", [
    ("p_ok-1.2", {"rehab": {"repair_success_prob": 1.2}}, "catastrophic_downside_probability"),
    ("p_ok-bool", {"rehab": {"repair_success_prob": True}}, "catastrophic_downside_probability"),
    ("salvage-negative", {"downside": {"salvage_if_repair_fails": -50}}, "parts_out_floor"),
    ("salvage-bool", {"downside": {"salvage_if_repair_fails": True}}, "parts_out_floor")])
def test_impossible_downside_inputs_are_unknown(mc, profile, name, econ, field):
    assert E(build(mc, profile, econ=econ))[field]["value"] == "UNKNOWN"


def test_certain_failure_is_probability_one_not_unknown(mc, profile):
    c = build(mc, profile, econ={"rehab": {"repair_success_prob": 0}})
    assert E(c)["catastrophic_downside_probability"]["value"] == 1 and E(c)["repair_uncertainty"]["value"] == "high"


@pytest.mark.parametrize("name,net,cost,lo,hi", [("reversed", 340, 1760, 2400, 1800), pytest.param("value-outside-range", 5000, 1760, 1800, 2400),
                                                 pytest.param("negative-cost", 340, -500, 1800, 2400)])
def test_the_gross_profit_range_is_ordered_and_contains_the_value(mc, profile, name, net, cost, lo, hi):
    it = base_item()
    it["economics"]["resale"].update(comp_price_low=lo, comp_price_expected=2100, comp_price_high=hi)
    g = E(build(mc, profile, derived={"net_profit_deterministic": net, "cost_out": cost}, item=it))["expected_gross_profit"]
    assert g.get("low") is None or (g["low"] <= g["value"] <= g["high"]), g


def test_a_wellformed_gross_range_is_ordered_and_contains_the_value(mc, profile):
    g = E(build(mc, profile, derived={"net_profit_deterministic": 340, "cost_out": 1760}))["expected_gross_profit"]
    assert (g["low"], g["value"], g["high"]) == (40, 340, 640)


# ------------------------------------------------------------------ no universal profit floor
@pytest.mark.parametrize("net", [-5, 0, 0.5, 5, 29.99, 30, 75, 299.99, 300, 301, 5000])
def test_the_recommendation_does_not_depend_on_absolute_profit(mc, profile, net):
    ref = build(mc, profile, net=500)
    c = build(mc, profile, net=net)
    assert c["recommendation"]["action"] == ref["recommendation"]["action"], f"net {net} changed the recommended action"
    assert c["status"] == ref["status"]


def test_the_rendered_card_never_cites_a_minimum_profit(mc, profile):
    for net in (5, 29, 75, 5000):
        t = mc.render_text(build(mc, profile, net=net))
        assert not re.search(r"(?i)minimum (?:profit|margin)|below (?:the )?(?:minimum|threshold|\$\s?\d+)|too (?:small|low)|not worth|under \$\s?\d+", t), t[:400]


def test_no_universal_profit_floor_constant_in_card_code_or_profile(mc, profile):
    src = pathlib.Path(mc.__file__).read_text()
    assert not re.search(r"min_profit|(?<!universal_)profit_floor|MIN_PROFIT|PROFIT_FLOOR", src)
    flat = json.dumps(profile)
    assert not re.search(r"min_profit|(?<!universal_)profit_floor", flat) and profile["deal_classes"]["no_universal_profit_floor"] is True
    # a floor may only live inside a class-specific data block, never at the top of deal_classes
    top = {k: v for k, v in profile["deal_classes"].items() if k not in ("micro_flip", "quick_turn", "capital_intensive_flip") and not k.startswith("_")}
    assert not [k for k, v in top.items() if isinstance(v, (int, float)) and not isinstance(v, bool)], f"a global number sits in deal_classes: {top}"


def test_the_new_card_fields_are_optional_and_old_cards_still_validate(mc, profile):
    c = build(mc, profile)
    old = copy.deepcopy(c)
    for f in NEW:
        old["economics"].pop(f, None)
    assert independent_schema_errors(old) == [], "the schema additions must be optional (additive)"
