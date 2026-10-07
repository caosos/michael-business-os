"""C-11: estimator coverage (READY_QUEUE @ agent-01 20d6dc6).

Acceptance: "Coverage matrix test: 19/19 categories produce either an estimate or an explicit
`insufficient` with gaps." Nothing is ever guessed: no resale price without comps, no scope for an
uncategorized item without a human override.
"""

import hashlib
import unittest

from helpers import CFG

from mbos_economics.comps_feed import query_key
from mbos_economics.engine import score_item
from mbos_economics.estimate import apply_estimate, estimate_item, load_priors
from mbos_economics.inputs import FLIP_CATEGORIES, SERVICE_CATEGORIES

try:
    from test_contracts import Draft202012Validator, economics_v11_errors
except ImportError:  # pragma: no cover
    Draft202012Validator = None

AS_OF = "2026-10-07T18:00:00Z"
PRI = load_priors()
FLIP_KEYS = {"negotiation_factor", "buy_fees_flat", "buy_fees_pct", "parts_cost", "materials_cost", "labor_hours",
             "admin_hours", "repair_success_prob", "sale_prob", "expected_dom_days", "storage_cost_per_day",
             "sell_fees_rate", "sell_fees_flat", "salvage_unsold_frac", "salvage_fail_frac", "ask_to_sold_ratio",
             "required_skills"}
SERVICE_KEYS = {"labor_hours", "materials_cost", "admin_hours", "completion_prob", "deposit_rate", "disposal_cost",
                "payment_terms_days", "required_skills"}


def P(n: int) -> str:
    return f"prov_01JH{n:022d}"


def item(lane: str, cat: str) -> dict:
    flip = lane == "flip"
    return {
        "item_id": "itm_01JH" + f"{int(hashlib.sha256(cat.encode()).hexdigest(), 16) % 10**22:022d}", "schema_version": "1.0.0", "type": lane,
        "category": cat, "state": "RESEARCHING", "created_at": "2026-10-07T12:00:00Z",
        "sources": [{"source": "ebay" if flip else "website_lead", "url": "https://example.invalid/x",
                     "ingestion_method": "api" if flip else "inbound_form", "first_seen_at": "2026-10-07T12:00:00Z",
                     "provenance_id": P(1)}],
        "dedup_key": f"{cat}|coverage",
        "normalized": {"title": f"coverage {cat}", "condition": "used" if flip else "n/a",
                       "price": {"amount": 400, "currency": "USD", "type": "fixed"} if flip else {"type": "quote_requested"},
                       "location": {"city": "Conway", "state": "AR"}},
    }


SOLD = {"comps": [{"kind": "sold", "price": p, "sold_date": f"2026-09-1{i}", "source": "manual",
                   "url": f"https://example.invalid/c/{i}", "provenance_id": P(10 + i)} for i, p in enumerate([900, 950, 1000])]}
SCOPE = {
    "flip": {"rehab.parts_cost": 120, "rehab.labor_hours": 4, "rehab.required_skills": ["repair"]},
    "service": {"job.labor_hours": 3, "job.materials_cost": 25, "job.required_skills": ["repair"]},
}


def with_scope(bundle: dict, lane: str) -> dict:
    b = dict(bundle)
    b["overrides"] = {k: {"value": v, "basis": "FACT", "provenance_id": P(50), "note": "scoped by Michael"}
                      for k, v in SCOPE[lane].items()}
    return b


def classify(lane: str, cat: str, bundle: dict | None) -> dict:
    it = item(lane, cat)
    r = estimate_item(it, bundle, AS_OF)
    row = {"status": r["status"], "blocking": sorted(g["code"] for g in r["gaps"] if g["blocking"])}
    if r["status"] == "estimated":
        est = apply_estimate(it, r)
        row["verdict"] = score_item(est, CFG, AS_OF)["scores"]["scorecard"]["decision"]
        row["item"] = est
    return row


class TestCoverageMatrix(unittest.TestCase):
    def test_19_categories(self):
        self.assertEqual(len(FLIP_CATEGORIES) + len(SERVICE_CATEGORIES), 19)

    def test_every_category_has_priors_and_template(self):
        for cat in FLIP_CATEGORIES:
            p = PRI.group(f"flip.{cat}")
            self.assertTrue(FLIP_KEYS <= set(p), (cat, FLIP_KEYS - set(p)))
            for k in ("parts_cost", "labor_hours", "repair_success_prob"):
                self.assertEqual(set(p[k]), {"new", "used", "parts", "unknown"}, (cat, k))
            self.assertIn(cat, PRI.get("comps_query"), cat)
        for cat in SERVICE_CATEGORIES:
            self.assertTrue(SERVICE_KEYS <= set(PRI.group(f"service.{cat}")), cat)

    def test_every_named_flip_category_has_a_vocabulary(self):
        for cat in FLIP_CATEGORIES - {"other_asset"}:
            groups = [g for g in PRI.get("comps_query")[cat] if not g.startswith("_")]
            self.assertTrue(groups, f"{cat}: empty comps vocabulary")
        self.assertEqual(query_key("tool", "Milwaukee M18 impact wrench kit", PRI), {"brand": "milwaukee", "type": "impact wrench"})
        self.assertEqual(query_key("project_vehicle", "2004 Honda ATV, runs", PRI), {"type": "atv"})

    def test_flips_without_comps_never_guess(self):
        for cat in sorted(FLIP_CATEGORIES):
            with self.subTest(cat):
                row = classify("flip", cat, None)
                self.assertEqual(row["status"], "insufficient")
                expect = "scope_override_required" if cat == "other_asset" else "no_comps"
                self.assertIn(expect, row["blocking"])

    def test_flips_with_sold_comps_estimate(self):
        for cat in sorted(FLIP_CATEGORIES - {"other_asset"}):
            with self.subTest(cat):
                row = classify("flip", cat, SOLD)
                self.assertEqual(row["status"], "estimated", row["blocking"])
                self.assertIn(row["verdict"], ("YES", "MAYBE", "PASS"))

    def test_services_estimate_from_the_lead(self):
        for cat in sorted(SERVICE_CATEGORIES - {"other_service"}):
            with self.subTest(cat):
                row = classify("service", cat, None)
                self.assertEqual(row["status"], "estimated", row["blocking"])

    def test_other_categories_need_human_scope(self):
        for lane, cat, bundle in (("flip", "other_asset", SOLD), ("service", "other_service", {})):
            with self.subTest(cat):
                self.assertEqual(classify(lane, cat, bundle)["blocking"], ["scope_override_required"])
                row = classify(lane, cat, with_scope(bundle, lane))
                self.assertEqual(row["status"], "estimated")
                tags = {a["field"]: a["basis"] for a in row["item"]["economics"]["estimates_meta"]["assumptions"]}
                for f in SCOPE[lane]:
                    self.assertEqual(tags[f"economics.{f}"], "FACT", f)

    def test_unknown_category_is_explicit(self):
        row = classify("flip", "boat", SOLD)
        self.assertEqual((row["status"], row["blocking"]), ("insufficient", ["category_unestimable"]))

    def test_full_matrix_and_tags(self):
        """19/19: each category yields an estimate or an explicit blocking gap, under each bundle."""
        for lane, cats in (("flip", FLIP_CATEGORIES), ("service", SERVICE_CATEGORIES)):
            for cat in sorted(cats):
                for bundle in (None, SOLD, with_scope(SOLD, lane)):
                    with self.subTest((cat, bool(bundle))):
                        row = classify(lane, cat, bundle)
                        self.assertTrue(row["status"] == "estimated" or row["blocking"], row)
                        if row["status"] != "estimated":
                            continue
                        meta = row["item"]["economics"]["estimates_meta"]
                        for a in meta["assumptions"]:
                            self.assertIn(a["basis"], {"FACT", "INFER", "REC", "UNK"})
                        if Draft202012Validator is not None:
                            self.assertEqual(economics_v11_errors(row["item"]), [])


class TestScopeOverrideFeedsTheQuote(unittest.TestCase):
    """C-11 fix: an override of a scope field is used in the computation, not just pasted on top."""

    def test_service_labor_override_changes_quote(self):
        base = estimate_item(item("service", "drywall_repair"), None, AS_OF)["item_patch"]["economics"]["job"]
        b = {"overrides": {"job.labor_hours": {"value": 10, "basis": "FACT", "provenance_id": P(60), "note": "site visit"}}}
        over = estimate_item(item("service", "drywall_repair"), b, AS_OF)["item_patch"]["economics"]["job"]
        self.assertEqual((base["labor_hours"], over["labor_hours"]), (4, 10))
        self.assertGreater(over["quoted_revenue"], base["quoted_revenue"] + 400)   # 6 more hours x $85
        self.assertEqual(over["job_days"], 2)

    def test_flip_labor_override_changes_hold_days(self):
        b = dict(SOLD)
        b["overrides"] = {"rehab.labor_hours": {"value": 12, "basis": "FACT", "provenance_id": P(61), "note": "quoted"}}
        base = estimate_item(item("flip", "mower"), SOLD, AS_OF)["item_patch"]["economics"]["holding"]["expected_hold_days"]
        over = estimate_item(item("flip", "mower"), b, AS_OF)["item_patch"]["economics"]["holding"]["expected_hold_days"]
        self.assertEqual(over - base, 2)          # ceil(12/4) - ceil(3/4) = 3 - 1


if __name__ == "__main__":
    unittest.main()
