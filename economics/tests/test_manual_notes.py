"""C-17: Michael's own mechanic notes enter as `manual` entries with provenance; nothing unsourced ships.

Acceptance (READY_QUEUE): "Source plan doc + a `manual` entry path in the KB with tests; nothing unsourced ships".
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import deal_cases as dc
from helpers import CFG, HERE

from mbos_economics.comps_feed import research_step
from mbos_economics.config import CONFIG_DIR
from mbos_economics.valueadd import (NoteError, build_value_add, load_kb, load_manual_notes, match_entries, merge_manual,
                                     new_manual_note)

KB = load_kb()
AT = "2026-10-07T20:00:00Z"
STATEMENT = "X380 hydro drive belt idler bracket cracks at the weld; budget a bracket before it strands the unit."


def note(**over):
    kw = dict(category="mower", makes=["john deere"], models=["X380"], kind="known_weakness", statement=STATEMENT,
              entered_by="michael", entered_at=AT, basis_of_knowledge="own experience",
              plan_hint="Price a replacement bracket into the parts budget.")
    kw.update(over)
    return new_manual_note(**kw)


def doc(*notes):
    return {"notes_format": 1, "notes": list(notes)}


def deere_item():
    it = dc.item(8, "mower", "John Deere X380 riding lawn tractor, deck work needed", 1100, 25)
    comps, prov = dc.comps_for("mower", "riding lawn tractor", [2400, 2500, 2600, 2700, 2800], 150)
    r = research_step(it, comps, prov, dc.AS_OF, profile=dc.PROFILE)
    assert r["proposed_next_state"] == "SCORED", r["estimate"]          # comps must match the listing's type
    return r["item"]


DEERE = deere_item()


class TestCreation(unittest.TestCase):
    def test_note_and_human_provenance(self):
        out = note()
        n, p = out["note"], out["provenance"]
        self.assertRegex(n["note_id"], r"^mn_[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertEqual(n["provenance_id"], p["provenance_id"])
        self.assertEqual((p["actor_type"], p["human_actor"], p["basis"]), ("human", "michael", "RECOMMENDATION"))
        self.assertEqual((p["tool_name"], p["created_at"]), ("mbos.manual_note", AT))
        self.assertEqual(p["inputs_used"][0]["ref"], n["note_id"])

    def test_provenance_validates_against_provenance_v1(self):
        try:
            from jsonschema import Draft202012Validator
        except ImportError:
            self.skipTest("jsonschema not installed")
        schema = json.loads((HERE / "contracts" / "provenance.schema.json").read_text())
        self.assertEqual(list(Draft202012Validator(schema).iter_errors(note()["provenance"])), [])

    def test_deterministic_and_content_addressed(self):
        self.assertEqual(note(), note())
        self.assertNotEqual(note()["note"]["note_id"], note(statement=STATEMENT + " Seen twice.")["note"]["note_id"])
        self.assertNotEqual(note()["note"]["note_id"], note(entered_at="2026-10-08T20:00:00Z")["note"]["note_id"])

    def test_reads_no_clock(self):
        src = (Path(__file__).resolve().parents[1] / "src" / "mbos_economics" / "valueadd.py").read_text()
        self.assertNotIn("datetime.now", src)
        self.assertNotIn("time.time(", src)


class TestRefusals(unittest.TestCase):
    def refused(self, **over):
        with self.assertRaises(NoteError) as cm:
            note(**over)
        return " | ".join(cm.exception.problems)

    def test_author_time_and_basis_are_mandatory(self):
        self.assertIn("entered_by is required", self.refused(entered_by=""))
        self.assertIn("entered_at must be an RFC 3339", self.refused(entered_at="2026-10-07T20:00:00"))     # naive timestamp
        self.assertIn("basis_of_knowledge is required", self.refused(basis_of_knowledge=""))

    def test_must_name_a_make_and_a_model(self):
        self.assertIn("BOTH makes and models", self.refused(models=[]))
        self.assertIn("BOTH makes and models", self.refused(makes=[]))

    def test_category_and_kind_are_closed_sets(self):
        self.assertIn("is not a flip category", self.refused(category="boat"))
        self.assertIn("must be one of", self.refused(kind="gossip"))

    def test_elementary_advice_is_refused_with_guidance(self):
        for text in ("Check the compression first.", "Look for leaks before buying.", "Make sure it starts."):
            msg = self.refused(statement=text)
            self.assertIn("elementary advice", msg)
            self.assertIn("specific to THIS model", msg)
        self.assertIn("elementary advice", self.refused(plan_hint="Check the battery."))

    def test_overlong_and_non_https_reference(self):
        self.assertIn("over 600 characters", self.refused(statement="X380 bracket " * 60))
        self.assertIn("reference_url must be https", self.refused(reference_url="http://forum.example/thread"))

    def test_a_note_cannot_claim_fact(self):
        n = note()["note"]
        n["basis"] = "FACT"
        with self.assertRaises(NoteError) as cm:
            load_manual_notes(doc(n))
        self.assertIn("never FACT", str(cm.exception))

    def test_loader_refuses_missing_or_malformed_provenance(self):
        n = note()["note"]
        for bad in ("", "prov_not_an_id", "itm_01JK0000000000000000000001"):
            m = copy.deepcopy(n)
            m["provenance_id"] = bad
            with self.assertRaises(NoteError):
                load_manual_notes(doc(m))

    def test_loader_reports_every_problem_and_returns_nothing_partial(self):
        good, bad = note()["note"], copy.deepcopy(note(models=["X350"])["note"])
        bad["entered_by"] = ""
        bad["kind"] = "gossip"
        with self.assertRaises(NoteError) as cm:
            load_manual_notes(doc(good, bad))
        joined = " | ".join(cm.exception.problems)
        self.assertIn("notes[1] entered_by is required", joined)
        self.assertIn("notes[1] kind", joined)
        self.assertEqual(len([p for p in cm.exception.problems if p.startswith("notes[0]")]), 0)

    def test_duplicate_ids_and_format(self):
        n = note()["note"]
        with self.assertRaises(NoteError):
            load_manual_notes(doc(n, copy.deepcopy(n)))
        with self.assertRaises(NoteError):
            load_manual_notes({"notes_format": 2, "notes": []})


class TestMerge(unittest.TestCase):
    def merged(self, *notes):
        return merge_manual(KB, load_manual_notes(doc(*[n["note"] for n in notes])))

    def test_manual_risk_is_owner_stated_never_fact(self):
        n = note()
        v = build_value_add(DEERE, dc.AS_OF, cfg=CFG, kb=self.merged(n))
        recall, mine = v["block"]["model_specific_risks"]                # the X380 is ALSO on the Kawasaki recall list
        self.assertEqual((recall["basis"], recall["provenance_id"]), ("FACT", v["provenance"]["provenance_id"]))
        self.assertEqual(mine["basis"], "RECOMMENDATION")
        self.assertEqual(mine["provenance_id"], n["note"]["provenance_id"])           # Michael's own human provenance
        self.assertIn("michael's own note (own experience), entered 2026-10-07".lower(), mine["source"].lower())
        self.assertIn("Michael's note; the model is taken from the listing text", mine["risk"])
        self.assertIn(STATEMENT, mine["risk"])
        self.assertEqual(mine["kind"], "known_weakness")
        self.assertIn(n["note"]["provenance_id"], v["provenance"]["derived_from"])
        self.assertIn("Price a replacement bracket into the parts budget.", v["block"]["plan"]["value"])

    def test_sourced_entries_come_first_and_are_untouched(self):
        m = self.merged(note())
        self.assertEqual(m["entries"][:len(KB["entries"])], KB["entries"])
        self.assertEqual(m["entries"][-1]["origin"], "manual")
        self.assertEqual(m["kb_version"], KB["kb_version"] + "+manual")
        self.assertNotEqual(m["_hash"], KB["_hash"])

    def test_note_only_applies_to_its_make_and_model(self):
        v = build_value_add(DEERE, dc.AS_OF, cfg=CFG, kb=self.merged(note(models=["X390"], statement=STATEMENT.replace("X380", "X390"))))
        self.assertEqual(len(v["block"]["model_specific_risks"]), 1)                 # only the sourced recall entry
        other, _, _ = dc.zero_turn_mower()
        self.assertNotIn("manual", " ".join(build_value_add(other, dc.AS_OF, cfg=CFG, kb=self.merged(note()))["matched"]))

    def test_a_retracted_note_is_never_linted(self):
        """A retraction row copies the retracted note's content, so linting it would make retraction useless (found in the D-17 review)."""
        n = note()["note"]
        n.update({"statement": "Check the compression first.", "retracted": True})
        self.assertEqual(load_manual_notes(doc(n)), [])
        from mbos_economics.valueadd import load_manual_notes_lenient
        self.assertEqual(load_manual_notes_lenient(doc(n)), ([], []))

    def test_lenient_loader_skips_bad_notes_and_reports_them(self):
        from mbos_economics.valueadd import load_manual_notes_lenient
        good, bad = note()["note"], note(models=["X350"])["note"]
        bad["statement"] = "Look for leaks."
        live, problems = load_manual_notes_lenient(doc(good, bad))
        self.assertEqual([n["note_id"] for n in live], [good["note_id"]])
        self.assertEqual([p["note_id"] for p in problems], [bad["note_id"]])
        with self.assertRaises(NoteError):
            load_manual_notes(doc(good, bad))                               # strict stays strict

    def test_edit_links_through_supersedes(self):
        a = note()["note"]
        e = note(statement=STATEMENT + " Seen twice.", entered_at="2026-10-08T20:00:00Z", supersedes=a["note_id"])["note"]
        self.assertEqual(e["supersedes"], a["note_id"])
        self.assertNotEqual(e["note_id"], a["note_id"])
        with self.assertRaises(NoteError):
            note(supersedes="not-a-note-id")

    def test_numeric_model_numbers_are_allowed_in_a_human_note_but_not_in_the_shipped_kb(self):
        """Asymmetry by design: agency-converted entries must not match on a wattage or year (false safety claims), but a
        person writing 'John Deere 4020' means a real numeric model and owns the statement (shown as RECOMMENDATION)."""
        n = note(makes=["john deere"], models=["4020"], category="mower", statement="4020 power-shift clutch pack wears; budget a rebuild.")["note"]
        item = {"category": "mower", "normalized": {"title": "John Deere 4020 tractor"}}
        self.assertEqual(len(match_entries(item, merge_manual(KB, load_manual_notes(doc(n))))), 1)
        other = {"category": "mower", "normalized": {"title": "Ford 4020 tractor"}}                     # make still required
        self.assertEqual(match_entries(other, merge_manual(KB, load_manual_notes(doc(n)))), [])

    def test_retracted_notes_are_ignored(self):
        n = note()["note"]
        n["retracted"] = True
        self.assertEqual(load_manual_notes(doc(n)), [])

    def test_merge_does_not_mutate_the_shipped_kb(self):
        before = json.dumps(KB, sort_keys=True)
        self.merged(note())
        self.assertEqual(json.dumps(KB, sort_keys=True), before)


class TestNothingUnsourcedShips(unittest.TestCase):
    def test_packaged_kb_has_no_manual_entries_and_every_entry_is_sourced(self):
        raw = json.loads((CONFIG_DIR / "value_add_kb.json").read_text())
        for e in raw["entries"]:
            self.assertNotEqual(e.get("origin"), "manual", e["id"])
            self.assertTrue(e["source"]["url"].startswith("https://"), e["id"])
        self.assertFalse(any(CONFIG_DIR.glob("*note*")), "no notes file belongs in the package config")

    def test_load_kb_refuses_a_manual_entry_in_a_kb_file(self):
        bad = {k: v for k, v in copy.deepcopy(KB).items() if k != "_hash"}
        merged = merge_manual(KB, load_manual_notes(doc(note()["note"])))
        bad["entries"] = merged["entries"]
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "kb.json"
            p.write_text(json.dumps(bad))
            with self.assertRaises(ValueError) as cm:
                load_kb(p)
        self.assertIn("manual notes never ship in the KB file", str(cm.exception))

    def test_a_manual_risk_always_carries_provenance(self):
        v = build_value_add(DEERE, dc.AS_OF, cfg=CFG, kb=merge_manual(KB, load_manual_notes(doc(note()["note"]))))
        for r in v["block"]["model_specific_risks"]:
            self.assertTrue(r["source"] and r["provenance_id"], r)
            if r["basis"] != "FACT":
                self.assertEqual(r["basis"], "RECOMMENDATION")


class TestCli(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "mbos_economics", *args], capture_output=True, text=True,
                              env={"PYTHONPATH": str(HERE.parent / "src")})

    def test_new_prints_note_and_provenance_and_writes_nothing(self):
        before = {str(p): p.stat().st_mtime_ns for p in CONFIG_DIR.rglob("*.json")}
        r = self.run_cli("note", "new", "--category", "mower", "--make", "john deere", "--model", "X380", "--kind",
                         "known_weakness", "--statement", STATEMENT, "--entered-by", "michael", "--entered-at", AT,
                         "--basis-of-knowledge", "own experience")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["note"]["provenance_id"], out["provenance"]["provenance_id"])
        self.assertEqual({str(p): p.stat().st_mtime_ns for p in CONFIG_DIR.rglob("*.json")}, before)

    def test_refusal_exit_code(self):
        r = self.run_cli("note", "new", "--category", "mower", "--make", "x", "--model", "y", "--kind", "known_weakness",
                         "--statement", "Check the compression.", "--entered-by", "michael", "--entered-at", AT,
                         "--basis-of-knowledge", "own experience")
        self.assertEqual(r.returncode, 2)
        self.assertIn("elementary advice", r.stdout)

    def test_check_validates_a_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(doc(note()["note"]), f)
        try:
            ok = self.run_cli("note", "check", f.name)
            self.assertEqual(ok.returncode, 0)
            self.assertEqual(json.loads(ok.stdout)["active_notes"], 1)
        finally:
            os.unlink(f.name)


try:
    from mbos.card import build_card, validate_card
    _card_ok = bool(os.environ.get("MBOS_CONTRACTS_DIR"))
except ImportError:  # pragma: no cover
    _card_ok = False


@unittest.skipUnless(_card_ok, "needs agent-01 mbos.card installed and MBOS_CONTRACTS_DIR=<archive>/docs/research/contracts")
class TestCardIntegration(unittest.TestCase):
    def test_validate_card_clean_with_a_manual_note(self):
        v = build_value_add(DEERE, dc.AS_OF, cfg=CFG, kb=merge_manual(KB, load_manual_notes(doc(note()["note"]))))
        card = build_card(DEERE, [], [], {"value_add": v["block"]}, profile=dc.PROFILE,
                          now=datetime(2026, 10, 7, 20, tzinfo=timezone.utc))
        self.assertEqual(validate_card(card), [])
        risks = card["value_add_plan"]["model_specific_risks"]
        self.assertEqual([r["basis"] for r in risks], ["FACT", "RECOMMENDATION"])
        self.assertTrue(risks[1]["provenance_id"].startswith("prov_"))


if __name__ == "__main__":
    unittest.main()
