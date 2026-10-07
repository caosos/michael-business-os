"""C-05 / ruling R13: a machine PASS archives only when >= 1 decisive input is evidence-backed.

Acceptance (READY_QUEUE C-05): "Golden test: a priors-only PASS is flagged."
"""

import copy
import json
import unittest

from helpers import HERE, case, run

from mbos_economics.estimate import apply_estimate, estimate_item

EXAMPLES = HERE.parent / "examples"
AS_OF = "2026-10-07T18:00:00Z"


def golden(name: str) -> dict:
    return json.loads((EXAMPLES / f"{name}.scored.json").read_text())["item"]["scores"]["scorecard"]


def P(n: int) -> str:
    return f"prov_01JE{n:022d}"


class TestGoldens(unittest.TestCase):
    def test_priors_only_pass_is_flagged(self):
        sc = golden("mower_no_start")                      # floor-gate PASS, nothing attested
        self.assertEqual(sc["decision"], "PASS")
        self.assertTrue(sc["pass_on_priors"])
        self.assertEqual(sc["pass_basis"]["evidence_backed_inputs"], [])
        self.assertIn("economics.rehab.labor_hours", sc["pass_basis"]["decisive_inputs"])
        self.assertTrue(any(r.startswith("R13: PASS is not evidence-backed") for r in sc["reasons"]))

    def test_evidence_backed_pass_is_not_flagged(self):
        sc = golden("project_vehicle_truck_over_cap")      # cash-cap PASS on an agreed (FACT) buy price
        self.assertEqual(sc["decision"], "PASS")
        self.assertFalse(sc["pass_on_priors"])
        self.assertEqual(sc["pass_basis"]["evidence_backed_inputs"], ["economics.acquisition.expected_buy_price"])
        self.assertTrue(sc["pass_basis"]["gates"]["cash_ok"]["evidence_backed"])

    def test_c06_floor_pass_on_prior_repair_costs_is_flagged(self):
        """C-06 acceptance: revenue IS evidence-backed (FACT sold comps) and the ask IS a FACT, yet the
        floor PASS rests on prior repair costs, so the amended rule flags it."""
        sc = golden("welder_estimated_from_comps")
        self.assertEqual(sc["decision"], "PASS")
        self.assertFalse(sc["gates"]["pph_floor_ok"])
        g = sc["pass_basis"]["gates"]["pph_floor_ok"]
        self.assertEqual((g["revenue_backed"], g["cost_backed"]), (True, False))
        self.assertTrue(sc["pass_on_priors"])

    def test_ask_price_is_not_a_decisive_input(self):
        for p in sorted(EXAMPLES.glob("*.scored.json")):
            sc = json.loads(p.read_text())["item"]["scores"]["scorecard"]
            if sc.get("pass_basis"):
                self.assertNotIn("economics.acquisition.ask_price", sc["pass_basis"]["decisive_inputs"], p.name)

    def test_flag_never_set_on_yes_or_maybe(self):
        for p in sorted(EXAMPLES.glob("*.scored.json")):
            sc = json.loads(p.read_text())["item"]["scores"]["scorecard"]
            if sc["decision"] != "PASS":
                self.assertFalse(sc["pass_on_priors"], p.name)
                self.assertNotIn("pass_basis", sc, p.name)


class TestDecisiveInputsPerGate(unittest.TestCase):
    def test_license_pass_on_prior_skills_is_flagged(self):
        sc = run(case("smart_home_needs_new_circuit"))["scores"]["scorecard"]
        self.assertTrue(sc["pass_on_priors"])
        self.assertEqual(sc["pass_basis"]["decisive_inputs"],
                         ["economics.job.required_skills", "economics.job.requires_license_he_lacks"])

    def test_license_pass_with_attested_scope_archives(self):
        it = case("smart_home_needs_new_circuit")
        it["economics"]["estimates_meta"]["assumptions"] = [
            {"field": "economics.job.required_skills", "value": ["smart_home_install", "licensed_electrical"],
             "basis": "FACT", "note": "customer confirmed a new 240V circuit is needed"}]
        sc = run(it)["scores"]["scorecard"]
        self.assertEqual(sc["decision"], "PASS")
        self.assertFalse(sc["pass_on_priors"])

    def test_non_fact_basis_does_not_count(self):
        it = case("project_vehicle_truck_over_cap")
        for a in it["economics"]["estimates_meta"]["assumptions"]:
            a["basis"] = "REC"
        self.assertTrue(run(it)["scores"]["scorecard"]["pass_on_priors"])

    def test_flip_economic_pass_backed_on_both_sides_archives(self):
        it = case("mower_no_start")                        # floor PASS
        it["economics"]["estimates_meta"]["assumptions"] = [
            {"field": "economics.resale.target_sell_price", "value": 650, "basis": "INFER",
             "evidence_backed": True, "provenance_ids": ["prov_01JE0000000000000000000001"]},
            {"field": "economics.rehab.parts_cost", "value": 150, "basis": "FACT", "note": "parts quoted by dealer"}]
        sc = run(it)["scores"]["scorecard"]
        self.assertEqual(sc["decision"], "PASS")
        self.assertFalse(sc["pass_on_priors"])

    def test_service_rule_unchanged_one_input(self):
        it = case("equipment_repair_zero_turn")
        it["economics"]["job"]["quoted_revenue"] = 300      # now under the floor
        it["economics"]["estimates_meta"]["assumptions"] = [
            {"field": "economics.job.quoted_revenue", "value": 300, "basis": "FACT", "note": "customer's firm budget"}]
        sc = run(it)["scores"]["scorecard"]
        self.assertEqual(sc["decision"], "PASS")
        self.assertFalse(sc["pass_on_priors"])

    def test_distance_gate_decisive_set_includes_distance(self):
        sc = golden("generator_far")
        self.assertIn("normalized.location.road_miles_one_way", sc["pass_basis"]["decisive_inputs"])
        self.assertTrue(sc["pass_on_priors"])


class TestEstimatorMarksEvidence(unittest.TestCase):
    """The comp-median resale target is an INFERENCE, but derived purely from FACT sold comps:
    the estimator marks it evidence_backed with the comps' provenance ids."""

    def test_comp_target_is_evidence_backed(self):
        items = json.loads((HERE / "fixtures" / "agent02" / "items.json").read_text())
        it = copy.deepcopy([i for i in items if i["category"] == "welder"][0])
        comps = [{"kind": "sold", "price": p, "sold_date": f"2026-09-{10 + i:02d}", "source": "manual",
                  "url": f"https://example.invalid/w/{i}", "provenance_id": P(i)} for i, p in enumerate([600, 650, 700])]
        r = estimate_item(it, {"comps": comps}, AS_OF)
        a = [x for x in r["item_patch"]["economics"]["estimates_meta"]["assumptions"]
             if x["field"] == "economics.resale.target_sell_price"][0]
        self.assertEqual((a["basis"], a["evidence_backed"], a["provenance_ids"]), ("INFER", True, [P(0), P(1), P(2)]))
        sc = run(apply_estimate(it, r))["scores"]["scorecard"]
        self.assertEqual(sc["decision"], "PASS")                      # welder under the $40/h floor
        self.assertIn("economics.resale.target_sell_price", sc["pass_basis"]["evidence_backed_inputs"])
        self.assertTrue(sc["pass_on_priors"])                          # C-06: cost side still priors

    def test_asking_only_target_is_not_evidence_backed(self):
        items = json.loads((HERE / "fixtures" / "agent02" / "items.json").read_text())
        it = copy.deepcopy([i for i in items if i["category"] == "welder"][0])
        comps = [{"kind": "asking", "price": p, "provenance_id": P(10 + i)} for i, p in enumerate([600, 650, 700])]
        a = [x for x in estimate_item(it, {"comps": comps}, AS_OF)["item_patch"]["economics"]["estimates_meta"]["assumptions"]
             if x["field"] == "economics.resale.target_sell_price"][0]
        self.assertNotIn("evidence_backed", a)


if __name__ == "__main__":
    unittest.main()
