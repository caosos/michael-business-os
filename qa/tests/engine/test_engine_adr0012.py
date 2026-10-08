"""G-10 / ADR-0012 engine half (C-19, C-20): no universal absolute-profit floor, class-aware gates from DATA, Michael's three training
examples behave as specified, cash context is never assumed, malformed numbers are refused. Strict xfails are tied to F-57/F-58."""
from __future__ import annotations

import json
import re
from decimal import Decimal

import pytest

from .conftest import QA, score

PROFILE = json.loads((QA / "ext" / "operator_profile.v1.json").read_text())["deal_classes"]


# ---------------------------------------------------------------- no universal floor in code or config
def test_no_min_profit_constant_survives_in_engine_code_or_live_config(eco):
    src = eco.root / "src" / "mbos_economics"
    rx = re.compile(r"min_profit_(?:flip|service|ok)|ev_min_profit_ok|ev_multiple_of_min_profit|profit_floor")
    hits = []

    def keys(node, path=""):
        if isinstance(node, dict):
            for k, v in node.items():
                if rx.search(k):
                    hits.append(f"{path}/{k}")
                keys(v, f"{path}/{k}")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                keys(v, f"{path}[{i}]")

    for p in src.rglob("*"):
        if p.is_file() and "history" not in p.parts:
            if p.suffix == ".json":
                keys(json.loads(p.read_text()), p.name)  # config KEYS (prose notes may name what was removed)
            elif p.suffix == ".py":
                hits += [f"{p.name}:{n}" for n, l in enumerate(p.read_text().splitlines(), 1) if rx.search(l) and not l.lstrip().startswith("#")]
    assert not hits, hits


def test_the_only_absolute_profit_requirements_are_class_specific_data(eco):
    cfg = json.loads((eco.root / "src" / "mbos_economics" / "config" / "scoring-config.json").read_text())
    for blk, v in cfg.items():
        if blk in ("class_gates", "_comment", "version") or not isinstance(v, dict):
            continue
        for k, vv in v.items():
            assert not re.search(r"min_(?:net_|ev_)?profit", k), f"a universal profit threshold {blk}.{k} = {vv}"
    micro = cfg["class_gates"]["micro_flip"]
    assert micro["min_net_profit"]["value"] == 0 and micro["min_ev_profit"]["value"] == 0, "micro flips must not carry an absolute-profit requirement"


def test_no_numeric_literal_comparison_against_profit_in_the_engine(eco):
    src = (eco.root / "src" / "mbos_economics" / "engine.py").read_text()
    bad = [l.strip() for l in src.splitlines() if re.search(r"profit\w*\s*(?:<|<=|>=)\s*(?:Decimal\()?[\"']?[1-9]\d*", l)]
    assert not bad, bad


def test_engine_class_thresholds_equal_the_operator_profile(eco):
    c = eco.cfg
    assert c.num("deal_classes.micro_flip_max_cash") == PROFILE["micro_flip"]["max_cash_at_risk"]
    assert c.num("deal_classes.micro_flip_max_days") == PROFILE["micro_flip"]["max_days_to_cash"]
    assert c.num("deal_classes.quick_turn_max_days") == PROFILE["quick_turn"]["max_days_to_cash"]
    assert c.num("deal_classes.capital_intensive_min_cash") == PROFILE["capital_intensive_flip"]["min_cash_at_risk"]
    assert c.num("deal_classes.capital_intensive_min_days") == PROFILE["capital_intensive_flip"]["or_min_days_to_cash"]


# ---------------------------------------------------------------- the engine and the card agree on every class boundary
GRID_CASH = ["0.01", "30", "99.99", "100", "100.01", "200", "749.99", "750", "750.01", "5000"]
GRID_DAYS = ["0.04", "1", "2.99", "3", "3.01", "9.99", "10", "10.01", "44.99", "45", "45.01", "120"]


def test_engine_and_card_assign_the_same_class_on_a_boundary_grid(eco, mc, profile):
    bad = []
    for cash in GRID_CASH:
        for days in GRID_DAYS:
            a = eco.engine._deal_class("flip", Decimal(cash), Decimal(days), eco.cfg)
            b = mc._class_of(float(cash), float(days), profile)
            if a != b:
                bad.append((cash, days, a, b))
    assert not bad, bad[:6]


# ---------------------------------------------------------------- Michael's three training examples
def test_the_30_dollar_tv_is_a_micro_flip_and_is_not_passed(eco):
    s = score(eco, "tv_65_inch")
    d = s["derived"]
    assert s["decision"] != "PASS", s["reasons"][:3]
    assert d["deal_class"] == "MICRO_FLIP" and d["net_profit_deterministic"] < 150  # under the old $150 floor, still alive
    assert s["gates"].get("class_profit_ok") is True and "min_profit_ok" not in s["gates"]


def test_the_late_season_mower_is_capital_intensive_and_ranks_low_today(eco):
    s = score(eco, "mower_late_season")
    assert s["derived"]["deal_class"] == "CAPITAL_INTENSIVE_FLIP"
    in_season = score(eco, "mower_late_season", lambda e: e["context"].update(seasonality_factor=1))
    assert s["ranking"]["rank_score"] < in_season["ranking"]["rank_score"] * 0.5, "late season must cut today's rank sharply"
    tight = score(eco, "mower_late_season", lambda e: e["context"].update(current_cash=900))
    loose = score(eco, "mower_late_season", lambda e: e["context"].update(current_cash=50000))
    assert tight["ranking"]["cash_pressure_factor"] < loose["ranking"]["cash_pressure_factor"] <= 1


@pytest.mark.xfail(strict=True, reason="F-58: a late-season mower with tight funds is only a low rank_score; no reason line says 'wrong buy today' (season, cash pressure)")
def test_the_late_season_mower_is_flagged_as_the_wrong_buy_today_in_words(eco):
    s = score(eco, "mower_late_season")
    said = [r for r in s["reasons"] if "rank score" not in r.lower() and re.search(r"(?i)season|cash pressure|funds|wrong buy|tight", r)]
    assert said, s["reasons"]  # the formula text 'x seasonality_factor x cash_pressure_factor' does not count as a flag


def test_the_non_running_recon_lands_in_a_different_class(eco):
    cls = {n: score(eco, n)["derived"]["deal_class"] for n in ("tv_65_inch", "mower_late_season", "recon_250_non_running")}
    assert cls["recon_250_non_running"] not in (cls["tv_65_inch"], cls["mower_late_season"]), cls


def test_a_tiny_absolute_profit_is_not_a_reason_to_reject(eco):
    """Same TV, but resale just above cost: a micro flip is judged on velocity and downside, never on 'under $X'."""
    s = score(eco, "tv_65_inch", lambda e: (e["resale"].update(target_sell_price=45, comp_price_low=44, comp_price_expected=45, comp_price_high=48),
                                           e["downside"].update(salvage_if_unsold=20, salvage_if_repair_fails=10)))
    assert s["derived"]["net_profit_deterministic"] < 30
    assert s["gates"].get("class_profit_ok") is True
    assert not [r for r in s["reasons"] if re.search(r"(?i)min(?:imum)? (?:net )?profit|profit floor|profit (?:is )?(?:below|under) \$?\d+", r) and "/h" not in r and "hour" not in r.lower()], s["reasons"]


def test_a_capital_intensive_flip_must_still_clear_its_own_class_requirement(eco):
    s = score(eco, "mower_late_season", lambda e: (e["resale"].update(target_sell_price=700, comp_price_low=650, comp_price_expected=700, comp_price_high=760),
                                                       e["downside"].update(salvage_if_unsold=400, salvage_if_repair_fails=150)))
    assert s["derived"]["deal_class"] == "CAPITAL_INTENSIVE_FLIP"
    assert s["gates"].get("class_profit_ok") is False or s["decision"] != "YES"


# ---------------------------------------------------------------- cash context is never assumed
def test_without_a_stated_cash_the_engine_applies_no_pressure(eco):
    s = score(eco, "mower_late_season", lambda e: e["context"].pop("current_cash", None))
    assert s["derived"]["current_cash_context"] == {"value": None, "known": False}
    assert s["ranking"]["cash_pressure_factor"] == 1 and s["ranking"]["cash_share_of_current_cash"] is None


@pytest.mark.xfail(strict=True, reason="F-57: the engine takes `current_cash` from the item (any lane can write it) and applies a pressure factor; the card says UNKNOWN because only Michael's profile may state it")
def test_cash_context_has_a_single_michael_stated_source(eco):
    s = score(eco, "mower_late_season")  # the case carries context.current_cash = 1200 with no profile statement
    assert s["derived"]["current_cash_context"]["known"] is False


@pytest.mark.parametrize("name,mut", [
    ("buy-negative", lambda e: e["acquisition"].update(expected_buy_price=-30)), ("buy-nan", lambda e: e["acquisition"].update(expected_buy_price=float("nan"))),
    ("buy-inf", lambda e: e["acquisition"].update(expected_buy_price=float("inf"))), ("buy-string", lambda e: e["acquisition"].update(expected_buy_price="30")),
    ("buy-bool", lambda e: e["acquisition"].update(expected_buy_price=True)), ("hold-negative", lambda e: e["holding"].update(expected_hold_days=-3)),
    ("hold-nan", lambda e: e["holding"].update(expected_hold_days=float("nan"))), ("prob-above-1", lambda e: e["resale"].update(sale_prob=1.5)),
    ("season-negative", lambda e: e["context"].update(seasonality_factor=-1)), ("season-above-1", lambda e: e["context"].update(seasonality_factor=5)),
    ("cash-zero", lambda e: e["context"].update(current_cash=0)), ("cash-negative", lambda e: e["context"].update(current_cash=-5)),
    ("cash-nan", lambda e: e["context"].update(current_cash=float("nan"))), ("cash-string", lambda e: e["context"].update(current_cash="tight"))])
def test_malformed_numbers_are_refused_with_an_input_error_never_scored(eco, name, mut):
    with pytest.raises(eco.InputError):
        score(eco, "mower_late_season", mut)


def test_zero_hold_days_and_zero_cash_context_edge_do_not_divide_by_zero(eco):
    s = score(eco, "tv_65_inch", lambda e: e["holding"].update(expected_hold_days=0))
    assert "NaN" not in json.dumps(s, default=str) and "Infinity" not in json.dumps(s, default=str)
    assert s["derived"]["time_to_cash_days"] > 0


def test_a_score_is_deterministic_and_never_contains_nan(eco):
    a, b = score(eco, "recon_250_non_running"), score(eco, "recon_250_non_running")
    assert eco.engine.canonical_scorecard(a) == eco.engine.canonical_scorecard(b)
    assert not re.search(r"NaN|Infinity", json.dumps(a, default=str))
