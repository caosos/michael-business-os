"""D-29: Michael's attestation through the owner UI login; the workflow login cannot call it or forge the entry."""

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import key, make_item
from test_human_only_owner_paths import real_dbos  # noqa: F401

AGENT = {"type": "agent", "id": "agent-03-economics"}
HUMAN = {"type": "human", "id": "michael"}


def _human_prov(conn):
    return conn.execute("""SELECT mbos.record_provenance('{"actor_type":"human","human_actor":"michael","basis":"FACT",
                           "tool_name":"mbos.attestation","tool_version":"0.1.0"}')""").fetchone()[0]


def _attest(conn, item_id, pid, k="title_in_hand", note="I saw the title", actor=HUMAN, idem=None):
    return conn.execute("SELECT mbos.record_attestation(%s,%s,%s,%s,%s,%s)",
                        (item_id, k, note, Jsonb(actor), [pid], idem or key("att"))).fetchone()[0]


def test_owner_ui_login_records_receipted_human_attestation_visible_to_lane_c(db):
    item_id, _ = make_item(db.store(), "RESEARCHING")
    ui = db.store("approver")
    assert ui.conn.execute("SELECT session_user").fetchone()[0] == "mbos_operator_ui"
    hp = _human_prov(ui.conn)
    k = key("att")
    rid = _attest(ui.conn, item_id, hp, idem=k)
    assert _attest(ui.conn, item_id, hp, idem=k) == rid                       # idempotent replay
    research = db.connect("reader").execute("SELECT doc->'research' FROM mbos.items WHERE item_id=%s", (item_id,)).fetchone()[0]
    mine = [r for r in research if r["field"] == "attestation:title_in_hand"]
    assert mine == [{"finding": "I saw the title", "field": "attestation:title_in_hand", "basis": "FACT",
                     "source_uri": "human:michael", "provenance_id": hp}]
    r = ui.conn.execute("SELECT type, actor->>'type', actor->>'id', item_id FROM mbos.receipts WHERE receipt_id=%s", (rid,)).fetchone()
    assert r == ("ITEM_STATE_CHANGED", "human", "michael", item_id)
    assert ui.verify_chain().ok


@pytest.mark.parametrize("actor", [{"type": "agent", "id": "agent-x"}, {"type": "human"}, {"type": "human", "id": " "}, {"type": "system", "id": "michael"}])
def test_ui_login_refuses_non_human_actor(db, actor):
    item_id, _ = make_item(db.store(), "RESEARCHING")
    ui = db.store("approver")
    with pytest.raises(errors.InsufficientPrivilege):
        _attest(ui.conn, item_id, _human_prov(ui.conn), actor=actor)


def test_ui_login_needs_human_provenance_for_that_human(db):
    item_id, pid = make_item(db.store(), "RESEARCHING")                       # pid is an external source record
    ui = db.store("approver")
    with pytest.raises(psycopg.DatabaseError, match="human provenance"):
        _attest(ui.conn, item_id, pid)


def test_real_mbos_dbos_refused_and_cannot_forge_attestation_entry(real_dbos):
    p, pid = real_dbos
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:
        hp = _human_prov(c)
        item_id = c.execute("SELECT item_id FROM mbos.items LIMIT 1").fetchone()
        assert item_id is None                                               # fresh cluster: seed one below
    from conftest import flip_doc
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:
        doc = flip_doc()
        doc["sources"][0]["provenance_id"] = pid
        item_id = c.execute("SELECT mbos.create_item(%s,%s,'x',%s,%s)", (Jsonb(doc), Jsonb(AGENT), [pid], key())).fetchone()[0]
        with pytest.raises(errors.InsufficientPrivilege):
            _attest(c, item_id, hp)
        entry = {"finding": "forged", "field": "attestation:title_in_hand", "basis": "FACT", "source_uri": "human:michael", "provenance_id": hp}
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT mbos.append_item_research(%s,%s,%s,'x',%s,%s)", (item_id, Jsonb([entry]), Jsonb(AGENT), [hp], key()))
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT mbos.update_item_doc(%s,%s,'ITEM_STATE_CHANGED',%s,'x',%s,%s)",
                      (item_id, Jsonb({"research": [entry]}), Jsonb(AGENT), [hp], key()))
        ok = {**entry, "field": "card.comps", "finding": "lane enrichment"}      # ordinary lane enrichment still works
        c.execute("SELECT mbos.append_item_research(%s,%s,%s,'x',%s,%s)", (item_id, Jsonb([ok]), Jsonb(AGENT), [hp], key()))
