"""C-33: trailer / donor chassis / machine valuation. Goldens in examples/asset/ (regen: scripts/regen_asset.py)."""

import copy
import json
import unittest
from pathlib import Path

from mbos_economics.asset_deal import evaluate, forecast_bid, load_asset_config

EX = Path(__file__).resolve().parents[1] / "examples" / "asset"


def load(name):
    return json.loads((EX / f"{name}.input.json").read_text())


class TestAssetDeal(unittest.TestCase):
    def test_junk_camper_valued_as_parts_not_camping(self):
        r = evaluate(load("01_junk_camper_donor"))
        self.assertEqual(r["headline_path"], "parts_out")
        self.assertFalse(r["evidence"]["camping_value_used"])
        self.assertEqual(r["evidence"]["sold_comps_used"], 0)           # the 4000 camping comps are ignored
        self.assertEqual(r["paths"]["parts_out"]["net_as_is"]["floor"], 271.8)   # (150+160+40+60+80) - 150*1.1*1.08 - 20 - 20
        self.assertEqual(r["capital_at_risk"], 0)                         # sold/scrap floor covers the spend
        self.assertEqual(r["verdict"], "MAYBE")                           # bill of sale: never YES

    def test_estimate_parts_not_in_floor(self):
        c = load("01_junk_camper_donor")
        c["parts"] = [p for p in c["parts"] if p["basis"] == "estimate"]
        r = evaluate(c)
        self.assertEqual(r["paths"]["parts_out"]["net_as_is"]["floor"], -218.2)
        self.assertEqual(r["capital_at_risk"], 218.2)

    def test_splitter_without_engine_not_auto_pass(self):
        r = evaluate(load("02_splitter_without_engine"))
        self.assertEqual(r["verdict"], "YES")
        self.assertEqual(r["extras"]["repair_cost"], 150)
        self.assertEqual(r["extras"]["repair_hours_michael"], 3)
        self.assertGreater(r["profit_per_day"], 0)
        self.assertEqual(r["bid_forecast"] if "bid_forecast" in r else None, None)

    def test_repair_without_skills_needs_shop_cost(self):
        c = load("02_splitter_without_engine")
        c["repair"]["skills_cover_repair"] = False
        r = evaluate(c)
        self.assertEqual(r["unknowns"], ["repair:shop_cost"])
        c["repair"]["shop_cost"] = 200
        self.assertEqual(evaluate(c)["extras"]["repair_cost"], 350)
        self.assertEqual(evaluate(c)["extras"]["repair_hours_michael"], 0)

    def test_no_title_trailer_as_is_vs_resolved_never_yes(self):
        r = evaluate(load("03_no_title_trailer"))
        self.assertFalse(r["paperwork"]["legal_transfer_assumed"])
        self.assertEqual(r["headline_basis"], "as_is")
        self.assertEqual(r["paths"]["resale"]["value_expected_as_is"], 750)
        self.assertEqual(r["paths"]["resale"]["value_expected_resolved"], 1500)
        self.assertGreater(r["paperwork"]["net_resolved_expected"], r["paperwork"]["net_as_is_expected"])
        self.assertGreater(r["paperwork"]["days_to_cash_resolved"], r["days_to_cash"])
        self.assertEqual(r["verdict"], "MAYBE")

    def test_no_title_without_path_cost_delay_is_unknown(self):
        c = load("03_no_title_trailer")
        c["paperwork"] = {"class": "no_title"}
        r = evaluate(c)
        self.assertEqual(r["verdict"], "HOLD")
        self.assertEqual(r["unknowns"], ["paperwork:title_cost", "paperwork:title_delay_days", "paperwork:title_path"])

    def test_cap_500_case(self):
        r = evaluate(load("04_cap_500"))
        self.assertTrue(r["cash_cap"]["over_cap"])
        self.assertEqual(r["verdict"], "MAYBE")
        self.assertEqual(r["suggested_max_bid"]["binding"], "cash_cap")
        self.assertEqual(r["suggested_max_bid"]["max_bid"], 404.04)       # (500-20)/(1.1*1.08)
        self.assertTrue(r["suggested_max_bid"]["assumptions"])
        c = load("04_cap_500")
        c["hammer_price"] = 404
        self.assertFalse(evaluate(c)["cash_cap"]["over_cap"])
        self.assertEqual(evaluate(c)["verdict"], "YES")

    def test_bid_forecast_labelled_and_deterministic(self):
        r = evaluate(load("04_cap_500"))
        f = r["bid_forecast"]
        self.assertIn("FORECAST", f["label"])
        self.assertEqual(f["final_hammer"]["low"], 450)
        self.assertGreater(f["final_hammer"]["expected"], 450)
        self.assertTrue(f["likely_exceeds_max_bid"])
        k = load_asset_config()["forecast"]
        self.assertEqual(forecast_bid(100, 0, 0, k)["final_hammer"]["expected"], 100)   # nothing left, no uplift
        self.assertGreater(forecast_bid(100, 10, 48, k)["final_hammer"]["expected"], forecast_bid(100, 1, 48, k)["final_hammer"]["expected"])

    def test_owner_override_both_shown_with_provenance_not_yes(self):
        r = evaluate(load("05_owner_override_splitter"))
        self.assertEqual(r["resale"]["system_estimate"], 900)
        self.assertEqual(r["resale"]["owner_target"], 1500)
        self.assertEqual(r["resale"]["used"], "owner")
        self.assertEqual(r["resale"]["owner_provenance"]["source"], "michael 2026-10-09")
        self.assertEqual(r["paths"]["resale"]["value_expected_resolved"], 1500)
        self.assertEqual(r["verdict"], "MAYBE")
        c = load("05_owner_override_splitter")
        c["owner_resale_target"] = {"value": 1500}
        self.assertEqual(evaluate(c)["unknowns"], ["owner_resale_target:value_and_source"])

    def test_asking_comps_never_yield_yes(self):
        r = evaluate(load("06_asking_only"))
        self.assertEqual(r["verdict"], "HOLD")
        self.assertFalse(r["evidence"]["asking_counted_as_sold"])
        c = load("06_asking_only")
        c["comps"] += [{"sold_price": 1500}] * 2
        r = evaluate(c)
        self.assertNotEqual(r["verdict"], "YES")
        self.assertEqual(r["evidence"]["asking_comps_count"], 3)

    def test_goldens_replay_and_existing_untouched(self):
        files = sorted(EX.glob("*.input.json"))
        self.assertGreaterEqual(len(files), 6)
        for f in files:
            want = json.loads(f.with_name(f.name.replace(".input.", ".scored.")).read_text())
            self.assertEqual(json.loads(json.dumps(evaluate(json.loads(f.read_text())))), want, f.name)

    def test_input_not_mutated(self):
        c = load("02_splitter_without_engine")
        before = copy.deepcopy(c)
        evaluate(c)
        self.assertEqual(c, before)


if __name__ == "__main__":
    unittest.main()
