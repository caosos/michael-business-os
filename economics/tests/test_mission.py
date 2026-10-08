"""C-21: Weekly Money Mission planner. Output is checked against Agent 01's validator when available."""

import copy
import json
import os
import unittest
from pathlib import Path

from helpers import CFG, HERE

from mbos_economics.engine import score_item
from mbos_economics.mission import load_planner_config, plan_week
from worked_cases import SCORED_AT, fresh as wfresh

try:
    from mbos.mission import plan_errors
    _HAVE = bool(os.environ.get("MBOS_CONTRACTS_DIR"))
except Exception:   # pragma: no cover
    plan_errors, _HAVE = None, False

EX = HERE.parent / "examples"


def load(name: str) -> dict:
    sub = "class_aware/" if (EX / "class_aware" / f"{name}.scored.json").exists() else ""
    it = json.loads((EX / f"{sub}{name}.scored.json").read_text())["item"]
    it["state"] = "RESEARCHING"
    return it


ITEMS = [load(n) for n in ("tv_65_inch", "mower_late_season", "recon_250_non_running", "drywall_basement",
                           "smart_home_install", "trailer_utility_at_walkaway")]
TV, MOWER, RECON, DRYWALL, SMART, TRAILER = (i["item_id"] for i in ITEMS)


def mission(target, hours=30):
    return {"mission_version": "1.0.0", "period": {"start": "2026-10-05", "end": "2026-10-11"},
            "weekly_target_usd": target, "hours_available": hours}


def ledger(avail):
    return {"protected_principal": avail, "earned_working_capital": 0, "capital_deployed": 0,
            "realized_profit": 0, "available_to_deploy": avail}


def ids(plan):
    return [leg["item_id"] for leg in plan["legs"]]


class TestPlanWeek(unittest.TestCase):
    def check(self, plan):
        spend = sum(leg["cash_at_risk"] for leg in plan["legs"])
        self.assertLessEqual(spend, plan["ledger"]["available_to_deploy"] + 0.005)
        if plan["recommendation"] == "DO_NOT_SPEND":
            self.assertEqual(spend, 0)
        for leg in plan["legs"]:
            self.assertRegex(leg["scorecard_id"], r"^scr_")                  # every leg cites its scorecard
            self.assertIn("rank ", leg["why"])                               # components per leg
        if _HAVE:
            self.assertEqual(plan_errors(plan), [])

    def test_500_dollar_week_is_closed_by_the_service_alone(self):
        p = plan_week(mission(500), ledger(500), ITEMS)
        self.check(p)
        self.assertEqual(ids(p), [SMART])
        self.assertNotIn(MOWER, ids(p))                                      # PASS: wrong buy today
        self.assertLess(p["remaining_gap"], 0)                               # target exceeded
        self.assertEqual(p["confidence"], "high")
        self.assertIn("Services only", p["explanation"])

    def test_1500_dollar_week_adds_the_micro_flip_but_says_it_does_not_close_the_gap(self):
        p = plan_week(mission(1500), ledger(500), ITEMS)
        self.check(p)
        self.assertEqual(ids(p), [SMART, TV])
        self.assertGreater(p["remaining_gap"], 0)
        self.assertIn("does not close the gap", p["explanation"])
        self.assertEqual(p["confidence"], "low")                             # the TV is MAYBE
        self.assertEqual(p["replace_if_stale"], [TV])
        tv = next(l for l in p["legs"] if l["item_id"] == TV)
        self.assertEqual(tv["opportunity_class"], "MICRO_FLIP")

    def test_cash_tight_week_chooses_service_plus_tv(self):
        p = plan_week(mission(1500), ledger(100), ITEMS)
        self.check(p)
        self.assertEqual(sorted(ids(p)), sorted([SMART, TV]))
        p = plan_week(mission(1500), ledger(40), ITEMS)       # only the TV fits
        self.check(p)
        self.assertEqual(ids(p), [TV])

    def test_capital_intensive_flip_cash_returning_after_the_week_is_locked_not_income(self):
        p = plan_week(mission(2500), ledger(1000), ITEMS)
        self.check(p)
        self.assertNotIn(TRAILER, ids(p))      # its cash returns in 10 d: no help inside a 7-day period

    def test_do_not_spend_when_services_alone_are_better(self):
        it = wfresh("smart_home_install")
        it["economics"]["job"]["materials_cost"] = 0
        it["economics"]["logistics"]["trips"] = []             # remote work: no fuel, no materials
        it["economics"]["job"]["buy_fees"] = 0
        o = score_item(it, CFG, SCORED_AT)
        it["scores"], it["recommendation"], it["state"] = o["scores"], o["recommendation"], "RECOMMENDED"
        self.assertEqual(it["scores"]["scorecard"]["derived"]["cash_at_risk"], 0)
        p = plan_week(mission(500), ledger(500), [it, load("tv_65_inch")])
        self.check(p)
        self.assertEqual(p["recommendation"], "DO_NOT_SPEND")
        self.assertEqual(ids(p), [it["item_id"]])
        self.assertIn("no capital at risk", p["legs"][0]["why"])

    def test_null_target_gives_null_gap_and_unknown(self):
        p = plan_week(mission(None), ledger(500), ITEMS)
        self.check(p)
        self.assertEqual(p["recommendation"], "DEPLOY")   # cash legs: only DEPLOY may commit cash (plan_errors)
        self.assertIsNone(p["remaining_gap"])
        self.assertEqual(p["confidence"], "UNKNOWN")
        self.assertIn("weekly_target_usd", p["unknowns"])

    def test_null_hours_is_unconstrained_and_said_so(self):
        p = plan_week(mission(1500, None), ledger(500), ITEMS)
        self.check(p)
        self.assertTrue(any("hours_available" in u for u in p["unknowns"]))

    def test_hours_constraint_binds(self):
        p = plan_week(mission(1500, 1), ledger(500), ITEMS)
        self.check(p)
        self.assertEqual(ids(p), [TV])                                       # 0.68 h; the service needs 8 h

    def test_nothing_viable_is_hold(self):
        p = plan_week(mission(500), ledger(500), [load("mower_late_season"), load("recon_250_non_running")])
        self.check(p)
        self.assertEqual((p["recommendation"], p["legs"]), ("HOLD", []))

    def test_pass_scorecards_are_never_legs(self):
        p = plan_week(mission(500), ledger(5000), ITEMS)
        self.assertNotIn(MOWER, ids(p))
        self.assertNotIn(RECON, ids(p))

    def test_deterministic_and_order_independent(self):
        a = plan_week(mission(1500), ledger(500), ITEMS)
        b = plan_week(mission(1500), ledger(500), list(reversed(copy.deepcopy(ITEMS))))
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))

    def test_no_absolute_profit_floor_in_planner(self):
        src = (HERE.parent / "src" / "mbos_economics" / "mission.py").read_text()
        self.assertNotIn("min_profit", src)
        self.assertEqual(load_planner_config()["version"], "2026.10.1")


if __name__ == "__main__":
    unittest.main()
