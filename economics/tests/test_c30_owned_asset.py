"""C-30: five-path owned-asset comparison (BBQ trailer) on incremental cash; sunk basis never decides."""

import copy
import unittest

from test_coverage import P
from mbos_economics.owned_asset import compare_paths, PATHS

AS_OF = "2026-10-08T12:00:00Z"
_n = [100]


def e(field, value, basis="FACT"):
    _n[0] += 1
    return {"finding": f"Michael: {field}", "field": "owned:" + field, "value": value, "basis": basis,
            "provenance_id": P(_n[0]), "entered_by": "michael"}


def bbq(*extra, basis=300):
    return {"item_id": "itm_01JH" + "7" * 22, "schema_version": "1.0.0", "type": "owned_asset", "category": "trailer",
            "research": [e("historical_basis_usd", basis), e("past_tow", "Little Rock to Conway, towed fine", "INFER"), *extra]}


def rng(lo, hi):
    return {"low": lo, "high": hi}


EXAMPLE = [e("sell:resale", rng(500, 800)), e("sell:days", rng(7, 30)), e("sell:hours", 2),
           e("minimal:cash", rng(150, 250)), e("minimal:hours", rng(8, 12)), e("minimal:resale", rng(1800, 2400)),
           e("minimal:days", rng(14, 30)),
           e("themed:cash", rng(600, 900)), e("themed:hours", rng(25, 35)), e("themed:resale", rng(3500, 5000)),
           e("themed:days", rng(30, 60)),
           e("keep:value", 1000), e("keep:cash", 0), e("keep:hours", 0), e("tailgate_months", [9, 10, 11, 12, 1])]


def by(res):
    return {p["path"]: p for p in res["paths"]}


class TestOwnedAsset(unittest.TestCase):
    def test_stated_facts_only_every_path_is_unknown_with_named_inputs(self):
        r = compare_paths(bbq(), AS_OF)
        self.assertEqual([p["path"] for p in r["paths"]], list(PATHS))
        self.assertEqual(r["recommendation"]["path"], "UNKNOWN")
        for p in r["paths"]:
            self.assertFalse(p["computable"])
            self.assertIsNone(p["net_incremental"])
            self.assertTrue(p["unknowns"])
        b = by(r)
        self.assertIn("owned:minimal:cash", b["MINIMAL_REHAB_FLIP"]["unknowns"])
        self.assertIn("owned:themed:resale", b["THEMED_VALUE_ADD_FLIP"]["unknowns"])
        self.assertIn("owned:keep:value", b["KEEP"]["unknowns"])
        self.assertIn("owned:convert:cash", b["CONVERT"]["unknowns"])
        self.assertIn("owned:sell:resale", b["SELL_AS_IS_OR_PART_OUT"]["unknowns"])
        self.assertNotIn("owned:sell:cash", b["SELL_AS_IS_OR_PART_OUT"]["unknowns"])
        self.assertEqual(b["SELL_AS_IS_OR_PART_OUT"]["incremental_cash"], {"low": 0.0, "high": 0.0})

    def test_past_tow_alone_is_inference_not_roadworthy(self):
        rw = compare_paths(bbq(), AS_OF)["roadworthiness"]
        self.assertEqual(rw["confidence"], "INFERENCE")
        self.assertEqual(rw["past_tow_basis"], "INFERENCE")
        self.assertIn("owned:structure", rw["missing_safety_inputs"])
        self.assertEqual(compare_paths({"type": "owned_asset", "research": []}, AS_OF)["roadworthiness"]["confidence"], "UNKNOWN")

    def test_sunk_basis_reported_but_never_changes_a_net(self):
        a, b = compare_paths(bbq(*EXAMPLE, basis=300), AS_OF), compare_paths(bbq(*EXAMPLE, basis=5000), AS_OF)
        self.assertEqual(a["sunk_basis"]["historical_basis_usd"], {"low": 300.0, "high": 300.0})
        for pa, pb in zip(a["paths"], b["paths"]):
            self.assertEqual({k: v for k, v in pa.items()}, {k: v for k, v in pb.items()})
        self.assertEqual(a["recommendation"], b["recommendation"])

    def test_with_example_ranges_all_paths_compute(self):
        r = compare_paths(bbq(*EXAMPLE), AS_OF)
        b = by(r)
        self.assertEqual(b["MINIMAL_REHAB_FLIP"]["net_incremental"], {"low": 1550.0, "high": 2250.0})
        self.assertEqual(b["THEMED_VALUE_ADD_FLIP"]["net_incremental"], {"low": 2600.0, "high": 4400.0})
        self.assertEqual(b["KEEP"]["net_incremental"], {"low": 1000.0, "high": 1000.0})
        self.assertIsNone(b["KEEP"]["finished_resale_range"])
        self.assertIsNone(b["SELL_AS_IS_OR_PART_OUT"]["profit_per_incremental_dollar"])
        self.assertEqual(r["recommendation"]["path"], "THEMED_VALUE_ADD_FLIP")
        self.assertEqual(b["CONVERT"]["computable"], False)
        self.assertEqual(b["MINIMAL_REHAB_FLIP"]["seasonality"]["status"], "IN_SEASON")

    def test_recommendation_changes_with_the_rehab_ranges(self):
        def themed(cash, hours):
            ex = [x for x in EXAMPLE if x["field"] not in ("owned:themed:cash", "owned:themed:hours")]
            return compare_paths(bbq(*ex, e("themed:cash", cash), e("themed:hours", hours)), AS_OF)["recommendation"]["path"]
        self.assertEqual(themed(rng(600, 900), rng(25, 35)), "THEMED_VALUE_ADD_FLIP")
        self.assertEqual(themed(rng(2500, 3500), rng(60, 80)), "MINIMAL_REHAB_FLIP")

    def test_untrusted_entries_are_ignored(self):
        bad = e("minimal:cash", 100)
        bad.pop("entered_by")
        self.assertIn("owned:minimal:cash", by(compare_paths(bbq(bad), AS_OF))["MINIMAL_REHAB_FLIP"]["unknowns"])

    def test_pure_and_deterministic(self):
        it = bbq(*EXAMPLE)
        snap = copy.deepcopy(it)
        self.assertEqual(compare_paths(it, AS_OF), compare_paths(it, AS_OF))
        self.assertEqual(it, snap)


if __name__ == "__main__":
    unittest.main()
