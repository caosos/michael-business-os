"""C-26 (F-106/F-107/F-110): the three training flips through ``research_step`` with only a manual comp."""

import copy
import json
import unittest

from helpers import HERE

from mbos_economics.comps_feed import gap_text, research_step, scored_status
from mbos_economics.estimate import estimate_item, load_priors, prior_category

AS_OF = "2026-10-07T18:00:00Z"
REC = json.loads((HERE / "fixtures" / "training_flips.json").read_text())["records"]
PRI = load_priors()


def prov_id(n: int) -> str:
    return f"prov_01JF{n:022d}"


def listing(key: str, n: int) -> dict:
    r = copy.deepcopy(REC[key]["record"])
    return {"item_id": f"itm_01JF{n:022d}", "schema_version": "1.0.0", "state": "RESEARCHING",
            "created_at": "2026-10-07T10:00:00Z", "type": r["type"], "category": r["category"],
            "subcategory": r.get("subcategory"), "dedup_key": r["dedup_key"], "normalized": r["normalized"],
            "economics": r["economics"],
            "sources": [{"source": REC[key]["source"], "url": REC[key]["url"], "ingestion_method": "manual",
                         "first_seen_at": "2026-10-07T10:00:00Z", "provenance_id": prov_id(n)}]}


def manual_comp(category: str, title: str, price: int, n: int):
    comp = {"kind": "sold", "price": price, "sold_date": "2026-10-01", "source": "manual", "category": category,
            "title": title, "currency": "USD", "provenance_id": prov_id(900 + n), "url": f"https://example.invalid/seen/{n}",
            "fetched_at": "2026-10-07T17:00:00Z"}
    prov = {"provenance_id": prov_id(900 + n), "basis": "FACT", "source_uri": comp["url"],
            "fetched_at": comp["fetched_at"], "actor_type": "human"}
    return comp, prov


def run(key, n, category, title, price):
    c, p = manual_comp(category, title, price, n)
    return research_step(listing(key, n), [c], [p], AS_OF)


class TestTrainingClasses(unittest.TestCase):
    def test_tv_is_a_first_class_category_and_reaches_yes_within_cap(self):
        it = listing("TRAIN-TV-1", 1)
        self.assertEqual(prior_category(it, PRI), "consumer_electronics")
        r = run("TRAIN-TV-1", 1, "other_asset", "55 inch LED TV sold", 95)
        self.assertEqual(r["proposed_next_state"], "SCORED")
        sc = r["item"]["scores"]["scorecard"]
        self.assertEqual(sc["decision"], "YES")
        self.assertLessEqual(sc["derived"]["cash_at_risk"], 500)
        self.assertNotIn("scope_override_required", [g["code"] for g in r["estimate"]["gaps"]])

    def test_unknown_other_asset_still_needs_a_scope_override(self):
        it = listing("TRAIN-TV-1", 2)
        it["normalized"]["title"], it["subcategory"] = "Antique butter churn", "churn"
        r = estimate_item(it, {}, AS_OF)
        self.assertEqual(r["status"], "insufficient")
        self.assertIn("scope_override_required", [g["code"] for g in r["gaps"]])

    def test_mower_passes_archived_on_the_listing_price(self):
        r = run("TRAIN-MOWER-1", 3, "mower", "Older riding mower 42in sold", 750)
        sc = r["item"]["scores"]["scorecard"]
        self.assertEqual(sc["decision"], "PASS")
        self.assertFalse(sc["pass_on_priors"])
        self.assertTrue(sc["pass_basis"]["gates"]["cash_ok"]["evidence_backed"])
        self.assertIn("economics.acquisition.expected_buy_price", sc["pass_basis"]["evidence_backed_inputs"])

    def test_recon_is_maybe_naming_fault_identified(self):
        r = run("TRAIN-RECON-1", 4, "mechanical_equipment", "Honda Recon ATV sold", 1050)
        rec = r["item"]["recommendation"]
        self.assertEqual(rec["verdict"], "MAYBE")
        self.assertTrue(any("fault not identified" in x for x in rec["rationale"]))
        self.assertIn("fault_identified", r["status_text"])


class TestInlineEconomics(unittest.TestCase):
    def test_fact_inline_values_are_kept_and_priors_marked(self):
        r = run("TRAIN-MOWER-1", 5, "mower", "Older riding mower 42in sold", 750)
        econ = r["item"]["economics"]
        self.assertEqual(econ["acquisition"]["expected_buy_price"], 480)
        self.assertEqual(econ["rehab"]["parts_cost"], 45)
        by = {a["field"]: a for a in econ["estimates_meta"]["assumptions"]}
        self.assertEqual(by["economics.acquisition.expected_buy_price"]["basis"], "FACT")
        self.assertEqual(by["economics.acquisition.ask_price"]["provenance_ids"], [prov_id(5)])

    def test_inline_resale_price_is_never_kept(self):
        it = listing("TRAIN-TV-1", 6)
        e = estimate_item(it, {}, AS_OF)
        self.assertIn("no_comps", [g["code"] for g in e["gaps"]])

    def test_buy_defaults_to_ask_as_inference_without_inline_economics(self):
        it = listing("TRAIN-TV-1", 7)
        it["economics"] = {}
        c, p = manual_comp("other_asset", "55 inch LED TV sold", 95, 7)
        r = research_step(it, [c], [p], AS_OF)
        by = {a["field"]: a for a in r["item"]["economics"]["estimates_meta"]["assumptions"]}
        self.assertEqual(by["economics.acquisition.expected_buy_price"]["basis"], "INFER")
        self.assertEqual(r["item"]["economics"]["acquisition"]["expected_buy_price"], 30)


class TestStatusText(unittest.TestCase):
    def test_every_gap_code_states_its_real_blocker(self):
        for code, needle in (("scope_override_required", "Waiting for you"), ("thin_comps", "Add sold prices"),
                             ("repair_scope_unknown", "fault is not identified"),
                             ("transport_unclassified", "truck or needs a trailer")):
            self.assertIn(needle, gap_text({"code": code, "detail": "d", "blocking": False}), code)

    def test_yes_status_is_plain(self):
        self.assertEqual(scored_status([], "YES", None), "Scored YES.")
        self.assertIn("a + b -> MAYBE", scored_status([], "PASS", "a + b -> MAYBE"))
