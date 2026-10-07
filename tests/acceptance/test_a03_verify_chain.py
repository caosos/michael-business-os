"""A3. verify_chain passes, and fails after a single byte is tampered with (05 §17 tamper test)."""

import threading

import pytest
import sqlalchemy as sa

from mbos import ledger
from tests.helpers.seed import seed_flow

pytestmark = pytest.mark.acceptance


def _tamper(engine, sql, **params):
    """Bypass the insert-only triggers the only way possible: superuser + replication role."""
    with engine.begin() as c:
        c.execute(sa.text("SET LOCAL session_replication_role = replica"))
        c.execute(sa.text(sql), params)


def test_chain_verifies(ledger_db):
    seed_flow(ledger_db)
    with ledger_db.connect() as c:
        res = ledger.verify_chain(c)
    assert res["ok"] and res["checked"] >= 15


def test_one_byte_tamper_detected(ledger_db):
    seed_flow(ledger_db)
    with ledger_db.connect() as c:
        seq, intent = c.execute(sa.text("SELECT seq, body->>'intent' FROM mbos.receipts ORDER BY seq OFFSET 5 LIMIT 1")).one()
    flipped = ("X" if intent[0] != "X" else "Y") + intent[1:]
    _tamper(ledger_db, "UPDATE mbos.receipts SET body = jsonb_set(body, '{intent}', to_jsonb(CAST(:v AS text))) WHERE seq = :s",
            v=flipped, s=seq)
    with ledger_db.connect() as c:
        res = ledger.verify_chain(c)
    assert not res["ok"] and res["first_bad_seq"] == seq and "row_hash" in res["reason"]


def test_deleted_row_detected(ledger_db):
    seed_flow(ledger_db)
    with ledger_db.connect() as c:
        seq = c.execute(sa.text("SELECT seq FROM mbos.receipts ORDER BY seq OFFSET 3 LIMIT 1")).scalar_one()
    _tamper(ledger_db, "DELETE FROM mbos.receipts WHERE seq = :s", s=seq)
    with ledger_db.connect() as c:
        res = ledger.verify_chain(c)
    assert not res["ok"] and "prev_hash" in res["reason"]


def test_concurrent_writers_keep_one_linear_chain(ledger_db):
    with ledger_db.begin() as c:
        prov = ledger.tool_provenance(c, "tests.a3")
    errors = []

    def writer(n):
        try:
            for i in range(15):
                with ledger_db.begin() as c:
                    ledger.append_receipt(c, type="LESSON_RECORDED", intent=f"w{n}-{i}", provenance_ids=[prov],
                                          entity_id=f"w{n}", idempotency_key=f"w{n}:{i}")
        except Exception as e:  # pragma: no cover - surfaced below
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors
    with ledger_db.connect() as c:
        res = ledger.verify_chain(c)
        seqs = c.execute(sa.text("SELECT array_agg(seq ORDER BY seq) FROM mbos.receipts")).scalar_one()
    assert res["ok"] and res["checked"] == 120
    assert seqs == list(range(seqs[0], seqs[0] + 120)), "seq is gap-free and matches chain order"


def test_snapshot_isolation_writers_refused(ledger_db):
    with ledger_db.begin() as c:
        prov = ledger.tool_provenance(c, "tests.a3")
    with pytest.raises(sa.exc.DBAPIError, match="READ COMMITTED"):
        with ledger_db.connect().execution_options(isolation_level="REPEATABLE READ") as c:
            with c.begin():
                ledger.append_receipt(c, type="LESSON_RECORDED", intent="rr", provenance_ids=[prov], entity_id="rr")
