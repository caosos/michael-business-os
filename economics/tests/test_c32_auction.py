"""C-32: auction cost model. Goldens in examples/auction/ replay byte-for-byte (regen: scripts/regen_auction.py)."""

import json
import unittest
from pathlib import Path

from mbos_economics.auction import evaluate

EX = Path(__file__).resolve().parents[1] / "examples" / "auction"
SOLD = [{"sold_price": x} for x in (180, 200, 220)]


def case(**kw):
    base = {"item_id": "itm_01JH" + "8" * 22, "hammer_price": 80, "buyer_premium_pct": 0.15, "sales_tax_rate": 0.0925,
            "pickup_cost": 10, "transport_cost": 15, "labor_hours": 2, "days_to_sell": 3, "pickup_wait_hours": 24,
            "resale_fee_pct": 0.1, "comps": SOLD}
    base.update(kw)
    return base


class TestAuction(unittest.TestCase):
    def test_premium_tax_pickup_all_in(self):
        r = evaluate(case())
        # premium 12.00; tax (80+12)*0.0925 = 8.51; fixed 25 -> 125.51
        self.assertEqual(r["cost"], {"hammer": 80, "buyer_premium": 12, "sales_tax": 8.51, "pickup_and_transport": 25, "all_in": 125.51})
        self.assertEqual(r["net"]["expected"], 54.49)           # 200*0.9 - 125.51
        self.assertEqual(r["profit_per_labor_hour"], 27.245)
        self.assertEqual(r["verdict"], "YES")
        self.assertEqual(r["walk_away_hammer"], 91.53)         # (180-40-25)/(1.15*1.0925)

    def test_time_to_cash_fast_flags_and_turnover(self):
        r = evaluate(case(days_to_sell=0, pickup_wait_hours=0, payout_lag_days=0))
        self.assertEqual(r["time_to_cash_hours"], 0)
        self.assertTrue(r["flags"]["fast_24h"] and r["flags"]["fast_48h"])
        r = evaluate(case(days_to_sell=1, pickup_wait_hours=12, payout_lag_days=0))
        self.assertEqual(r["time_to_cash_hours"], 36)
        self.assertEqual((r["flags"]["fast_24h"], r["flags"]["fast_48h"]), (False, True))
        self.assertEqual(r["capital_turns_per_30d"], 20)

    def test_slow_item_flagged_separately_and_not_yes(self):
        r = evaluate(case(days_to_sell=45))
        self.assertTrue(r["flags"]["slow_inventory"])
        self.assertFalse(r["flags"]["fast_48h"])
        self.assertEqual(r["verdict"], "MAYBE")

    def test_asking_only_comps_cannot_yield_yes(self):
        asking = [{"asking_price": x, "kind": "asking"} for x in (300, 320, 340, 360)]
        r = evaluate(case(comps=asking))
        self.assertFalse(r["computable"])
        self.assertEqual(r["verdict"], "HOLD")
        self.assertIn("auction:sold_comps", r["unknowns"])
        self.assertEqual(r["evidence"]["asking_comps_count"], 4)
        self.assertFalse(r["evidence"]["asking_counted_as_sold"])

    def test_asking_does_not_pad_too_few_sold_comps(self):
        r = evaluate(case(comps=SOLD[:2] + [{"asking_price": 250, "kind": "asking"}] * 3))
        self.assertEqual(r["evidence"]["sold_comps_count"], 2)
        self.assertEqual(r["verdict"], "MAYBE")

    def test_asking_labelled_sold_price_is_not_sold(self):
        r = evaluate(case(comps=[{"sold_price": 200, "status": "listed"}] * 5))
        self.assertEqual(r["verdict"], "HOLD")

    def test_missing_input_named_not_invented(self):
        c = case()
        del c["sales_tax_rate"]
        r = evaluate(c)
        self.assertEqual(r["unknowns"], ["auction:sales_tax_rate"])
        self.assertIsNone(r["cost"])

    def test_goldens_replay(self):
        files = sorted(EX.glob("*.input.json"))
        self.assertGreaterEqual(len(files), 4)
        for f in files:
            want = json.loads(f.with_name(f.name.replace(".input.", ".scored.")).read_text())
            self.assertEqual(json.loads(json.dumps(evaluate(json.loads(f.read_text())))), want, f.name)


if __name__ == "__main__":
    unittest.main()
