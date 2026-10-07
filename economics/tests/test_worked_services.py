"""Worked SERVICE examples: drywall, smart-home install, equipment repair."""

import unittest

from helpers import case, reference_service, run


class ServiceCase(unittest.TestCase):
    name = ""

    def setUp(self):
        self.item = case(self.name)
        self.sc = run(self.item)["scores"]["scorecard"]
        self.d = self.sc["derived"]

    def assert_matches_reference(self):
        ref = reference_service(self.item["economics"])
        self.assertAlmostEqual(self.d["cost_out"], ref["cost_out"], places=2)
        self.assertAlmostEqual(self.d["net_profit_deterministic"], ref["net"], places=2)
        self.assertAlmostEqual(self.d["total_hours"], ref["hours"], places=4)
        self.assertAlmostEqual(self.d["profit_per_hour_deterministic"], ref["pph"], places=2)
        self.assertAlmostEqual(self.d["ev_net_profit"], ref["ev"], places=2)
        self.assertAlmostEqual(self.d["ev_profit_per_hour"], ref["ev_pph"], places=2)
        self.assertAlmostEqual(self.d["cash_tied_up"], ref["cash"], places=2)


class TestDrywallBasement(ServiceCase):
    """Round-one §17.4 inputs. Awarded job (win_prob 1)."""
    name = "drywall_basement"

    def test(self):
        self.assert_matches_reference()
        # trips 3 x 16 mi ($7.32, .3556 h) + 10 mi ($4.58, .2222 h) = $26.54, 1.2890 h
        self.assertEqual(self.d["trips_cash"], 26.54)
        # CostOut = 320 materials + 26.54 + 15 disposal = 361.54 ; net = 1850 - 361.54
        self.assertEqual(self.d["net_profit_deterministic"], 1488.46)
        self.assertEqual(self.d["profit_per_hour_deterministic"], 88.66)   # / 16.789 h
        # EV = .98 x 1488.46 + .02 x (925 - 361.54) = 1469.96 ; bad-job branch still positive
        self.assertEqual(self.d["ev_net_profit"], 1469.96)
        self.assertEqual(self.d["expected_revenue"], 1831.5)
        self.assertEqual(self.d["max_loss"], 0)
        self.assertEqual(self.d["time_to_cash_days"], 11)                  # 3 lag + 3 job + 5 terms
        self.assertEqual(self.sc["decision"], "YES")
        self.assertEqual(self.sc["min_quote_for_yes"], 1638)


class TestSmartHome(ServiceCase):
    """Round-one §17.5 inputs. Highest $/h; fresh referral lead => YES + ALERT."""
    name = "smart_home_install"

    def test(self):
        self.assert_matches_reference()
        self.assertEqual(self.d["cost_out"], 65.64)                        # 40 + 2 x 12.82
        self.assertEqual(self.d["profit_per_hour_deterministic"], 101.2)   # 834.36 / 8.2444
        self.assertEqual(self.d["ev_net_profit"], 820.86)
        self.assertEqual(self.sc["decision"], "YES")
        self.assertTrue(self.sc["alert"])

    def test_license_gate(self):
        sc = run(case("smart_home_needs_new_circuit"))["scores"]["scorecard"]
        self.assertGreater(sc["composite"], 60)                            # economics look great...
        self.assertEqual(sc["decision"], "PASS")                           # ...but it is licensed work
        self.assertEqual([k for k, v in sc["gates"].items() if not v], ["license_ok"])
        self.assertTrue(any("licensed_electrical" in r for r in sc["reasons"]))


class TestEquipmentRepair(ServiceCase):
    """New case. Competitive on-site hydraulic pump job with card fees and a parts deposit."""
    name = "equipment_repair_zero_turn"

    def test(self):
        self.assert_matches_reference()
        self.assertEqual(self.d["payment_fees"], 31.33)                    # 1070 x .029 + .30
        self.assertEqual(self.d["sunk_cash"], 13.73)                       # estimate trip, spent win or lose
        self.assertEqual(self.d["cost_out"], 452.95)
        self.assertEqual(self.d["net_profit_deterministic"], 585.72)
        self.assertEqual(self.d["deposit"], 428)
        self.assertEqual(self.d["cash_tied_up"], 24.95)                    # 452.95 - 428
        # EV = .72 x 585.72 + .08 x (733.34 - 452.95) + .20 x -13.73 = 441.40
        self.assertEqual(self.d["ev_net_profit"], 441.4)
        self.assertEqual(self.d["ev_hours"], 6.1634)                       # 1.4167 + .8 x 5.9334
        self.assertEqual(self.d["ev_profit_per_hour"], 71.62)
        self.assertEqual(self.d["max_loss"], 13.73)
        self.assertEqual(self.sc["decision"], "MAYBE")
        self.assertEqual([k for k, v in self.sc["yes_conditions"].items() if not v], ["ev_pph_target_ok"])
        self.assertEqual(self.sc["min_quote_for_yes"], 1098)


class TestCoordinatorDrywallPatch(ServiceCase):
    """Agent 01's illustrative drywall lead (C23). Verdict agrees (MAYBE); numbers are now real."""
    name = "drywall_patch_coordinator"

    def test(self):
        self.assert_matches_reference()
        self.assertEqual(self.d["net_profit_deterministic"], 388.04)
        self.assertEqual(self.d["cash_tied_up"], 0)                        # deposit 112.50 > 61.96 out
        self.assertEqual(self.sc["decision"], "MAYBE")


if __name__ == "__main__":
    unittest.main()
