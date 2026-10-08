"""C-08: morning digest (READY_QUEUE @ agent-01 71adb0d).

Acceptance: "Deterministic ranking over the 13 goldens + 02 fixtures; explanation per row."
(14 goldens since C-06 added the welder.)
"""

import copy
import json
import random
import unittest

from helpers import CFG, CFG_BIG, HERE
from worked_cases import SCORED_AT

from mbos_economics.digest import build_digest, render_text
from mbos_economics.engine import score_item
from mbos_economics.estimate import apply_estimate, estimate_item

AS_OF = "2026-10-07T18:00:00Z"


def corpus() -> list[dict]:
    items = [json.loads(p.read_text())["item"] for p in sorted((HERE.parent / "examples").glob("*.scored.json"))]
    for it in items:       # digest logic is tested on the pre-C-24 $1,500 / $800 caps; the goldens themselves are at $500
        o = score_item(it, CFG_BIG, SCORED_AT)
        it["scores"], it["recommendation"] = o["scores"], o["recommendation"]
    for it in json.loads((HERE / "fixtures" / "agent02" / "items.json").read_text()):
        it = copy.deepcopy(it)
        it["state"] = "RESEARCHING"
        r = estimate_item(it, None, AS_OF)
        if r["status"] == "estimated":
            it = apply_estimate(it, r)
            o = score_item(it, CFG_BIG, AS_OF)
            it["scores"], it["recommendation"], it["state"] = o["scores"], o["recommendation"], "RECOMMENDED"
        items.append(it)
    return items


ITEMS = corpus()


class TestAcceptanceC08(unittest.TestCase):
    def setUp(self):
        self.d = build_digest(ITEMS, AS_OF)

    def test_buckets_and_exclusions(self):
        self.assertEqual(len(ITEMS), 24)
        self.assertEqual(self.d["counts"], {"act_alert": 2, "act": 2, "research": 7, "research_r13": 6})
        self.assertEqual(len(self.d["excluded"]), 7)     # 1 evidence-backed PASS + 6 unscored 02 flips
        why = {e["item_id"]: e["reason"] for e in self.d["excluded"]}
        self.assertIn("evidence-backed", why["itm_01JB0000000000000000000007"])    # truck over cap
        self.assertEqual(sum("not scored yet" in r for r in why.values()), 6)

    def test_ranking_order(self):
        top = [(r["rank"], r["item_id"], r["bucket"]) for r in self.d["rows"][:5]]
        self.assertEqual(top, [
            # C-20: inside a bucket, ordered by rank_score (risk-adjusted profit x confidence x velocity)
            (1, "itm_01JB0000000000000000000022", "act_alert"),   # smart-home: rank 697.73
            (2, "itm_01JB0000000000000000000002", "act_alert"),   # trailer at $225: rank 46.54
            (3, "itm_01JB0000000000000000000020", "act"),         # drywall: rank 434.64
            (4, "itm_01JB0000000000000000000006", "act"),         # project vehicle: tied-up cash, rank 25.11
            (5, "itm_01JB0000000000000000000024", "research"),    # equipment repair: re-quote
        ])
        self.assertEqual([r["rank"] for r in self.d["rows"]], list(range(1, 18)))
        buckets = [r["bucket"] for r in self.d["rows"]]
        self.assertEqual(buckets, sorted(buckets, key=["act_alert", "act", "research", "research_r13"].index))

    def test_every_row_explained_and_referenced(self):
        for r in self.d["rows"]:
            self.assertTrue(r["reason"] and "->" in r["reason"], r["item_id"])
            self.assertTrue(r["action"])
            self.assertRegex(r["refs"]["scorecard_id"], r"^scr_")
            self.assertRegex(r["refs"]["provenance_id"], r"^prov_")
            self.assertRegex(r["refs"]["inputs_hash"], r"^sha256:")
        self.assertEqual(set(self.d["provenance"]["derived_from"]), {r["refs"]["provenance_id"] for r in self.d["rows"]})

    def test_specific_actions(self):
        by = {r["item_id"]: r for r in self.d["rows"]}
        self.assertEqual(by["itm_01JB0000000000000000000002"]["action"], "decide: offer at or below $227")
        self.assertEqual(by["itm_01JB0000000000000000000024"]["action"], "re-quote: YES at $1,098 or more")
        self.assertIn("license_ok", by["itm_01JB0000000000000000000023"]["action"])
        self.assertIn("pph_floor_ok", by["itm_01JB0000000000000000000003"]["action"])
        self.assertTrue(all("blocked by" in r["action"] or ":" in r["action"] for r in self.d["rows"]))

    def test_provenance_contract(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads((HERE / "contracts" / "provenance.schema.json").read_text())
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(self.d["provenance"])), [])

    def test_deterministic_under_shuffle(self):
        for seed in range(5):
            shuffled = ITEMS[:]
            random.Random(seed).shuffle(shuffled)
            self.assertEqual(build_digest(shuffled, AS_OF)["digest_hash"], self.d["digest_hash"])

    def test_text_render(self):
        txt = render_text(self.d)
        self.assertEqual(len(txt.splitlines()), 1 + 17 + 1)
        self.assertIn(" 1. [later] smart_home_install: YES + ALERT", txt)


class TestC20CapitalVelocityRanking(unittest.TestCase):
    """C-20: the digest ranks by the C-19 objective; the TV outranks the mower today; every row says why."""

    @classmethod
    def setUpClass(cls):
        cls.items = [json.loads(p.read_text())["item"]
                     for p in sorted((HERE.parent / "examples" / "class_aware").glob("*.scored.json"))]
        for it in cls.items:
            it["state"] = "RESEARCHING"
        cls.d = build_digest(cls.items, AS_OF)

    def test_tv_above_mower_today(self):
        by = {r["item_id"]: r for r in self.d["rows"]}
        tv, mower = by["itm_01JB0000000000000000000101"], by["itm_01JB0000000000000000000102"]
        self.assertLess(tv["rank"], mower["rank"])
        self.assertEqual((tv["bucket"], tv["deal_class"]), ("research", "MICRO_FLIP"))
        self.assertGreater(tv["rank_score"], mower["rank_score"])
        self.assertLess(tv["ev_decision"], mower["ev_decision"])          # smaller dollars, higher rank

    def test_rows_name_their_components(self):
        for r in self.d["rows"]:
            self.assertIn("rank ", r["reason"])
            self.assertIn("velocity", r["reason"])
            self.assertIn("risk-adjusted", r["reason"])
            self.assertIn("at risk", r["reason"])
        mower = next(r for r in self.d["rows"] if r["item_id"].endswith("102"))
        self.assertIn("WRONG BUY TODAY", mower["reason"])                  # out-of-season flag is visible
        self.assertIn("capital intensive flip", mower["reason"])

    def test_pre_c19_card_sorts_last_in_bucket_and_says_so(self):
        items = copy.deepcopy(self.items)
        old = next(i for i in items if i["item_id"].endswith("101"))
        del old["scores"]["scorecard"]["ranking"]
        rows = build_digest(items, AS_OF)["rows"]
        row = next(r for r in rows if r["item_id"] == old["item_id"])
        self.assertIn("re-score", row["reason"])
        self.assertIsNone(row["rank_score"])
        same = [r for r in rows if r["bucket"] == row["bucket"]]
        self.assertEqual(same[-1]["item_id"], old["item_id"])


class TestDeadlines(unittest.TestCase):
    def test_deadline_in_window_jumps_its_bucket(self):
        items = copy.deepcopy(ITEMS)
        civic = next(i for i in items if i["item_id"] == "itm_01JB0000000000000000000006")
        civic["recommendation"]["expires_at"] = "2026-10-08T06:00:00Z"            # 12 h
        rows = build_digest(items, AS_OF)["rows"]
        r = next(x for x in rows if x["item_id"] == civic["item_id"])
        self.assertEqual((r["rank"], r["window"], r["hours_left"]), (3, "<24h", 12.0))
        self.assertIn("deadline in 12", r["reason"])
        self.assertEqual(rows[0]["bucket"], "act_alert")         # buckets still come first

    def test_deadline_beats_value_inside_a_bucket(self):
        items = copy.deepcopy(ITEMS)
        civic = next(i for i in items if i["item_id"] == "itm_01JB0000000000000000000006")     # lower rank score
        civic["recommendation"]["expires_at"] = "2026-10-09T18:00:00Z"                        # 48 h
        acts = [x["item_id"] for x in build_digest(items, AS_OF)["rows"] if x["bucket"] == "act"]
        self.assertEqual(acts, ["itm_01JB0000000000000000000006", "itm_01JB0000000000000000000020"])

    def test_deadline_outside_horizon_ignored_for_order(self):
        items = copy.deepcopy(ITEMS)
        drywall = next(i for i in items if i["item_id"] == "itm_01JB0000000000000000000020")
        drywall["recommendation"]["expires_at"] = "2026-10-20T18:00:00Z"                      # beyond 72 h
        r = next(x for x in build_digest(items, AS_OF)["rows"] if x["item_id"] == drywall["item_id"])
        self.assertEqual((r["rank"], r["window"]), (3, "later"))

    def test_past_deadline_excluded(self):
        items = copy.deepcopy(ITEMS)
        items[0]["recommendation"]["expires_at"] = "2026-10-07T00:00:00Z"
        d = build_digest(items, AS_OF)
        self.assertIn("has passed", {e["item_id"]: e["reason"] for e in d["excluded"]}[items[0]["item_id"]])

    def test_closed_states_excluded(self):
        items = copy.deepcopy(ITEMS)
        for it in items:
            if it.get("scores"):
                it["state"] = "APPROVED"
        d = build_digest(items, AS_OF)
        self.assertEqual(d["rows"], [])


if __name__ == "__main__":
    unittest.main()
