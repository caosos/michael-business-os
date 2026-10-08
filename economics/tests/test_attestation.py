"""C-25: attested evidence counts (F-90), truthful waiting text (F-93), UNKNOWN stays UNKNOWN (F-99), legs + HOLD (F-94)."""

import copy
import unittest

from helpers import CFG
from mbos_economics.comps_feed import waiting_status
from mbos_economics.engine import score_item
from mbos_economics.inputs import attested_keys, build_engine_input
from mbos_economics.mission import plan_week
from worked_cases import SCORED_AT, fresh

PID = "prov_01ARZ3NDEKTSV4RRFFQ69G5FAV"


def att(key, basis="FACT", pid=PID):
    return {"finding": f"Michael confirms {key}", "field": f"attestation:{key}", "basis": basis, "provenance_id": pid}


def doorbell(*attested):
    it = fresh("smart_home_install")          # "6 switches, doorbell, 3 cameras, hub"
    ev = it["economics"]["estimates_meta"]["evidence"]
    ev.pop("scope_verified"), ev.pop("customer_screened")
    it["research"] = [att(k) for k in attested]
    it["state"] = "RESEARCHING"
    return it


def scored(it):
    out = score_item(it, CFG, SCORED_AT)
    it = copy.deepcopy(it)
    it["scores"], it["recommendation"] = out["scores"], out["recommendation"]
    return it


def mission():
    return {"mission_version": "1.0.0", "period": {"start": "2026-10-05", "end": "2026-10-11"},
            "weekly_target_usd": 500, "hours_available": 30}


LEDGER = {"ledger_version": "1.0.0", "available_to_deploy": 500}


class TestAttestation(unittest.TestCase):
    def test_without_attestation_stays_maybe_and_names_the_evidence(self):
        sc = scored(doorbell())["scores"]["scorecard"]
        self.assertEqual(sc["decision"], "MAYBE")
        self.assertEqual(sc["evidence_search"]["items"], ["scope_verified"])

    def test_both_attestations_reach_yes_and_raise_confidence(self):
        none = scored(doorbell())["scores"]["scorecard"]
        one = scored(doorbell("scope_verified"))["scores"]["scorecard"]
        both = scored(doorbell("scope_verified", "customer_screened"))["scores"]["scorecard"]
        self.assertEqual((one["decision"], both["decision"]), ("YES", "YES"))
        c = lambda s: s["derived"]["confidence"]
        self.assertLess(c(none), c(one))
        self.assertLess(c(one), c(both))
        self.assertTrue(both["evidence"]["customer_screened"] and both["evidence"]["scope_verified"])

    def test_attestation_changes_inputs_hash_and_replays(self):
        a, b = scored(doorbell()), scored(doorbell("scope_verified"))
        self.assertNotEqual(a["scores"]["inputs_hash"], b["scores"]["inputs_hash"])
        self.assertEqual(b["scores"]["inputs_hash"], scored(doorbell("scope_verified"))["scores"]["inputs_hash"])

    def test_only_attestable_keys_of_the_right_lane_count(self):
        it = doorbell()
        it["research"] = [att("skill_fit_high"), att("three_sold_comps"), att("condition_verified"),
                          att("scope_verified", basis="UNKNOWN"), {**att("customer_screened"), "field": "customer_screened"}]
        self.assertEqual(attested_keys(it), [])
        self.assertEqual(scored(it)["scores"]["scorecard"]["decision"], "MAYBE")

    def test_item_is_not_mutated(self):
        it = doorbell("scope_verified")
        before = copy.deepcopy(it)
        build_engine_input(it)
        self.assertEqual(it, before)


class TestStatusText(unittest.TestCase):
    def test_no_comps_is_waiting_for_a_price_not_running(self):
        t = waiting_status([{"code": "no_sold_comps", "detail": "x", "blocking": True}], 0)
        self.assertIn("Waiting for a price you saw", t)
        self.assertNotIn("running", t.lower())

    def test_comps_but_still_insufficient_is_a_failed_recheck(self):
        t = waiting_status([{"code": "no_road_miles", "detail": "distance unknown", "blocking": True}], 3)
        self.assertEqual(t, "Last re-check failed: distance unknown")


class TestPlanLegs(unittest.TestCase):
    def test_maybe_only_plan_is_hold_with_titles_and_waiting_on(self):
        plan = plan_week(mission(), LEDGER, [scored(doorbell())])
        self.assertEqual(plan["recommendation"], "HOLD")
        leg = plan["legs"][0]
        self.assertEqual(leg["verdict"], "MAYBE")
        self.assertIn("doorbell", leg["title"])
        self.assertTrue(any("scope_verified" in w for w in leg["waiting_on"]))
        self.assertIn("Waiting on", plan["explanation"])
        self.assertEqual(leg["cash_at_risk"], 0.0)       # the contract: only DEPLOY commits cash

    def test_attested_yes_leg_is_deployable(self):
        plan = plan_week(mission(), LEDGER, [scored(doorbell("scope_verified", "customer_screened"))])
        self.assertNotEqual(plan["recommendation"], "HOLD")
        self.assertEqual(plan["legs"][0]["verdict"], "YES")
        self.assertEqual(plan["legs"][0]["waiting_on"], [])


if __name__ == "__main__":
    unittest.main()
