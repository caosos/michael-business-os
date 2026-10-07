"""A2 — UPDATE or DELETE on receipts, approvals, provenance (and outcomes) is rejected by a trigger.
Mock limitation: SQLite has no roles; this proves the trigger fires for every connection, including a
second independent one. The `agent_write` role check must be re-run against Agent 04's Postgres."""
import json
import sqlite3

import pytest

TABLES = {"receipts": "seq", "approvals": "approval_id", "provenance": "provenance_id", "outcomes": "outcome_id"}


def _rows(conn, table):
    return conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()


@pytest.mark.parametrize("table", sorted(TABLES))
def test_update_and_delete_rejected(ran, table):
    conn = ran.store.conn
    before = _rows(conn, table)
    assert before, f"{table} must hold rows for this test to mean anything"
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute(f"UPDATE {table} SET doc = '{{}}'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        conn.execute(f"DELETE FROM {table}")
    assert _rows(conn, table) == before


@pytest.mark.parametrize("table", sorted(TABLES))
def test_rejected_from_an_independent_connection(ran, table):
    other = sqlite3.connect(ran.store.path)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            other.execute(f"DELETE FROM {table}")
    finally:
        other.close()


def test_insert_or_replace_cannot_overwrite_a_receipt(ran):
    """REPLACE deletes the conflicting row internally — a classic way around DELETE triggers."""
    conn = ran.store.conn
    seq, rid, key, typ, doc = conn.execute(
        "SELECT seq, receipt_id, idempotency_key, type, doc FROM receipts WHERE seq=1").fetchone()
    forged = json.loads(doc)
    forged["intent"] = "rewritten history"
    with pytest.raises(sqlite3.DatabaseError):
        conn.execute("INSERT OR REPLACE INTO receipts VALUES (?,?,?,?,?,?,?,?,?)",
                     (seq, rid, key, typ, None, None, json.dumps(forged), None, "x"))
    assert json.loads(conn.execute("SELECT doc FROM receipts WHERE seq=1").fetchone()[0])["intent"] != "rewritten history"
    assert ran.store.verify_chain().ok


def test_duplicate_idempotency_key_rejected(ran):
    r = ran.store.receipts()[-1]
    with pytest.raises(sqlite3.IntegrityError):
        with ran.store.tx() as t:
            t.receipt(type="ITEM_STATE_CHANGED", actor={"type": "system", "id": "qa"}, intent="dup",
                      provenance_ids=r["provenance_ids"], idempotency_key=r["idempotency_key"])
