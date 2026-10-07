"""C-18: model-year matching for year-specific KB entries (NHTSA recalls and complaints are per make/model/YEAR).

Acceptance (READY_QUEUE): "a 2018 recall does not flag a 2021 listing or a yearless one; a 2018 listing matches".
Rule: a year-specific entry applies only when the LISTING states a year (read from the title: INFERENCE, with the evidence
shown). A yearless listing, or one whose stated years are not all covered, never matches: the card shows UNKNOWN.
"""

import copy
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import deal_cases as dc
from helpers import CFG

from mbos_economics.valueadd import (NoteError, build_value_add, group_years, listing_years, load_kb,
                                     load_manual_notes, match_entries, match_hits, merge_manual, new_manual_note)

KB = load_kb()
AT = "2026-10-07T20:00:00Z"


def entry(years=(2018,), makes=("ford",), models=("F-150",), eid="nhtsa_fixture_2018", kind="failure_mode"):
    years = list(years) if isinstance(years, tuple) else years          # JSON has lists; a tuple here is just the default
    return {"id": eid, "category": "project_vehicle", "kind": kind,
            "match": [{"makes": list(makes), "models": list(models), **({"years": years} if years is not None else {})}],
            "risk": "NHTSA campaign FIXTURE-18V001 (fixture): the fuel pump can fail, stalling the engine. Remedy: dealer replacement. "
                    "Whether the remedy was completed on this unit is UNKNOWN.",
            "plan_hint": "Ask a Ford dealer whether the campaign remedy was completed.",
            "source": {"title": "NHTSA: fixture campaign, recall date Jan 1, 2019", "url": "https://www.nhtsa.gov/fixture/18V001",
                       "retrieved": "2026-10-07"}}


def kb_with(*entries):
    return {"kb_version": "test", "_hash": "sha256:" + "1" * 64, "entries": list(entries)}


def vehicle(title):
    return {"item_id": "itm_01JM0000000000000000000001", "type": "flip", "category": "project_vehicle",
            "normalized": {"title": title}, "sources": [{"source": "ebay", "provenance_id": "prov_01JM0000000000000000000001"}]}


def ids(title, kb):
    return [e["id"] for e in match_entries(vehicle(title), kb)]


class TestAcceptance(unittest.TestCase):
    KBY = kb_with(entry())

    def test_a_2018_listing_matches(self):
        self.assertEqual(ids("2018 Ford F-150 XLT project truck", self.KBY), ["nhtsa_fixture_2018"])

    def test_a_2021_listing_does_not(self):
        self.assertEqual(ids("2021 Ford F-150 XLT project truck", self.KBY), [])

    def test_a_yearless_listing_does_not(self):
        self.assertEqual(ids("Ford F-150 project truck, runs", self.KBY), [])

    def test_blocked_matches_are_recorded_as_unknown_never_silent(self):
        v = build_value_add(vehicle("Ford F-150 project truck"), dc.AS_OF, cfg=CFG, kb=self.KBY)
        self.assertNotIn("model_specific_risks", v["block"])
        self.assertEqual(v["matched"], [])
        self.assertEqual([b["entry_id"] for b in v["year_blocked"]], ["nhtsa_fixture_2018"])
        self.assertIn("states no model year", v["year_blocked"][0]["reason"])
        self.assertTrue(any("nhtsa_fixture_2018 not applied" in o and "UNKNOWN" in o for o in v["omitted"]))
        v21 = build_value_add(vehicle("2021 Ford F-150 project truck"), dc.AS_OF, cfg=CFG, kb=self.KBY)
        self.assertIn("is not entirely within the covered years 2018", v21["year_blocked"][0]["reason"])

    def test_the_evidence_for_the_year_is_shown_and_called_an_inference(self):
        v = build_value_add(vehicle("2018 Ford F-150 XLT project truck"), dc.AS_OF, cfg=CFG, kb=self.KBY)
        (r,) = v["block"]["model_specific_risks"]
        self.assertIn("Model year read from the listing title (2018)", r["risk"])
        self.assertIn("inference", r["risk"])
        self.assertIn("not verified against the unit", r["risk"])
        self.assertEqual(v["year_evidence"], {"nhtsa_fixture_2018": "2018"})

    def test_make_and_model_are_still_required(self):
        self.assertEqual(ids("2018 Chevrolet Silverado project truck", self.KBY), [])
        self.assertEqual(ids("2018 Ford Ranger project truck", self.KBY), [])


class TestYearForms(unittest.TestCase):
    def test_list_range_and_string_forms(self):
        self.assertEqual(group_years({"years": [2012, 2013]}), {2012, 2013})
        self.assertEqual(group_years({"years": {"from": 2010, "to": 2012}}), {2010, 2011, 2012})
        self.assertEqual(group_years({"years": "2010-2012"}), {2010, 2011, 2012})
        self.assertIsNone(group_years({"makes": ["ford"]}))                       # not year-specific

    def test_malformed_years_are_refused_by_the_loader(self):
        for bad in ([], ["2018"], [True], [1900], [2099], {"from": 2020, "to": 2010}, {"from": 1960, "to": 2030}, "last year", 2018):
            e = entry(years=bad)
            with tempfile.TemporaryDirectory() as td:
                base = {k: v for k, v in copy.deepcopy(KB).items() if k != "_hash"}
                base["entries"] = [e]
                p = Path(td) / "kb.json"
                p.write_text(json.dumps(base))
                with self.assertRaises(ValueError, msg=bad) as cm:
                    load_kb(p)
            self.assertIn("years", str(cm.exception))

    def test_valid_year_entries_load(self):
        for good in ([2018], [2012, 2013, 2014], {"from": 2010, "to": 2014}, "2010-2014"):
            with tempfile.TemporaryDirectory() as td:
                base = {k: v for k, v in copy.deepcopy(KB).items() if k != "_hash"}
                base["entries"] = [entry(years=good)]
                p = Path(td) / "kb.json"
                p.write_text(json.dumps(base))
                self.assertEqual(len(load_kb(p)["entries"]), 1, good)

    def test_malformed_years_fail_closed_in_the_matcher(self):
        self.assertEqual(ids("2018 Ford F-150", kb_with(entry(years=["2018"]))), [])


class TestListingYears(unittest.TestCase):
    def test_extraction(self):
        yrs = lambda t: listing_years(t.lower())[0]
        self.assertEqual(yrs("2018 Ford F-150"), {2018})
        self.assertEqual(yrs("Ford F-150 2018 XLT"), {2018})
        self.assertEqual(yrs("2010-2014 Ford F-150"), {2010, 2011, 2012, 2013, 2014})
        self.assertEqual(yrs("2010-14 Ford F-150"), {2010, 2011, 2012, 2013, 2014})
        self.assertEqual(yrs("2010 to 2014 Ford F-150"), {2010, 2011, 2012, 2013, 2014})
        self.assertEqual(yrs("2012 and 2018 Ford"), {2012, 2018})

    def test_not_years(self):
        for t in ("Ford F-150 with 2000 lb winch", "Ford F-150 $2000 obo", "2000 watt generator", "05 Ford F-150",
                  "Ford F-150 w/ 2000 psi washer", "Ford F-150 3.5L, 1999 miles", "Ford F-150 20000 miles"):
            self.assertEqual(listing_years(t.lower())[0], set(), t)

    def test_a_range_must_be_sane(self):
        self.assertEqual(listing_years("2018-2010 ford")[0], {2018, 2010})        # reversed: read as two separate years
        self.assertEqual(listing_years("1985 ford")[0], {1985})
        self.assertEqual(listing_years("1949 ford")[0], set())                    # out of range


class TestAllNamedYearsMustBeCovered(unittest.TestCase):
    """A unit has ONE model year. If the title names several, the entry applies only when every one is covered; otherwise
    the unit might be outside the covered years and a safety claim would be false."""

    def test_rule(self):
        one = kb_with(entry(years=[2012]))
        wide = kb_with(entry(years=[2012, 2013, 2014]))
        self.assertEqual(ids("2012-2014 Ford F-150", one), [])                    # a range wider than the entry: UNKNOWN
        self.assertEqual(ids("2012-2014 Ford F-150", wide), ["nhtsa_fixture_2018"])
        self.assertEqual(ids("2012 Ford F-150 (replaced the 2018 engine)", one), [])    # conservative: other year named
        self.assertEqual(ids("2013 Ford F-150", wide), ["nhtsa_fixture_2018"])

    def test_two_groups_with_different_years(self):
        e = entry(years=[2012])
        e["match"].append({"makes": ["ford"], "models": ["F-150"], "years": [2018]})
        self.assertEqual(ids("2018 Ford F-150", kb_with(e)), ["nhtsa_fixture_2018"])
        self.assertEqual(ids("2012 Ford F-150", kb_with(e)), ["nhtsa_fixture_2018"])
        self.assertEqual(ids("2015 Ford F-150", kb_with(e)), [])


class TestNothingElseChanged(unittest.TestCase):
    def test_entries_without_years_behave_exactly_as_before(self):
        for title, expect in (("Generac GP6500E portable generator", ["generac_gp_carburetor_fuel_leak_2026"]),
                              ("Cub Cadet 17AWCBYS010 zero turn", ["cub_cadet_rzt_sx_efi_fuel_tank_2018"])):
            cat = "generator" if "Generac" in title else "mower"
            self.assertEqual([e["id"] for e in match_entries({"category": cat, "normalized": {"title": title}}, KB)], expect)
        hits, blocked = match_hits({"category": "generator", "normalized": {"title": "Generac GP6500E"}}, KB)
        self.assertEqual((len(hits), blocked), (1, []))
        self.assertIsNone(hits[0]["year_evidence"])

    def test_shipped_entries_have_no_years(self):
        self.assertTrue(all("years" not in g for e in KB["entries"] for g in e["match"]))

    def test_numeric_asymmetry_is_preserved(self):
        """Shipped KBs still refuse numeric-only model tokens; a human's own note may use one (a real 'John Deere 4020')."""
        with tempfile.TemporaryDirectory() as td:
            base = {k: v for k, v in copy.deepcopy(KB).items() if k != "_hash"}
            base["entries"] = [entry(models=("6500",), years=[2018])]
            p = Path(td) / "kb.json"
            p.write_text(json.dumps(base))
            with self.assertRaises(ValueError) as cm:
                load_kb(p)
        self.assertIn("purely numeric", str(cm.exception))
        n = new_manual_note(category="project_vehicle", makes=["john deere"], models=["4020"], kind="known_weakness",
                            statement="4020 power-shift clutch pack wears; budget a rebuild.", entered_by="michael",
                            entered_at=AT, basis_of_knowledge="own experience")["note"]
        merged = merge_manual(KB, load_manual_notes({"notes_format": 1, "notes": [n]}))
        self.assertEqual(len(match_entries(vehicle("John Deere 4020 tractor"), merged)), 1)


class TestManualNotesCanBeYearSpecific(unittest.TestCase):
    def note(self, **kw):
        base = dict(category="project_vehicle", makes=["ford"], models=["F-150"], kind="known_weakness",
                    statement="The 2012 F-150 cam phaser rattle is a known weak point; budget the phasers.",
                    entered_by="michael", entered_at=AT, basis_of_knowledge="own experience", years=[2012])
        base.update(kw)
        return new_manual_note(**base)

    def test_year_specific_note(self):
        n = self.note()["note"]
        self.assertEqual(n["match"][0]["years"], [2012])
        merged = merge_manual(KB, load_manual_notes({"notes_format": 1, "notes": [n]}))
        self.assertEqual([e["origin"] for e in match_entries(vehicle("2012 Ford F-150"), merged)], ["manual"])
        self.assertEqual(match_entries(vehicle("2018 Ford F-150"), merged), [])
        self.assertEqual(match_entries(vehicle("Ford F-150"), merged), [])

    def test_note_years_are_validated_and_change_the_id(self):
        with self.assertRaises(NoteError) as cm:
            self.note(years=["twenty twelve"])
        self.assertIn("years", str(cm.exception))
        self.assertNotEqual(self.note()["note"]["note_id"], self.note(years=[2013])["note"]["note_id"])
        self.assertNotIn("years", self.note(years=None)["note"]["match"][0])


class TestDeterminism(unittest.TestCase):
    def test_the_year_evidence_is_part_of_the_hash(self):
        kb = kb_with(entry(years=[2012, 2018]))
        a = build_value_add(vehicle("2018 Ford F-150"), dc.AS_OF, cfg=CFG, kb=kb)
        b = build_value_add(vehicle("2012 Ford F-150"), dc.AS_OF, cfg=CFG, kb=kb)
        self.assertNotEqual(a["value_add_hash"], b["value_add_hash"])
        self.assertEqual(a, build_value_add(vehicle("2018 Ford F-150"), dc.AS_OF, cfg=CFG, kb=kb))


try:
    from mbos.card import build_card, validate_card
    _card_ok = bool(os.environ.get("MBOS_CONTRACTS_DIR"))
except ImportError:  # pragma: no cover
    _card_ok = False


@unittest.skipUnless(_card_ok, "needs agent-01 mbos.card installed and MBOS_CONTRACTS_DIR=<archive>/docs/research/contracts")
class TestCardIntegration(unittest.TestCase):
    def card(self, title):
        it = dc.item(11, "project_vehicle", title, 3500, 25)
        v = build_value_add(it, dc.AS_OF, cfg=CFG, kb=kb_with(entry()))
        return build_card(it, [], [], {"value_add": v["block"]}, profile=dc.PROFILE,
                          now=datetime(2026, 10, 7, 20, tzinfo=timezone.utc)), v

    def test_validate_card_clean_for_match_and_for_blocked(self):
        for title in ("2018 Ford F-150 project truck", "2021 Ford F-150 project truck", "Ford F-150 project truck"):
            card, _ = self.card(title)
            self.assertEqual(validate_card(card), [], title)

    def test_card_shows_the_risk_only_for_the_stated_year(self):
        self.assertEqual(len(self.card("2018 Ford F-150 project truck")[0]["value_add_plan"]["model_specific_risks"]), 1)
        self.assertEqual(self.card("2021 Ford F-150 project truck")[0]["value_add_plan"]["model_specific_risks"], [])
        self.assertEqual(self.card("Ford F-150 project truck")[0]["value_add_plan"]["model_specific_risks"], [])


if __name__ == "__main__":
    unittest.main()
