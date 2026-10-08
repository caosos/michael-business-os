"""C-24: per-deal cash/loss caps follow the protected principal ($500), and the ledger's available_to_deploy."""

import json
import unittest
from decimal import Decimal

from helpers import CFG, CFG_BIG, HERE, case, run, sc_of

PROFILE = json.loads((HERE / "contracts" / "operator_profile.v1.json").read_text())


class TestBankrollCaps(unittest.TestCase):
    def test_caps_equal_profile_principal(self):
        principal = Decimal(str(PROFILE["mission"]["protected_principal_usd"]))
        self.assertEqual(CFG.num("capital_and_risk.risk_capital_per_deal_cap"), principal)
        self.assertEqual(CFG.num("capital_and_risk.max_loss_cap"), principal)

    def test_1500_dollar_deal_is_not_yes(self):
        it = case("trailer_utility")            # ties up > $500 cash
        self.assertTrue(sc_of(it, CFG_BIG)["gates"]["cash_ok"])        # fundable under the old $1,500 cap
        sc = sc_of(case("trailer_utility"))
        self.assertEqual(sc["decision"], "PASS")
        self.assertFalse(sc["gates"]["cash_ok"])
        self.assertTrue(any("cash tied up" in r and "cash you can fund" in r for r in sc["reasons"]), sc["reasons"])

    def test_available_to_deploy_lowers_cap_unknown_keeps_it(self):
        base = sc_of(case("trailer_utility"), CFG_BIG)
        self.assertTrue(base["gates"]["cash_ok"])
        it = case("trailer_utility")
        it["economics"].setdefault("context", {})["available_to_deploy"] = 100
        sc = sc_of(it, CFG_BIG)
        self.assertFalse(sc["gates"]["cash_ok"])
        self.assertEqual(sc["decision"], "PASS")
        it["economics"]["context"]["available_to_deploy"] = None
        self.assertTrue(sc_of(it, CFG_BIG)["gates"]["cash_ok"])


if __name__ == "__main__":
    unittest.main()
