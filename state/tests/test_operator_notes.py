"""D-17: the operator-note store — Michael's mechanic knowledge, append-only, receipted, human-only."""

import json
import os
import re
import sys

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from mbos_state.ids import ulid
from conftest import key

HUMAN = {"type": "human", "id": "michael"}
T0 = "2026-10-07T16:00:00.000000Z"
T1 = "2026-10-08T09:30:00.000000Z"


def bundle(*, entered_by="michael", entered_at=T0, category="mower", makes=("john deere",), models=("X380",),
           kind="known_weakness", statement="X380 deck spindle bearings fail by ~300h; the housing wears too.",
           supersedes=None, **over):
    """Same shape as mbos_economics.new_manual_note(): {"note", "provenance"} with a human provenance record."""
    nid, pid = f"mn_{ulid()}", f"prov_{ulid()}"
    note = {"note_id": nid, "category": category, "match": [{"makes": list(makes), "models": list(models)}],
            "kind": kind, "statement": statement, "entered_by": entered_by, "entered_at": entered_at,
            "basis_of_knowledge": "own experience, 6 yrs of mower repair", "provenance_id": pid, **over}
    if supersedes:
        note["supersedes"] = supersedes
    prov = {"provenance_id": pid, "created_at": entered_at, "actor_type": "human", "human_actor": entered_by,
            "basis": "RECOMMENDATION", "tool_name": "mbos.manual_note", "tool_version": "1",
            "inputs_used": [{"ref": nid, "hash": "sha256:" + "0" * 64}]}
    return {"note": note, "provenance": prov}


@pytest.fixture
def ui(db):
    return db.store("approver")            # the Operator UI backend = the human channel


def test_record_is_atomic_receipted_and_cites_human_provenance(db, ui):
    b = bundle()
    nid = ui.record_operator_note(b)
    assert nid == b["note"]["note_id"]
    r = ui.conn.execute("""SELECT type, entity_type, entity_id, actor, provenance_ids, effect FROM mbos.receipts
                           WHERE entity_id = %s""", (nid,)).fetchall()
    assert r == [("LESSON_RECORDED", "operator_note", nid, HUMAN, [b["provenance"]["provenance_id"]], "create")]
    pv = ui.conn.execute("SELECT actor_type, human_actor, basis, tool_name FROM mbos.provenance WHERE provenance_id=%s",
                         (b["provenance"]["provenance_id"],)).fetchone()
    assert pv == ("human", "michael", "RECOMMENDATION", "mbos.manual_note")
    assert ui.conn.execute("SELECT basis FROM mbos.operator_notes").fetchone()[0] == "RECOMMENDATION"
    assert ui.verify_chain().ok
    assert ui.record_operator_note(b) == nid                                  # replay: no second row / receipt
    assert ui.conn.execute("SELECT count(*) FROM mbos.operator_notes").fetchone()[0] == 1
    assert ui.conn.execute("SELECT count(*) FROM mbos.receipts WHERE entity_id=%s", (nid,)).fetchone()[0] == 1


def test_failure_leaves_neither_note_nor_provenance_nor_receipt(db, ui):
    before = ui.conn.execute("SELECT (SELECT count(*) FROM mbos.provenance), (SELECT count(*) FROM mbos.receipts)").fetchone()
    bad = bundle(match=[{"makes": ["john deere"], "models": []}])                # a note must name a model
    with pytest.raises(errors.CheckViolation):
        ui.record_operator_note(bad)
    assert ui.conn.execute("SELECT (SELECT count(*) FROM mbos.provenance), (SELECT count(*) FROM mbos.receipts)").fetchone() == before


@pytest.mark.parametrize("over", [
    {"match": []}, {"match": [{"makes": ["x"]}]}, {"match": [{"makes": [], "models": ["y"]}]},
    {"match": [{"makes": ["a"], "models": ["b"]}, {"makes": ["c"], "models": [""]}]}, {"match": "john deere X380"},
    {"category": "sedan"}, {"kind": "opinion"}, {"statement": ""}, {"statement": "x" * 601}, {"plan_hint": "y" * 601},
    {"basis_of_knowledge": " "}, {"reference_url": "http://insecure.example"}, {"reference_url": "https://"},
    {"basis": "FACT"}, {"note_id": "mn_short"}, {"note_id": "nt_" + "0" * 26}])
def test_db_checks_reject_bad_notes(db, ui, over):
    with pytest.raises(psycopg.Error) as ei:
        ui.record_operator_note(bundle(**over))
    assert isinstance(ei.value, (errors.CheckViolation, psycopg.errors.InvalidTextRepresentation)), ei.value
    assert ui.conn.execute("SELECT count(*) FROM mbos.operator_notes").fetchone()[0] == 0


def test_boundary_values_accepted(db, ui):
    ui.record_operator_note(bundle(statement="s" * 600, plan_hint="p" * 600, reference_url="https://manual.example/p34",
                                   review_after="2027-01-01"))


def test_provenance_must_be_human_and_match_author(db, ui):
    b = bundle()
    b["provenance"].update(actor_type="agent", agent_name="agent-03-economics")           # agent-authored: refused
    with pytest.raises(psycopg.Error) as ei:
        ui.record_operator_note(b)
    assert ei.value.sqlstate == "MB002"
    b = bundle()
    b["provenance"]["human_actor"] = "someone-else"                                        # author mismatch
    with pytest.raises(psycopg.Error) as ei:
        ui.record_operator_note(b)
    assert ei.value.sqlstate == "MB002"
    b = bundle()
    b["note"]["provenance_id"] = "prov_" + "0" * 26                                        # not the bundle's record
    with pytest.raises(psycopg.Error) as ei:
        ui.record_operator_note(b)
    assert ei.value.sqlstate == "MB002"
    b = bundle()
    b["provenance"]["basis"] = "FACT"                                                      # owner-stated, never FACT
    with pytest.raises(psycopg.Error):
        ui.record_operator_note(b)


def test_note_row_without_receipt_cannot_commit(db):
    owner = db.connect("owner")
    b = bundle()
    pid = owner.execute("SELECT mbos.record_provenance(%s)", (Jsonb(b["provenance"]),)).fetchone()[0]
    n = b["note"]
    with pytest.raises(psycopg.Error) as ei:
        owner.execute("""INSERT INTO mbos.operator_notes (note_id, category, match, kind, statement, entered_by, entered_at,
                         basis_of_knowledge, provenance_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                      (n["note_id"], n["category"], Jsonb(n["match"]), n["kind"], n["statement"], n["entered_by"],
                       n["entered_at"], n["basis_of_knowledge"], pid))
    assert ei.value.sqlstate == "MB003"


def test_insert_only_and_role_boundaries(db, ui):
    nid = ui.record_operator_note(bundle())
    for role in ("owner", "superuser"):
        for sql in ("UPDATE mbos.operator_notes SET statement='x'", "DELETE FROM mbos.operator_notes",
                    "TRUNCATE mbos.operator_notes"):
            with pytest.raises(psycopg.Error) as ei:
                db.connect(role).execute(sql)
            assert ei.value.sqlstate == "MB001"
    for role in ("reader", "agent_write", "gateway", "policy_admin", "outbox_relay"):   # agent roles read, never write
        c = db.connect(role)
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT mbos.record_operator_note(%s)", (Jsonb(bundle()),))
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("INSERT INTO mbos.operator_notes (note_id) VALUES ('mn_x')")
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT mbos.retract_operator_note(%s, 'michael', now(), 'x')", (nid,))
    for role in ("reader", "agent_write", "gateway", "approver"):
        assert db.connect(role).execute("SELECT count(*) FROM mbos.operator_notes").fetchone()[0] == 1
    assert db.connect("reader").execute("SELECT jsonb_array_length(mbos.operator_notes_document()->'notes')").fetchone()[0] == 1


def test_edit_and_retract_fold_into_one_current_note(db, ui):
    v1 = bundle(statement="Deck spindle bearings fail early.")
    id1 = ui.record_operator_note(v1)
    v2 = bundle(entered_at=T1, supersedes=id1, statement="Deck spindle bearings fail by ~300h; replace the housing too.")
    id2 = ui.record_operator_note(v2)
    other = ui.record_operator_note(bundle(category="generator", makes=("honda",), models=("EU7000",),
                                           kind="expensive_part", statement="EU7000 inverter board is the costly part."))
    doc = ui.operator_notes_document()
    byid = {n["note_id"]: n for n in doc["notes"]}
    assert set(byid) == {id2, other} and "retracted" not in byid[id2]                 # v1 is folded away
    assert byid[id2]["statement"].endswith("housing too.")
    with pytest.raises(psycopg.Error):                                                  # a chain cannot fork
        ui.record_operator_note(bundle(entered_at=T1, supersedes=id1))
    rid = ui.retract_operator_note(id1, "michael", "2026-10-09T08:00:00Z", "bearing part was redesigned in 2025")
    assert ui.retract_operator_note(id2, "michael", "2026-10-09T08:00:00Z", "again") == rid      # already retracted
    doc = ui.operator_notes_document()
    byid = {n["note_id"]: n for n in doc["notes"]}
    assert byid[rid]["retracted"] is True and byid[rid]["statement"] == v2["note"]["statement"]   # content kept, valid
    assert len(doc["notes"]) == 2 and len(ui.operator_notes_document(False)["notes"]) == 1
    with pytest.raises(psycopg.Error) as ei:                                            # no edits to a retracted note
        ui.record_operator_note(bundle(entered_at="2026-10-10T08:00:00Z", supersedes=rid))
    assert ei.value.sqlstate == "MB004"
    with pytest.raises(psycopg.Error) as ei:
        ui.retract_operator_note(id1, "michael", T1, "  ")
    assert ei.value.sqlstate == "MB004"
    rc = ui.conn.execute("""SELECT count(*), bool_and(type='LESSON_RECORDED'), bool_and(entity_type='operator_note')
                            FROM mbos.receipts WHERE entity_type='operator_note'""").fetchone()
    assert rc == (4, True, True)                                                         # v1, v2, other, retraction
    assert ui.verify_chain().ok


# -- the folded document is accepted by Agent 03's loader -----------------------------------------------------
NOTE_KEYS = {"note_id", "category", "match", "kind", "statement", "plan_hint", "entered_by", "entered_at",
             "basis_of_knowledge", "provenance_id", "reference_url", "review_after", "basis", "retracted"}


def mirror_problems(n):
    """The loader's published rules (§7), mirrored so the suite never depends on another branch."""
    p = [k for k in ("note_id", "category", "match", "kind", "statement", "entered_by", "entered_at",
                     "basis_of_knowledge", "provenance_id") if not n.get(k)]
    if not re.match(r"^prov_[0-9A-HJKMNP-TV-Z]{26}$", n.get("provenance_id", "")):
        p.append("provenance_id")
    if not re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?(Z|[+-]\d\d:\d\d)$", n.get("entered_at", "")):
        p.append("entered_at")
    if not (isinstance(n.get("match"), list) and n["match"] and all(g.get("makes") and g.get("models") for g in n["match"])):
        p.append("match")
    if n.get("basis") not in (None, "RECOMMENDATION") or set(n) - NOTE_KEYS or len(n.get("statement", "")) > 600:
        p.append("basis/keys/length")
    return p


def test_document_shape_matches_the_loader_contract(db, ui):
    a = ui.record_operator_note(bundle())
    ui.record_operator_note(bundle(entered_at=T1, supersedes=a, plan_hint="swap the housing", reference_url="https://m.example/34",
                                   review_after="2027-06-01"))
    c = ui.record_operator_note(bundle(category="trailer", makes=("big tex",), models=("14ET",), kind="resale_demand",
                                       statement="14ET dump trailers resell within a week in this market."))
    ui.retract_operator_note(c, "michael", "2026-10-09T08:00:00Z", "market changed")
    doc = ui.operator_notes_document()
    assert doc["notes_format"] == 1 and len(doc["notes"]) == 2
    assert [mirror_problems(n) for n in doc["notes"]] == [[], []]
    assert len({n["note_id"] for n in doc["notes"]}) == 2


@pytest.mark.skipif(not os.environ.get("MBOS_ECONOMICS_SRC"), reason="set MBOS_ECONOMICS_SRC to Agent 03's economics/src")
def test_view_document_passes_agent03_note_check(db, ui, tmp_path):
    """D-17 acceptance: `python -m mbos_economics note check FILE` exits 0 on the database-rendered document, and
    the loader returns the live (non-retracted) notes. Also round-trips notes built by the real new_manual_note()."""
    import subprocess
    sys.path.insert(0, os.environ["MBOS_ECONOMICS_SRC"])
    try:
        from mbos_economics.valueadd import load_manual_notes, new_manual_note
    finally:
        sys.path.pop(0)
    first = new_manual_note(category="mower", makes=["john deere"], models=["X380"], kind="known_weakness",
                            statement="X380 deck spindle bearings fail by ~300h; the housing wears too.",
                            entered_by="michael", entered_at=T0, basis_of_knowledge="own experience")
    second = new_manual_note(category="generator", makes=["honda"], models=["EU7000"], kind="expensive_part",
                             statement="EU7000 inverter board is the costly part; budget $400.", entered_by="michael",
                             entered_at=T1, basis_of_knowledge="service manual p.34",
                             reference_url="https://example.invalid/manual", plan_hint="price the board first")
    third = new_manual_note(category="tool", makes=["milwaukee"], models=["2767-20"], kind="parts_availability",
                            statement="2767-20 anvils are backordered; the whole tool is cheaper than the part.",
                            entered_by="michael", entered_at="2026-10-09T10:00:00Z", basis_of_knowledge="parts counter")
    for b in (first, second, third):
        ui.record_operator_note(b)
    ui.retract_operator_note(third["note"]["note_id"], "michael", "2026-10-10T08:00:00Z", "part is back in stock")
    f = tmp_path / "notes.json"
    f.write_text(json.dumps(ui.operator_notes_document(), indent=1))
    cp = subprocess.run([sys.executable, "-m", "mbos_economics", "note", "check", str(f)], capture_output=True, text=True,
                        env={**os.environ, "PYTHONPATH": os.environ["MBOS_ECONOMICS_SRC"]})
    assert cp.returncode == 0, cp.stdout + cp.stderr
    live = load_manual_notes(str(f))
    assert {n["note_id"] for n in live} == {first["note"]["note_id"], second["note"]["note_id"]}
