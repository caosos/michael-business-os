"""P-03-13: plan_week over lane-D documents; validates with mbos.mission.plan_errors when available."""
import unittest

from test_mission import ITEMS, ledger, mission, plan_errors, _HAVE
from mbos_economics.mission_feed import plan_from_documents

PERIOD = {"start": "2026-10-05", "end": "2026-10-11"}


class TestFeed(unittest.TestCase):
    def ok(self, plan):
        if _HAVE:
            self.assertEqual(plan_errors(plan), [])

    def test_items_make_valid_plan(self):
        p = plan_from_documents(mission(1500), ledger(1500), ITEMS)
        self.assertTrue(p["legs"])
        self.assertTrue(all(l["scorecard_id"].startswith("scr_") for l in p["legs"]))
        self.ok(p)

    def test_no_items_no_legs(self):
        p = plan_from_documents(mission(1500), ledger(1500), [])
        self.assertEqual((p["recommendation"], p["legs"]), ("DO_NOT_SPEND", []))
        self.ok(p)

    def test_nothing_known_is_unknown(self):
        p = plan_from_documents(None, None, [], period=PERIOD)
        self.assertEqual((p["recommendation"], p["legs"]), ("UNKNOWN", []))
        self.assertIsNone(p["remaining_gap"])
        self.assertIn("scored_items (none live)", p["unknowns"])
        self.ok(p)

    def test_no_ledger_spends_nothing(self):
        p = plan_from_documents(mission(1500), None, ITEMS)
        self.assertEqual(sum(l["cash_at_risk"] for l in p["legs"]), 0)
        self.ok(p)

    def test_dead_items_ignored(self):
        dead = [dict(i, state="CLOSED") for i in ITEMS]
        self.assertEqual(plan_from_documents(mission(1500), ledger(1500), dead)["legs"], [])

    def test_missing_mission_needs_period(self):
        with self.assertRaises(ValueError):
            plan_from_documents(None, None, [])


if __name__ == "__main__":
    unittest.main()
