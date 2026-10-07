"""A2 (real spine): UPDATE / DELETE / TRUNCATE on ledger tables is rejected — as the `agent_write` role AND as owner."""
import pytest

TABLES = ["receipts", "approvals", "provenance", "outcomes", "effector_calls", "llm_spend", "artifacts"]
OPS = {"UPDATE": "UPDATE mbos.{t} SET {c} = {c}", "DELETE": "DELETE FROM mbos.{t}", "TRUNCATE": "TRUNCATE mbos.{t} CASCADE"}
COL = {"receipts": "seq", "approvals": "seq", "provenance": "provenance_id", "outcomes": "outcome_id",
       "effector_calls": "seq", "llm_spend": "seq", "artifacts": "sha256"}


@pytest.fixture(scope="module")
def full(qa):
    db = qa.ledger()
    db.seed()  # discover → … → ACTED → outcome: every ledger table gets rows
    from mbos.reference.governance import LedgerLLMBudget

    with db.engine.begin() as c:
        LedgerLLMBudget({"*": 1.0}).record(c, "agent-07-marketing", 0.01)
    yield db
    db.dispose()


@pytest.mark.parametrize("table", TABLES)
def test_tables_have_rows(qa, full, table):
    assert qa.scalar(f"SELECT count(*) FROM mbos.{table}", full.engine) > 0


@pytest.mark.parametrize("op", sorted(OPS))
@pytest.mark.parametrize("role", ["agent_write", "owner"])
@pytest.mark.parametrize("table", TABLES)
def test_mutation_rejected(qa, full, table, op, role):
    sql = OPS[op].format(t=table, c=COL[table])
    before = qa.scalar(f"SELECT count(*) FROM mbos.{table}", full.engine)
    if role == "owner":
        with full.engine.connect() as c:
            t = c.begin()
            try:
                import sqlalchemy as sa

                c.execute(sa.text(sql))
                err = None
            except Exception as e:  # noqa: BLE001
                err = str(getattr(e, "orig", e))
            finally:
                t.rollback()
    else:
        err = full.as_role(role, sql)
    assert err is not None, f"{op} on {table} as {role} was ALLOWED"
    if role == "agent_write" and op != "TRUNCATE":  # 01 grants UPDATE/DELETE on purpose: the TRIGGER must refuse
        assert "permission denied" not in err.lower(), f"refused only by a missing GRANT, not the trigger: {err}"
    assert qa.scalar(f"SELECT count(*) FROM mbos.{table}", full.engine) == before
