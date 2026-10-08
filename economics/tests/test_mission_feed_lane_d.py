"""P-03-15: ``mission_feed.plan_from_db`` on a real lane-D PostgreSQL 16 cluster (Agent 04's schema).

Flow in a THROWAWAY cluster: empty DB -> UNKNOWN; mission set by the approver -> DO_NOT_SPEND; ledger funded by the
approver login + scored Items written through 04's StateStore -> a plan whose legs cite real stored scorecard ids,
valid under Agent 01's ``plan_errors``. The ledger comes from ``mbos.capital_position_document()`` (never a literal).
Skipped, never failed, when the lane-D environment is unavailable (see lane_d.available()).
"""

import json
import unittest

import lane_d
from helpers import HERE

from mbos_economics.mission_feed import plan_from_db

_why = lane_d.available()
if _why is None:
    try:
        from mbos.mission import plan_errors
    except ImportError as e:  # pragma: no cover
        _why = f"{e.name} not installed"

GOLD = {p.name.replace(".scored.json", ""): json.loads(p.read_text())
        for p in sorted((HERE.parent / "examples").glob("*.scored.json"))}
PERIOD = {"start": "2026-10-12", "end": "2026-11-10"}   # 30 days: the Items' days_to_cash are 10-22
NAMES = ("trailer_utility_at_walkaway", "project_vehicle_civic", "drywall_basement", "trailer_utility")   # 3 YES + 1 MAYBE


def as_role(dsn: str, user: str) -> str:
    return dsn.replace("user=postgres", f"user={user}")


@unittest.skipIf(_why is not None, f"lane-D environment unavailable: {_why}")
class TestPlanFromDbOnLaneD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = lane_d.cluster()
        cls.dsn = cls._ctx.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    def plan(self):
        import psycopg
        with psycopg.connect(as_role(self.dsn, "mbos_reader"), autocommit=True) as c:
            return plan_from_db(c.cursor(), period=PERIOD)

    def test_empty_then_mission_then_funded_plan(self):
        import psycopg
        from psycopg.types.json import Jsonb
        from mbos_state.store import StateStore

        # 1. empty DB: nothing is invented
        p = self.plan()
        self.assertEqual(plan_errors(p), [])
        self.assertEqual((p["recommendation"], p["legs"]), ("UNKNOWN", []))
        self.assertIn("mission (none set)", p["unknowns"])
        self.assertIn("scored_items (none live)", p["unknowns"])

        # 2. the approver (Michael's channel) sets the mission; still no Items -> DO_NOT_SPEND
        human = Jsonb({"type": "human", "id": "michael"})
        with psycopg.connect(self.dsn, autocommit=True) as c:
            pid = StateStore(c).record_provenance(actor_type="agent", agent_name="agent-03-economics", basis="FACT",
                                                  tool_name="p-03-15-test", tool_version="0.0.1")
        mission = {"mission_version": "1.0.0", "period": PERIOD, "weekly_target_usd": 1500, "hours_available": 30,
                   "notes": "P-03-15 test fixture, not Michael's real target"}
        with psycopg.connect(as_role(self.dsn, "mbos_operator_ui"), autocommit=True) as ap:
            ap.execute("SELECT mbos.set_mission(%s, %s, 'P-03-15 test mission', %s, %s)",
                       (Jsonb(mission), human, [pid], "p0315:mission"))
            p = self.plan()
            self.assertEqual(plan_errors(p), [])
            self.assertEqual((p["recommendation"], p["legs"]), ("DO_NOT_SPEND", []))
            self.assertIn("capital_ledger (none funded: nothing available to deploy)", p["unknowns"])

            # 3. the approver funds the ledger; seed scored Items through 04's StateStore
            ap.execute("SELECT mbos.capital_fund(%s::numeric,%s,'P-03-15 test bankroll',%s,%s)",
                       (2000, human, [pid], "p0315:fund"))
        lane_d.write_scored(self.dsn, [(GOLD[n]["item"], GOLD[n]["provenance"], GOLD[n]["receipt_drafts"])
                                       for n in NAMES])

        with psycopg.connect(as_role(self.dsn, "mbos_reader"), autocommit=True) as c:
            ledger = c.execute("SELECT mbos.capital_position_document('dry_run')").fetchone()[0]
            stored = {r[0]: r[1]["scores"]["scorecard_id"] for r in c.execute(
                "SELECT item_id, doc FROM mbos.v_item_documents WHERE doc ? 'scores'")}
        self.assertEqual(ledger["protected_principal"], 2000)
        self.assertEqual(ledger["available_to_deploy"], 2000)
        self.assertEqual(set(stored), {GOLD[n]["item"]["item_id"] for n in NAMES})

        p = self.plan()
        self.assertEqual(plan_errors(p), [])
        self.assertTrue(p["legs"], json.dumps(p, indent=1)[:2500])
        self.assertEqual(p["recommendation"], "DEPLOY")
        self.assertEqual(p["ledger"]["available_to_deploy"], ledger["available_to_deploy"])    # the ledger fed the plan
        for leg in p["legs"]:
            self.assertEqual(leg["scorecard_id"], stored[leg["item_id"]])      # real stored scorecard ids
            self.assertTrue(leg["scorecard_id"].startswith("scr_"))
        self.assertNotIn("capital_ledger (none funded: nothing available to deploy)", p["unknowns"])
        self.assertNotIn("scored_items (none live)", p["unknowns"])


if __name__ == "__main__":
    unittest.main()
