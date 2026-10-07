"""A1: state change + receipt + outbox commit in ONE transaction — a failure leaves both or neither."""

import threading
import time

import psycopg
import pytest
from psycopg.types.json import Jsonb

from mbos_state.ids import new_id
from mbos_state.store import StateStore
from conftest import AGENT, key, make_item


def _counts(conn, item_id):
    return conn.execute(
        """SELECT (SELECT state FROM mbos.items WHERE item_id = %(i)s),
                  (SELECT count(*) FROM mbos.receipts WHERE item_id = %(i)s),
                  (SELECT count(*) FROM mbos.outbox WHERE aggregate_id = %(i)s)""", {"i": item_id}).fetchone()


def test_every_receipt_has_exactly_one_outbox_row(db):
    s = db.store()
    item_id, pid = make_item(s, "SCORED")
    state, n_receipts, n_outbox = _counts(s.conn, item_id)
    assert state == "SCORED" and n_receipts == n_outbox == 4  # create + 3 transitions
    orphan = s.conn.execute("""SELECT count(*) FROM mbos.receipts r
                               WHERE NOT EXISTS (SELECT 1 FROM mbos.outbox o WHERE o.receipt_id = r.receipt_id)""")
    assert orphan.fetchone()[0] == 0


def test_rollback_after_transition_leaves_neither(db):
    s = db.store()
    item_id, pid = make_item(s, "NORMALIZED")
    before = _counts(s.conn, item_id)
    with pytest.raises(RuntimeError):
        with s.transaction():
            s.transition_item(item_id, "RESEARCHING", AGENT, "start research", [pid], key())
            assert _counts(s.conn, item_id)[0] == "RESEARCHING"
            raise RuntimeError("fault injected between state change and commit")
    assert _counts(s.conn, item_id) == before


def test_receipt_failure_rolls_back_state_change(db):
    s = db.store()
    item_id, pid = make_item(s, "NORMALIZED")
    before = _counts(s.conn, item_id)
    with pytest.raises(psycopg.Error) as ei:
        s.transition_item(item_id, "RESEARCHING", AGENT, "bad provenance", [new_id("prov")], key())
    assert ei.value.sqlstate == "MB002"
    assert _counts(s.conn, item_id) == before


def test_state_change_without_receipt_cannot_commit(db):
    s = db.store("agent_write")
    item_id, pid = make_item(db.store(), "NORMALIZED")
    with pytest.raises(psycopg.Error) as ei:
        s.conn.execute("UPDATE mbos.items SET state = 'RESEARCHING' WHERE item_id = %s", (item_id,))
    assert ei.value.sqlstate == "MB003"
    assert _counts(s.conn, item_id)[0] == "NORMALIZED"


def test_receipt_for_other_item_does_not_satisfy_invariant(db):
    s = db.store()
    a, pid = make_item(s, "NORMALIZED")
    b, _ = make_item(s, "NORMALIZED")
    with pytest.raises(psycopg.Error) as ei:
        with s.transaction():
            s.conn.execute("UPDATE mbos.items SET state = 'RESEARCHING' WHERE item_id = %s", (a,))
            s.transition_item(b, "RESEARCHING", AGENT, "unrelated", [pid], key())
    assert ei.value.sqlstate == "MB003"
    assert _counts(s.conn, a)[0] == "NORMALIZED" and _counts(s.conn, b)[0] == "NORMALIZED"


def test_receipt_from_earlier_transaction_does_not_satisfy_invariant(db):
    s = db.store()
    item_id, pid = make_item(s, "NORMALIZED")   # earlier tx wrote receipts for this item
    with pytest.raises(psycopg.Error) as ei:
        s.conn.execute("UPDATE mbos.items SET doc = doc || '{\"x\":1}' WHERE item_id = %s", (item_id,))
    assert ei.value.sqlstate == "MB003"


def test_ledger_rows_need_their_receipt(db):
    s = db.store()
    item_id, pid = make_item(s)
    with pytest.raises(psycopg.Error) as ei:
        s.conn.execute("""INSERT INTO mbos.outcomes (item_id, observed_at, kind, provenance_ids)
                          VALUES (%s, now(), 'wasted_trip', ARRAY[%s])""", (item_id, pid))
    assert ei.value.sqlstate == "MB003"
    with pytest.raises(psycopg.Error) as ei:
        s.conn.execute("""INSERT INTO mbos.lessons (scope, statement, basis, provenance_ids)
                          VALUES ('ops', 'x', 'FACT', ARRAY[%s])""", (pid,))
    assert ei.value.sqlstate == "MB003"


def test_crash_mid_transaction_leaves_neither(db):
    """Kill the backend (simulated process crash) after the state change, before COMMIT."""
    s = db.store()
    item_id, pid = make_item(s, "NORMALIZED")
    before = _counts(s.conn, item_id)

    victim = db.connect(autocommit=False)
    vs = StateStore(victim)
    vs.transition_item(item_id, "RESEARCHING", AGENT, "will crash", [pid], key())
    pid_backend = victim.info.backend_pid
    db.connect().execute("SELECT pg_terminate_backend(%s)", (pid_backend,))
    time.sleep(0.2)
    with pytest.raises(psycopg.OperationalError):
        victim.commit()
    assert _counts(s.conn, item_id) == before
    assert s.verify_chain().ok


def test_idempotent_replay_is_a_noop(db):
    s = db.store()
    item_id, pid = make_item(s, "NORMALIZED")
    k = key("retry")
    r1 = s.transition_item(item_id, "RESEARCHING", AGENT, "research", [pid], k)
    before = _counts(s.conn, item_id)
    r2 = s.transition_item(item_id, "RESEARCHING", AGENT, "research (retry)", [pid], k)
    assert r1 == r2 and _counts(s.conn, item_id) == before
    with pytest.raises(psycopg.Error) as ei:
        s.transition_item(item_id, "SCORED", AGENT, "reuse key for another move", [pid], k)
    assert ei.value.sqlstate == "MB409"


def test_illegal_transition_and_optimistic_lock(db):
    s = db.store()
    item_id, pid = make_item(s, "NORMALIZED")
    with pytest.raises(psycopg.Error) as ei:
        s.transition_item(item_id, "ACTING", AGENT, "skip ahead", [pid], key())
    assert ei.value.sqlstate == "MB004"
    version = s.conn.execute("SELECT version FROM mbos.items WHERE item_id=%s", (item_id,)).fetchone()[0]
    with pytest.raises(psycopg.Error) as ei:
        s.transition_item(item_id, "RESEARCHING", AGENT, "stale", [pid], key(), expected_version=version - 1)
    assert ei.value.sqlstate == "MB409"
    s.transition_item(item_id, "RESEARCHING", AGENT, "fresh", [pid], key(), expected_version=version)


def test_doc_update_is_receipted_with_before_after(db):
    s = db.store()
    item_id, pid = make_item(s, "SCORED")
    rid = s.update_item_doc(item_id, {"scores": {"scorecard_id": new_id("scr"), "inputs_hash": "sha256:" + "0" * 64}},
                            "SCORE_RECORDED", AGENT, "score v0", [pid], key())
    r = s.conn.execute("SELECT before_state, after_state FROM mbos.receipts WHERE receipt_id=%s", (rid,)).fetchone()
    assert r[0]["doc"] == {"scores": None} and "scores" in r[1]["doc"]
    with pytest.raises(psycopg.Error):
        s.update_item_doc(item_id, {"state": "ACTED"}, "SCORE_RECORDED", AGENT, "sneak state", [pid], key())
