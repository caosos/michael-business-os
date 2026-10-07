"""D-17 acceptance (Agent 03's review of Agent 04's operator-note store, migration 0016).

Runs the REAL library (`new_manual_note`, `load_manual_notes`, `note check`, `build_value_add`) against a REAL lane-D
database built from Agent 04's migrations in a throwaway cluster, connecting AS each role. Skips cleanly unless the
lane-D environment is available (see lane_d.available(): MBOS_LANE_D_STATE_DIR -> Agent 04's state/ directory).
"""

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import deal_cases as dc
import lane_d
from helpers import CFG, HERE

from mbos_economics.valueadd import (NoteError, build_value_add, load_kb, load_manual_notes, load_manual_notes_lenient,
                                     merge_manual, new_manual_note)

_why = lane_d.available()
AT = "2026-10-07T20:00:00Z"
AT2 = "2026-10-08T09:00:00Z"
AT3 = "2026-10-09T09:00:00Z"
S1 = "X380 hydro drive belt idler bracket cracks at the weld; budget a bracket before it strands the unit."
S2 = "X380 hydro drive belt idler bracket cracks at the weld, usually by 400 h; the frame tab behind it wears too."


def as_role(dsn: str, login: str) -> str:
    return dsn.replace("user=postgres", f"user={login}")


def mk(**over):
    kw = dict(category="mower", makes=["john deere"], models=["X380"], kind="known_weakness", statement=S1,
              entered_by="michael", entered_at=AT, basis_of_knowledge="own experience",
              plan_hint="Price a replacement bracket into the parts budget.")
    kw.update(over)
    return new_manual_note(**kw)


@unittest.skipIf(_why is not None, f"lane-D environment unavailable: {_why}")
class TestOperatorNoteStore(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = lane_d.cluster()
        cls.dsn = cls._ctx.__enter__()
        import psycopg
        cls.psycopg = psycopg
        cls.ui = as_role(cls.dsn, "mbos_operator_ui")

    @classmethod
    def tearDownClass(cls):
        cls._ctx.__exit__(None, None, None)

    # -- helpers ---------------------------------------------------------------------------------------
    def record(self, dsn, bundle):
        with self.psycopg.connect(dsn) as c:
            return c.execute("SELECT mbos.record_operator_note(%s::jsonb)", (json.dumps(bundle),)).fetchone()[0]

    def document(self):
        with self.psycopg.connect(as_role(self.dsn, "mbos_reader")) as c:
            d = c.execute("SELECT mbos.operator_notes_document()").fetchone()[0]
        return d

    def refused(self, dsn, bundle, *fragments, exc=None):
        with self.assertRaises(exc or self.psycopg.Error) as cm:
            self.record(dsn, bundle)
        for f in fragments:
            self.assertIn(f, str(cm.exception))

    # -- the happy path: entry, edit, retraction, fold, our loader --------------------------------------
    def test_01_round_trip_edit_retract_fold_and_our_loader(self):
        a = mk()
        b = mk(makes=["honda"], models=["GX390"], category="mechanical_equipment",
               statement="GX390 on the Husqvarna saws: the governor spring sags after hard use, so the rpm hunts under load.")
        self.assertEqual(self.record(self.ui, a), a["note"]["note_id"])
        self.assertEqual(self.record(self.ui, b), b["note"]["note_id"])
        a2 = mk(statement=S2, entered_at=AT2, supersedes=a["note"]["note_id"])            # an EDIT of a
        self.assertEqual(self.record(self.ui, a2), a2["note"]["note_id"])
        with self.psycopg.connect(self.ui) as c:                                          # a RETRACTION of b
            rid = c.execute("SELECT mbos.retract_operator_note(%s, 'michael', %s::timestamptz, %s)",
                            (b["note"]["note_id"], AT3, "sold the saw; the note was about a single unit")).fetchone()[0]
        doc = self.document()
        by_id = {n["note_id"]: n for n in doc["notes"]}
        self.assertNotIn(a["note"]["note_id"], by_id)                                      # superseded rows fold away
        self.assertEqual(by_id[a2["note"]["note_id"]]["statement"], S2)
        self.assertTrue(by_id[rid]["retracted"])
        # OUR real loader accepts the database-rendered document and returns exactly the live notes
        live = load_manual_notes(doc)
        self.assertEqual([n["note_id"] for n in live], [a2["note"]["note_id"]])
        # and so does the real CLI (the exit code Agent 01 will gate on)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(doc, f)
        try:
            r = subprocess.run([sys.executable, "-m", "mbos_economics", "note", "check", f.name], capture_output=True, text=True,
                               env={"PYTHONPATH": str(HERE.parent / "src")})
            self.assertEqual((r.returncode, json.loads(r.stdout)["active_notes"]), (0, 1), r.stdout + r.stderr)
        finally:
            os.unlink(f.name)

    def test_02_receipts_provenance_and_chain(self):
        a = mk(models=["X390"], statement=S1.replace("X380", "X390"))
        self.record(self.ui, a)
        nid, pid = a["note"]["note_id"], a["provenance"]["provenance_id"]
        with self.psycopg.connect(self.dsn) as c:
            rc = c.execute("SELECT type, entity_type, provenance_ids, (actor->>'type'), (actor->>'id') FROM mbos.receipts "
                           "WHERE entity_id = %s", (nid,)).fetchall()
            pv = c.execute("SELECT actor_type, human_actor, basis, tool_name FROM mbos.provenance WHERE provenance_id = %s", (pid,)).fetchone()
            ok = c.execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]
        self.assertEqual(rc, [("LESSON_RECORDED", "operator_note", [pid], "human", "michael")])   # Option A, as ruled
        self.assertEqual(pv, ("human", "michael", "RECOMMENDATION", "mbos.manual_note"))
        self.assertTrue(ok)

    def test_03_end_to_end_value_add_cites_the_databases_human_provenance(self):
        a = mk(models=["X354"], statement=S1.replace("X380", "X354"))
        self.record(self.ui, a)
        item = dc.item(9, "mower", "John Deere X354 riding lawn tractor, deck work needed", 1100, 25)
        comps, prov = dc.comps_for("mower", "riding lawn tractor", [2400, 2500, 2600, 2700, 2800], 170)
        from mbos_economics.comps_feed import research_step
        scored = research_step(item, comps, prov, dc.AS_OF, profile=dc.PROFILE)["item"]
        live, problems = load_manual_notes_lenient(self.document())
        self.assertEqual(problems, [])
        v = build_value_add(scored, dc.AS_OF, cfg=CFG, kb=merge_manual(load_kb(), live))
        mine = [r for r in v["block"]["model_specific_risks"] if r["basis"] == "RECOMMENDATION"]
        self.assertEqual([r["provenance_id"] for r in mine], [a["provenance"]["provenance_id"]])
        self.assertIn(a["provenance"]["provenance_id"], v["provenance"]["derived_from"])

    # -- who may write ----------------------------------------------------------------------------------
    def test_04_only_the_human_channel_writes_llm_facing_roles_cannot(self):
        for login in ("mbos_reader", "mbos_state_mcp", "mbos_gateway", "mbos_policy"):
            n = mk(models=["Z" + login[-3:].upper() + "9"], statement="Z9 test note about a specific frame weld.")
            self.refused(as_role(self.dsn, login), n, "permission denied", exc=self.psycopg.errors.InsufficientPrivilege)
            with self.psycopg.connect(as_role(self.dsn, login)) as c, self.assertRaises(self.psycopg.errors.InsufficientPrivilege):
                c.execute("INSERT INTO mbos.operator_notes (note_id, category, match, kind, statement, entered_by, entered_at, "
                          "basis_of_knowledge, provenance_id) VALUES ('mn_01M4BZ73G0QZVNWMP24S2HM66V','mower','[]','failure_mode','x','m',now(),'x','prov_x')")

    def test_05_known_limitation_the_dbos_worker_login_inherits_approver(self):
        """DOCUMENTS current behaviour (roles.sql, by design): mbos_dbos is a member of `approver` so spine.decide can run
        in the workflow. It can therefore also insert notes. The control is that no LLM-facing process uses that login
        (R14); the database cannot tell a person from a workflow. If this ever changes, update the plan, not just this test."""
        n = mk(models=["X370"], statement="X370 deck lift link bushing wears oval early.")
        self.assertEqual(self.record(as_role(self.dsn, "mbos_dbos"), n), n["note"]["note_id"])

    # -- what the database itself refuses ---------------------------------------------------------------
    def test_06_database_refusals(self):
        base = mk(models=["X320"], statement="X320 steering shaft bushing wears at the frame tab.")
        agent_prov = copy.deepcopy(base)
        agent_prov["provenance"]["actor_type"] = "agent"
        self.refused(self.ui, agent_prov, "not a human RECOMMENDATION record")
        other_author = copy.deepcopy(base)
        other_author["note"]["entered_by"] = "intern"
        self.refused(self.ui, other_author, "does not match the provenance human_actor")
        fact = copy.deepcopy(base)
        fact["note"]["basis"] = "FACT"
        self.refused(self.ui, fact, "never FACT")
        nomodel = copy.deepcopy(base)
        nomodel["note"]["match"] = [{"makes": ["john deere"], "models": []}]
        self.refused(self.ui, nomodel, "operator_notes_match_check")
        mismatch = copy.deepcopy(base)
        mismatch["note"]["provenance_id"] = "prov_01M4BZ73G0QZVNWMP24S2HM66V"
        self.refused(self.ui, mismatch, "note.provenance_id must be the bundle")
        http = mk(models=["X321"], statement="X321 note.", reference_url="https://forum.example/x321")
        http["note"]["reference_url"] = "http://forum.example/x321"
        self.refused(self.ui, http, "reference_url")
        long = copy.deepcopy(base)
        long["note"]["statement"] = "X320 " * 130
        self.refused(self.ui, long, "statement")
        self.assertEqual(self.record(self.ui, base), base["note"]["note_id"])          # the unmodified bundle is fine
        self.assertEqual(self.record(self.ui, base), base["note"]["note_id"])          # and replay is idempotent
        reuse = mk(models=["X322"], statement="X322 note.")
        reuse["provenance"] = copy.deepcopy(base["provenance"])
        reuse["note"]["provenance_id"] = base["provenance"]["provenance_id"]
        self.refused(self.ui, reuse, "provenance_pkey")        # a provenance record can back only one note

    def test_07_append_only_and_chain_rules(self):
        a = mk(models=["X330"], statement="X330 hydro pump coupling strips its splines.")
        self.record(self.ui, a)
        with self.psycopg.connect(self.dsn) as c:                                     # even a superuser cannot rewrite history
            with self.assertRaises(self.psycopg.Error):
                c.execute("UPDATE mbos.operator_notes SET statement = 'rewritten' WHERE note_id = %s", (a["note"]["note_id"],))
        with self.psycopg.connect(self.dsn) as c:
            with self.assertRaises(self.psycopg.Error):
                c.execute("DELETE FROM mbos.operator_notes WHERE note_id = %s", (a["note"]["note_id"],))
        e1 = mk(models=["X330"], statement="X330 hydro pump coupling strips its splines; seen twice.", entered_at=AT2,
                supersedes=a["note"]["note_id"])
        self.record(self.ui, e1)
        fork = mk(models=["X330"], statement="X330 hydro pump coupling strips; a competing edit.", entered_at=AT3,
                  supersedes=a["note"]["note_id"])
        self.refused(self.ui, fork, "supersedes")                                     # a chain cannot fork
        back = mk(models=["X330"], statement="X330 backdated edit.", entered_at="2026-10-01T00:00:00Z",
                  supersedes=e1["note"]["note_id"])
        self.refused(self.ui, back, "cannot predate")

    # -- the review finding: the database does not lint, so the loader must survive a bad note ---------------
    def test_08_a_note_that_bypassed_the_lint_does_not_disable_the_others(self):
        good = mk(models=["X340"], statement="X340 mower deck lift shaft binds in its sleeve.")
        self.record(self.ui, good)
        sneaky = mk(models=["X341"], statement="X341 deck belt note.")                 # build valid, then alter text BEFORE insert
        sneaky["note"]["statement"] = "Check the compression first, then look for leaks."
        self.assertEqual(self.record(self.ui, sneaky), sneaky["note"]["note_id"])      # the DB accepts any text (lint is Python-side)
        doc = self.document()
        with self.assertRaises(NoteError) as cm:                                       # strict: the whole document is refused
            load_manual_notes(doc)
        self.assertIn("elementary advice", str(cm.exception))
        live, problems = load_manual_notes_lenient(doc)                                # lenient: the good notes survive
        ids = {n["note_id"] for n in live}
        self.assertIn(good["note"]["note_id"], ids)
        self.assertNotIn(sneaky["note"]["note_id"], ids)
        self.assertEqual([p["note_id"] for p in problems], [sneaky["note"]["note_id"]])
        # retract the offender (the supported fix); the strict document is clean again
        with self.psycopg.connect(self.ui) as c:
            c.execute("SELECT mbos.retract_operator_note(%s, 'michael', %s::timestamptz, 'bypassed the entry lint')",
                      (sneaky["note"]["note_id"], AT3))
        self.assertEqual(load_manual_notes_lenient(self.document())[1], [])


if __name__ == "__main__":
    unittest.main()
