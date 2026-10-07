"""A4. Every receipt's provenance_ids resolve under provenance.schema.json's anyOf rule."""

import pytest
import sqlalchemy as sa

from mbos import audit, ledger
from mbos.contracts import ContractViolation
from tests.helpers.seed import seed_flow

pytestmark = pytest.mark.acceptance


def test_all_receipts_resolve(ledger_db):
    seed_flow(ledger_db)
    with ledger_db.connect() as c:
        res = audit.provenance_resolution(c)
    assert res["ok"], res
    assert res["receipts"] >= 15


def test_receipt_without_provenance_refused_in_python(ledger_db):
    with pytest.raises(ValueError, match="no receipt without provenance"):
        with ledger_db.begin() as c:
            ledger.append_receipt(c, type="LESSON_RECORDED", intent="x", provenance_ids=[])


def test_receipt_without_provenance_refused_by_db(ledger_db):
    with pytest.raises(sa.exc.DBAPIError):
        with ledger_db.begin() as c:
            c.execute(sa.text("INSERT INTO mbos.receipts (seq, body, row_hash) VALUES (0, CAST(:b AS jsonb), '')"),
                      {"b": '{"receipt_id":"rcpt_01JA0000000000000000000001","type":"LESSON_RECORDED","idempotency_key":"k","provenance_ids":[]}'})


def test_provenance_that_resolves_to_nothing_is_refused(ledger_db):
    with pytest.raises(ContractViolation):  # no source, model, approval or tool
        with ledger_db.begin() as c:
            ledger.record_provenance(c, actor_type="agent", basis="INFERENCE", agent_name="x")
    with pytest.raises(sa.exc.DBAPIError):  # and the DB CHECK refuses it independently
        with ledger_db.begin() as c:
            c.execute(sa.text("INSERT INTO mbos.provenance (body) VALUES (CAST(:b AS jsonb))"),
                      {"b": '{"provenance_id":"prov_01JA0000000000000000000077","created_at":"2026-10-07T00:00:00Z","actor_type":"agent","basis":"FACT"}'})
