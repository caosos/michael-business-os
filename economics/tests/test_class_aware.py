"""C-19 / ADR-0012: no universal absolute-profit floor; class-aware gates; visible ranking."""

import json
import unittest
from decimal import Decimal
from pathlib import Path

from class_cases import CLASS_CASES, fresh
from mbos_economics.config import load_config
from mbos_economics.engine import compute, score_item
from mbos_economics.inputs import InputError, build_engine_input, validate_engine_input
from mbos_economics.replay import replay_item
from worked_cases import SCORED_AT

HERE = Path(__file__).resolve().parent
CFG = load_config()
PROFILE = json.loads((HERE / "contracts" / "operator_profile.v1.json").read_text())["deal_classes"]


def sc(name, mutate=None):
    it = fresh(name)
    if mutate:
        mutate(it["economics"])
    return score_item(it, CFG, SCORED_AT)["scores"]["scorecard"]


class TestNoUniversalFloor(unittest.TestCase):
    def test_no_min_profit_constants_remain(self):
        raw = (HERE.parent / "src" / "mbos_economics" / "config" / "scoring-config.json").read_text()
        body = json.loads(raw)
        self.assertNotIn("min_profit_flip", body["capital_and_risk"])
        self.assertNotIn("min_profit_service", body["capital_and_risk"])
        self.assertNotIn("ev_multiple_of_min_profit", body["alert_thresholds"])
        src = (HERE.parent / "src" / "mbos_economics" / "engine.py").read_text()
        for dead in ("min_profit_ok", "ev_min_profit_ok", "capital_and_risk.min_profit"):
            self.assertNotIn(dead, src)

    def test_gates_have_no_universal_profit_gate(self):
        s = sc("tv_65_inch")
        self.assertNotIn("min_profit_ok", s["gates"])
        self.assertIn("class_profit_ok", s["gates"])

    def test_config_classes_mirror_operator_profile(self):
        """The config copies the owner's class thresholds (hashed for replay); this fails on drift."""
        c = CFG
        self.assertEqual(c.num("deal_classes.micro_flip_max_cash"), PROFILE["micro_flip"]["max_cash_at_risk"])
        self.assertEqual(c.num("deal_classes.micro_flip_max_days"), PROFILE["micro_flip"]["max_days_to_cash"])
        self.assertEqual(c.num("deal_classes.quick_turn_max_days"), PROFILE["quick_turn"]["max_days_to_cash"])
        self.assertEqual(c.num("deal_classes.capital_intensive_min_cash"),
                         PROFILE["capital_intensive_flip"]["min_cash_at_risk"])
        self.assertEqual(c.num("deal_classes.capital_intensive_min_days"),
                         PROFILE["capital_intensive_flip"]["or_min_days_to_cash"])


class TestMichaelsThreeExamples(unittest.TestCase):
    def test_tv_is_a_micro_flip_and_not_passed_for_small_profit(self):
        s = sc("tv_65_inch")
        d = s["derived"]
        self.assertLess(d["net_profit_deterministic"], 150)          # below the old universal floor
        self.assertEqual(d["deal_class"], "MICRO_FLIP")
        self.assertNotEqual(s["decision"], "PASS")
        self.assertTrue(all(s["gates"].values()))
        self.assertGreater(d["cash_multiple"], 2)
        self.assertEqual(d["catastrophic_downside_probability"], 0.2)
        self.assertEqual(d["parts_out_floor"], 15)                   # parts-out floor on a dead panel

    def test_mower_late_season_is_capital_intensive_and_the_wrong_buy_today(self):
        s, tv = sc("mower_late_season"), sc("tv_65_inch")
        d = s["derived"]
        self.assertEqual(d["deal_class"], "CAPITAL_INTENSIVE_FLIP")
        self.assertGreater(d["net_profit_deterministic"], tv["derived"]["net_profit_deterministic"])  # bigger spread
        self.assertLess(s["ranking"]["capital_velocity"], 0.01)
        self.assertEqual(s["ranking"]["cash_share_of_current_cash"], 0.7236)   # funds tight
        self.assertLess(s["ranking"]["cash_pressure_factor"], 1)
        self.assertLess(s["ranking"]["rank_score"], tv["ranking"]["rank_score"])
        self.assertNotEqual(s["decision"], "YES")

    def test_recon_is_a_different_class(self):
        s = sc("recon_250_non_running")
        self.assertEqual(s["derived"]["deal_class"], "STANDARD_FLIP")
        self.assertEqual(s["derived"]["catastrophic_downside_probability"], 0.4)
        self.assertEqual(s["ranking"]["seasonality_factor"], 0.9)
        self.assertEqual(s["derived"]["liquidity"]["expected_dom_days"], 14)

    def test_tv_outranks_mower_with_components_visible(self):
        tv, mo = sc("tv_65_inch")["ranking"], sc("mower_late_season")["ranking"]
        self.assertGreater(tv["rank_score"], mo["rank_score"])
        for r in (tv, mo):
            for k in ("risk_adjusted_profit", "confidence", "capital_velocity", "seasonality_factor_applied",
                      "cash_pressure_factor", "rank_score", "formula"):
                self.assertIn(k, r)

    def test_goldens_replay(self):
        for p in sorted((HERE.parent / "examples" / "class_aware").glob("*.scored.json")):
            doc = json.loads(p.read_text())
            self.assertTrue(replay_item(doc["item"])["match"], p.name)
        self.assertEqual(len(list((HERE.parent / "examples" / "class_aware").glob("*.scored.json"))), 3)


class TestClassGates(unittest.TestCase):
    def test_capital_intensive_requires_absolute_profit_as_data(self):
        low = lambda e: e["resale"].update(target_sell_price=900, comp_price_expected=900, comp_price_low=800,
                                           comp_price_high=1000)
        s = sc("mower_late_season", low)
        self.assertEqual(s["derived"]["deal_class"], "CAPITAL_INTENSIVE_FLIP")
        self.assertEqual(s["derived"]["class_requirements"]["min_net_profit"], 150)
        self.assertFalse(s["gates"]["class_profit_ok"])

    def test_micro_flip_has_no_absolute_floor(self):
        self.assertEqual(sc("tv_65_inch")["derived"]["class_requirements"]["min_net_profit"], 0)

    def test_class_boundaries(self):
        from mbos_economics.engine import _deal_class
        D = Decimal
        for lane, cash, days, want in (("flip", 100, 3, "MICRO_FLIP"), ("flip", 101, 3, "QUICK_TURN"),
                                       ("flip", 100, 4, "QUICK_TURN"), ("flip", 749, 10, "QUICK_TURN"),
                                       ("flip", 749, 11, "STANDARD_FLIP"), ("flip", 750, 1, "CAPITAL_INTENSIVE_FLIP"),
                                       ("flip", 50, 45, "CAPITAL_INTENSIVE_FLIP"), ("service", 5, 1, "SERVICE_JOB")):
            self.assertEqual(_deal_class(lane, D(cash), D(days), CFG), want, (cash, days))


class TestServiceJobClass(unittest.TestCase):
    def test_service_is_service_job_without_a_flip_cash_multiple(self):
        from worked_cases import fresh as wfresh
        s = score_item(wfresh("drywall_basement"), CFG, SCORED_AT)["scores"]["scorecard"]
        d = s["derived"]
        self.assertEqual(d["deal_class"], "SERVICE_JOB")
        self.assertIsNone(d["cash_multiple"])
        self.assertIsNone(d["ev_cash_multiple"])
        self.assertEqual(d["class_requirements"]["min_net_profit"], 0)       # no absolute floor for a service


class TestUnknownContext(unittest.TestCase):
    def test_absent_context_is_unknown_not_assumed(self):
        s = sc("tv_65_inch", lambda e: e.pop("context"))
        r = s["ranking"]
        self.assertIsNone(r["seasonality_factor"])
        self.assertIsNone(r["personal_use_value"])
        self.assertIsNone(r["cash_share_of_current_cash"])
        self.assertEqual(r["cash_pressure_factor"], 1)
        self.assertEqual(s["derived"]["current_cash_context"], {"value": None, "known": False})

    def test_invalid_context_is_refused(self):
        for bad in ({"current_cash": 0}, {"seasonality_factor": 1.5}, {"personal_use_value": "100"}, "x"):
            it = fresh("tv_65_inch")
            it["economics"]["context"] = bad
            with self.assertRaises(InputError):
                validate_engine_input(build_engine_input(it))

    def test_personal_use_value_raises_profit_not_cash(self):
        base = sc("tv_65_inch")["ranking"]["risk_adjusted_profit"]
        more = sc("tv_65_inch", lambda e: e["context"].update(personal_use_value=40))["ranking"]["risk_adjusted_profit"]
        self.assertEqual(round(more - base, 2), 40)

    def test_non_positive_profit_is_not_rescued_by_velocity(self):
        s = sc("tv_65_inch", lambda e: (e["resale"].update(target_sell_price=30, comp_price_expected=30,
                                                           comp_price_low=30, comp_price_high=30),
                                          e["downside"].update(salvage_if_unsold=10, salvage_if_repair_fails=5)))
        self.assertLessEqual(s["ranking"]["risk_adjusted_profit"], 0)
        self.assertLessEqual(s["ranking"]["rank_score"], 0)


class TestAlertRebased(unittest.TestCase):
    def test_alert_uses_cash_multiple_not_a_profit_floor(self):
        s = sc("tv_65_inch")
        self.assertIn("ev_multiple_ok", s["alert_checks"])
        self.assertGreaterEqual(s["derived"]["ev_cash_multiple"], 1.5)
        self.assertTrue(s["alert_checks"]["ev_multiple_ok"])         # tiny dollars, strong multiple: no $ floor


if __name__ == "__main__":
    unittest.main()
