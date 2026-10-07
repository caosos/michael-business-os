"""ADR-0010 interoperability: Postgres (migration 0003) == Python reference on every vector, and a chain the
spine wrote in Postgres verifies with ONLY the pure-Python reference (what any other lane would run)."""

import json

import pytest
import sqlalchemy as sa

from mbos.ledger import load_receipts, verify_chain, verify_exported_chain
from tests.helpers.common import ROOT
from tests.helpers.seed import seed_flow

VECTORS = json.loads((ROOT / "docs/research/contracts/canonical/vectors.json").read_text())


@pytest.mark.parametrize("case", VECTORS["cjson"], ids=lambda c: c["name"])
def test_postgres_matches_vectors(ledger_db, case):
    with ledger_db.connect() as c:
        got, h = c.execute(sa.text("SELECT mbos.cjson(CAST(:j AS jsonb)), mbos.cjson_sha256(CAST(:j AS jsonb))"),
                           {"j": case["input"]}).one()
    assert (got, h) == (case["canonical"], case["sha256"])


def test_postgres_receipt_vectors(ledger_db):
    with ledger_db.connect() as c:
        for r in VECTORS["receipt_chain"]:
            assert c.execute(sa.text("SELECT mbos.rh1_row_hash(CAST(:d AS jsonb))"), {"d": json.dumps(r)}).scalar_one() == r["row_hash"]


def test_spine_chain_verifies_in_pure_python(ledger_db):
    seed_flow(ledger_db)
    with ledger_db.connect() as c:
        assert verify_chain(c)["ok"]
        exported = load_receipts(c)
    ok, msg = verify_exported_chain(exported)
    assert ok, msg
    exported[3]["intent"] += "x"  # and a tamper is caught by the pure-Python verifier too
    assert not verify_exported_chain(exported)[0]


def test_migration_functions_are_the_reference_sql():
    ref = (ROOT / "docs/research/contracts/canonical/mbos_canonical.sql").read_text()
    mig = (ROOT / "src/mbos/db/migrations/0003_canonical_rh1.sql").read_text()
    body = ref[ref.index("-- ECMAScript"):]
    assert body in mig
