"""P-03-16: the listing's extracted model year (Agent 02 `model_years`, INFERENCE with quoted evidence) reaches the KB matcher.

Acceptance: "2018 Cub Cadet ..." shows the year-specific recall risk (sourced); a 2015 listing does not; no year -> no hit.
"""
import unittest

import deal_cases as dc
from helpers import CFG

from mbos_economics.valueadd import build_value_add, match_hits

AT = dc.AS_OF
ENTRY = {"id": "cub_cadet_fixture_2018", "category": "mower", "kind": "recall",
         "match": [{"makes": ["cub cadet"], "models": ["RZT SX"], "years": [2018]}],
         "risk": "CPSC FIXTURE recall: fuel tank can leak. Whether the remedy was completed on this unit is UNKNOWN.",
         "plan_hint": "Check the recall remedy.",
         "source": {"title": "CPSC: fixture recall", "url": "https://www.cpsc.gov/fixture", "retrieved": "2026-10-07"}}
KB = {"kb_version": "test", "_hash": "sha256:" + "1" * 64, "entries": [ENTRY]}


def mower(title):
    return {"item_id": "itm_01JM0000000000000000000001", "type": "flip", "category": "mower",
            "normalized": {"title": title}, "sources": [{"source": "ebay", "provenance_id": "prov_01JM0000000000000000000001"}]}


def my(year, quote):
    return [{"year": year, "evidence": quote}]


class TestExtractedYears(unittest.TestCase):
    def test_shorthand_2018_hits_and_quotes_the_title_text(self):
        v = build_value_add(mower("'18 Cub Cadet RZT SX zero turn"), AT, cfg=CFG, kb=KB, model_years=my(2018, "'18"))
        (r,) = v["block"]["model_specific_risks"]
        self.assertEqual(r["basis"], "FACT")
        self.assertIn("cpsc.gov/fixture", r["source"])
        self.assertIn("(2018 from \"'18\")", r["risk"])
        self.assertIn("inference", r["risk"])
        self.assertTrue(r["provenance_id"])

    def test_shorthand_2015_does_not(self):
        v = build_value_add(mower("'15 Cub Cadet RZT SX zero turn"), AT, cfg=CFG, kb=KB, model_years=my(2015, "'15"))
        self.assertNotIn("model_specific_risks", v["block"])
        self.assertTrue(any("not applied" in o for o in v["omitted"]))

    def test_absent_year_is_no_hit_and_unknown(self):
        for my_ in (None, []):
            hits, blocked = match_hits(mower("Cub Cadet RZT SX zero turn"), KB, None, my_)
            self.assertEqual((hits, len(blocked)), ([], 1))

    def test_four_digit_title_still_works_and_old_signature_unchanged(self):
        hits, _ = match_hits(mower("2018 Cub Cadet RZT SX"), KB)
        self.assertEqual(len(hits), 1)

    def test_malformed_years_are_ignored(self):
        hits, _ = match_hits(mower("Cub Cadet RZT SX"), KB, None, [{"year": "2018"}, {"year": True}, "x"])
        self.assertEqual(hits, [])

    def test_deterministic_and_hash_differs_with_years(self):
        a = build_value_add(mower("'18 Cub Cadet RZT SX"), AT, cfg=CFG, kb=KB, model_years=my(2018, "'18"))
        b = build_value_add(mower("'18 Cub Cadet RZT SX"), AT, cfg=CFG, kb=KB, model_years=my(2018, "'18"))
        c = build_value_add(mower("'18 Cub Cadet RZT SX"), AT, cfg=CFG, kb=KB)
        self.assertEqual(a["value_add_hash"], b["value_add_hash"])
        self.assertNotEqual(a["value_add_hash"], c["value_add_hash"])
