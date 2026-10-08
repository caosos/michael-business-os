"""D-30: Michael's typed inputs (scope overrides, quote) through the owner UI login; the workflow login cannot forge them."""

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import key, make_item, flip_doc
from test_human_only_owner_paths import real_dbos  # noqa: F401

AGENT = {"type": "agent", "id": "agent-03-economics"}
HUMAN = {"type": "human", "id": "michael"}


def _human_prov(conn):
    return conn.execute("""SELECT mbos.record_provenance('{"actor_type":"human","human_actor":"michael","basis":"FACT",
                           "tool_name":"mbos.human_input","tool_version":"0.1.0"}')""").fetchone()[0]


def _input(conn, item_id, pid, kind, k, value, actor=HUMAN, idem=None):
    return conn.execute("SELECT mbos.record_human_input(%s,%s,%s,%s,'Michael said so',%s,%s,%s)",
                        (item_id, kind, k, Jsonb(value), Jsonb(actor), [pid], idem or key("hi"))).fetchone()[0]


def test_owner_ui_login_records_both_kinds_receipted_and_idempotent(db):
    item_id, _ = make_item(db.store(), "RESEARCHING")
    ui = db.store("approver")
    assert ui.conn.execute("SELECT session_user").fetchone()[0] == "mbos_operator_ui"
    hp = _human_prov(ui.conn)
    k = key("hi")
    rid = _input(ui.conn, item_id, hp, "scope_override", "rehab.parts_cost", 120, idem=k)
    assert _input(ui.conn, item_id, hp, "scope_override", "rehab.parts_cost", 120, idem=k) == rid
    _input(ui.conn, item_id, hp, "scope_override", "job.required_skills", ["repair", "wiring"])
    _input(ui.conn, item_id, hp, "quote", "amount_usd", 250.5)
    research = db.connect("reader").execute("SELECT doc->'research' FROM mbos.items WHERE item_id=%s", (item_id,)).fetchone()[0]
    by = {r["field"]: r for r in research if r["field"].startswith(("scope_override:", "quote:"))}
    assert by["scope_override:rehab.parts_cost"] == {"finding": "Michael said so", "field": "scope_override:rehab.parts_cost", "value": 120,
                                                     "basis": "INFER", "source_uri": "human:michael", "provenance_id": hp, "entered_by": "michael"}
    assert by["scope_override:job.required_skills"]["value"] == ["repair", "wiring"]
    assert by["quote:amount_usd"]["value"] == 250.5 and by["quote:amount_usd"]["basis"] == "FACT"
    r = ui.conn.execute("SELECT type, actor->>'type', actor->>'id', item_id FROM mbos.receipts WHERE receipt_id=%s", (rid,)).fetchone()
    assert r == ("ITEM_STATE_CHANGED", "human", "michael", item_id)
    assert ui.verify_chain().ok


@pytest.mark.parametrize("actor", [{"type": "agent", "id": "agent-x"}, {"type": "human"}, {"type": "system", "id": "michael"}])
def test_ui_login_refuses_non_human_actor(db, actor):
    item_id, _ = make_item(db.store(), "RESEARCHING")
    ui = db.store("approver")
    with pytest.raises(errors.InsufficientPrivilege):
        _input(ui.conn, item_id, _human_prov(ui.conn), "quote", "amount_usd", 100, actor=actor)


@pytest.mark.parametrize("kind,k,value", [
    ("quote", "amount_usd", 0), ("quote", "amount_usd", -5), ("quote", "amount_usd", 1e9), ("quote", "amount_usd", "100"),
    ("quote", "other", 100), ("scope_override", "rehab.labor_hours", -1), ("scope_override", "rehab.labor_hours", 1e12),
    ("scope_override", "rehab.labor_hours", True), ("scope_override", "rehab.bogus", 1), ("scope_override", "job.parts_cost", 1),
    ("scope_override", "job.required_skills", []), ("scope_override", "job.required_skills", [""]), ("scope_override", "rehab.required_skills", 3),
    ("other", "x", 1)])
def test_bad_shape_refused(db, kind, k, value):
    item_id, _ = make_item(db.store(), "RESEARCHING")
    ui = db.store("approver")
    with pytest.raises(psycopg.DatabaseError, match="mbos:"):
        _input(ui.conn, item_id, _human_prov(ui.conn), kind, k, value)


def test_needs_human_provenance_for_that_human(db):
    item_id, pid = make_item(db.store(), "RESEARCHING")
    ui = db.store("approver")
    with pytest.raises(psycopg.DatabaseError, match="human provenance"):
        _input(ui.conn, item_id, pid, "quote", "amount_usd", 100)


def test_real_mbos_dbos_refused_and_cannot_forge_entries(real_dbos):
    p, pid = real_dbos
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:
        hp = _human_prov(c)
        doc = flip_doc()
        doc["sources"][0]["provenance_id"] = pid
        item_id = c.execute("SELECT mbos.create_item(%s,%s,'x',%s,%s)", (Jsonb(doc), Jsonb(AGENT), [pid], key())).fetchone()[0]
        with pytest.raises(errors.InsufficientPrivilege):
            _input(c, item_id, hp, "quote", "amount_usd", 100)
        for fld in ("scope_override:rehab.parts_cost", "quote:amount_usd", "attestation:x"):
            entry = {"finding": "forged", "field": fld, "value": 1, "basis": "FACT", "source_uri": "human:michael",
                     "provenance_id": hp, "entered_by": "michael"}
            with pytest.raises(errors.InsufficientPrivilege):
                c.execute("SELECT mbos.append_item_research(%s,%s,%s,'x',%s,%s)", (item_id, Jsonb([entry]), Jsonb(AGENT), [hp], key()))
            with pytest.raises(errors.InsufficientPrivilege):
                c.execute("SELECT mbos.update_item_doc(%s,%s,'ITEM_STATE_CHANGED',%s,'x',%s,%s)",
                          (item_id, Jsonb({"research": [entry]}), Jsonb(AGENT), [hp], key()))
        ok = {"finding": "enrich", "field": "card.comps", "basis": "FACT", "source_uri": "human:michael", "provenance_id": hp}
        c.execute("SELECT mbos.append_item_research(%s,%s,%s,'x',%s,%s)", (item_id, Jsonb([ok]), Jsonb(AGENT), [hp], key()))
