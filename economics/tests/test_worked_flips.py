"""Worked FLIP examples: trailer, mower, generator, project vehicle (+ C14 resolution).

Every case asserts (1) the engine's ledger equals the independent float reference
to the cent and (2) literal hand-checked values and the verdict. Arithmetic for
the headline numbers is written out in comments and in
docs/research/agent-03-worked-examples.md.
"""

import unittest

from helpers import CFG_BIG, case, reference_flip, run


class FlipCase(unittest.TestCase):
    name = ""

    def setUp(self):
        self.item = case(self.name)
        self.out = run(self.item, CFG_BIG)
        self.sc = self.out["scores"]["scorecard"]
        self.d = self.sc["derived"]

    def assert_matches_reference(self):
        ref = reference_flip(self.item["economics"])
        self.assertAlmostEqual(self.d["cost_out"], ref["cost_out"], places=2)
        self.assertAlmostEqual(self.d["net_profit_deterministic"], ref["net"], places=2)
        self.assertAlmostEqual(self.d["total_hours"], ref["hours"], places=4)
        self.assertAlmostEqual(self.d["profit_per_hour_deterministic"], ref["pph"], places=2)
        self.assertAlmostEqual(self.d["ev_net_profit"], ref["ev"], places=2)
        self.assertAlmostEqual(self.d["ev_profit_per_hour"], ref["ev_pph"], places=2)
        self.assertAlmostEqual(self.d["max_loss"], ref["max_loss"], places=2)


class TestTrailerUtility_C14(FlipCase):
    """Round-one §17.1 inputs. C14: round one called this YES at EV $62/h against a $65 rule.

    Resolution: the RULE stands (EV profit/hour >= w_target is required for YES), the
    TEST changes. At $250 the trailer is MAYBE; the engine names the fix: buy at <= $227.
    """
    name = "trailer_utility"

    def test_ledger(self):
        self.assert_matches_reference()
        # v = 3.20/18 + 0.28 = 0.4578 $/mi
        self.assertEqual(self.d["vehicle_cost_per_mile"], 0.4578)
        # trips: 40 mi -> $18.31, 0.8889 h ; 16 mi -> $7.32, 0.3556 h
        self.assertEqual(self.d["trips_cash"], 25.63)
        self.assertEqual(self.d["travel_hours"], 1.2445)
        # CostOut = 250 + 10 + 160 + 30 + 25.63 + 27 (9 d x $3) = 502.63
        self.assertEqual(self.d["cost_out"], 502.63)
        self.assertEqual(self.d["net_profit_deterministic"], 547.37)
        self.assertEqual(self.d["profit_per_hour_deterministic"], 73.04)   # 547.37 / 7.4945
        self.assertEqual(self.d["cash_tied_up"], 502.63)
        self.assertEqual(self.d["roi_deterministic"], 1.089)

    def test_ev_tree(self):
        # B1 .8075 x 547.37 = 441.9963 ; B2 .1425 x 197.37 = 28.1252
        # B3 fail cost = 250+10+18.31(acq trip only)+0.3x160 = 326.31 ; .05 x -106.31 = -5.3155
        self.assertEqual(self.d["ev_net_profit"], 464.81)
        self.assertEqual(self.d["ev_profit_per_hour"], 62.02)             # 464.81 / 7.4945
        self.assertEqual(self.d["max_loss"], 106.31)
        self.assertEqual(self.d["p_loss"], 0.05)
        self.assertEqual(self.d["expected_revenue"], 958.63)  # .8075x1050 + .1425x700 + .05x220 = 958.625

    def test_verdict_is_maybe_not_yes(self):
        self.assertTrue(all(self.sc["gates"].values()))
        self.assertEqual(self.sc["decision"], "MAYBE")
        self.assertEqual([k for k, v in self.sc["yes_conditions"].items() if not v], ["ev_pph_target_ok"])
        self.assertFalse(self.sc["alert"])                                # alert requires YES
        self.assertIn("YES blocked: EV profit/hour $62.02 < flip target $65.00", self.sc["reasons"])

    def test_walk_away_price(self):
        self.assertEqual(self.sc["walk_away_price"], 227)


class TestTrailerUtilityAtWalkAway(FlipCase):
    name = "trailer_utility_at_walkaway"

    def test_yes_and_alert(self):
        self.assert_matches_reference()
        self.assertEqual(self.d["ev_profit_per_hour"], 65.36)
        self.assertEqual(self.sc["decision"], "YES")
        # strong AND perishable: listed 2 h ago, scarcity .6433, discount (500-225)/500 = .55, EV >= 2x150
        self.assertTrue(self.sc["alert"])
        self.assertEqual(self.d["deal_discount"], 0.55)


class TestMowerNoStart(FlipCase):
    """Round-one §17.2. Round one said 'survives gates (det. PPH $39.8 ~ floor)'. A floor is a
    floor: $39.84 < $40 is a hard PASS. The gate is live at the boundary."""
    name = "mower_no_start"

    def test(self):
        self.assert_matches_reference()
        # CostOut = 150 + 0 + 150 + 0 + 38.46 (84 mi) + 28 = 366.46 ; net 283.54 ; hours 7.1167
        self.assertEqual(self.d["cost_out"], 366.46)
        self.assertEqual(self.d["profit_per_hour_deterministic"], 39.84)
        self.assertEqual(self.d["ev_net_profit"], 133.56)
        self.assertEqual(self.d["max_loss"], 137.05)   # 90 - (150 + 32.05 + 45)
        self.assertEqual(self.sc["decision"], "PASS")
        self.assertEqual([k for k, v in self.sc["gates"].items() if not v], ["pph_floor_ok"])
        self.assertIsNone(self.sc["walk_away_price"])

    def test_evidence_does_not_rescue_a_floor_failure(self):
        better = run(case("mower_compression_confirmed"))["scores"]["scorecard"]
        self.assertEqual(better["derived"]["confidence"], 1)
        self.assertEqual(better["derived"]["ev_net_profit"], 210.88)
        self.assertEqual(better["decision"], "PASS")    # deterministic $/h unchanged at 39.84
        self.assertGreater(better["composite"], self.sc["composite"])


class TestGeneratorFar(FlipCase):
    """Round-one §17.3. 160 mi one-way. AT-16: fails the distance ratio gate even though
    deterministic profit/hour beats the target."""
    name = "generator_far"

    def test(self):
        self.assert_matches_reference()
        self.assertEqual(self.d["profit_per_hour_deterministic"], 66.30)
        self.assertGreater(self.d["profit_per_hour_deterministic"], 65)
        self.assertTrue(self.d["distance_ratio_gate_applies"])
        # burden = 155.66 trips + 7.5556 h x $40 + wasted-trip EV ; limit = .35 x 384.20
        self.assertEqual(self.d["travel_burden_limit"], 134.47)
        self.assertGreater(self.d["travel_burden"], self.d["travel_burden_limit"])
        self.assertEqual(self.d["confidence_distance_penalty"], 0.1)
        self.assertEqual(self.sc["decision"], "PASS")
        self.assertEqual([k for k, v in self.sc["gates"].items() if not v], ["distance_ratio_ok"])


class TestProjectVehicle(FlipCase):
    name = "project_vehicle_civic"

    def test(self):
        self.assert_matches_reference()
        # CostOut = 950 + 95 + 260 + 40 + 22.89 (50 mi) + 21 = 1388.89 (< $1,500 cap)
        self.assertEqual(self.d["cost_out"], 1388.89)
        self.assertEqual(self.d["net_profit_deterministic"], 1211.11)
        self.assertEqual(self.d["profit_per_hour_deterministic"], 119.78)  # / 10.1111 h
        # B1 .72x1211.11 + B2 .18x511.11 + B3 .10x(700-1145.89) = 919.41
        self.assertEqual(self.d["ev_net_profit"], 919.41)
        self.assertEqual(self.d["max_loss"], 445.89)
        self.assertTrue(self.sc["evidence"]["three_sold_comps"])          # 5 comps listed
        self.assertEqual(self.sc["decision"], "YES")
        self.assertFalse(self.sc["alert"])           # listed 20 h ago, 14 competing listings
        self.assertEqual(self.sc["walk_away_price"], 1061)

    def test_cash_cap_gate(self):
        truck = run(case("project_vehicle_truck_over_cap"), CFG_BIG)["scores"]["scorecard"]
        self.assertGreater(truck["derived"]["net_profit_deterministic"], 1800)
        self.assertEqual(truck["derived"]["cash_tied_up"], 2973.89)
        self.assertEqual(truck["decision"], "PASS")
        self.assertEqual([k for k, v in truck["gates"].items() if not v], ["cash_ok"])
        self.assertEqual(truck["walk_away_price"], 926)   # the cap binds: buy <= $926 to fit $1,500


if __name__ == "__main__":
    unittest.main()
