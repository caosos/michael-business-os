"""A2. UPDATE or DELETE on receipts, approvals or provenance is rejected by a trigger,
even for the agent_write role (which deliberately HAS the UPDATE/DELETE grants)."""

import pytest
import sqlalchemy as sa

from tests.helpers.seed import seed_flow

pytestmark = pytest.mark.acceptance

LEDGERS = ["receipts", "approvals", "provenance", "outcomes", "effector_calls", "artifacts", "llm_spend"]


@pytest.fixture()
def seeded(ledger_db):
    seed_flow(ledger_db)
    with ledger_db.begin() as c:
        c.execute(sa.text("INSERT INTO mbos.llm_spend (agent_id, day, usd) VALUES ('a', current_date, 0)"))
    return ledger_db


@pytest.mark.parametrize("role", ["agent_write", "owner"])
@pytest.mark.parametrize("table", LEDGERS)
@pytest.mark.parametrize("stmt", ["UPDATE mbos.{t} SET {col} = {col}", "DELETE FROM mbos.{t}", "TRUNCATE mbos.{t} CASCADE"])
def test_mutation_rejected(seeded, table, stmt, role):
    """agent_write holds UPDATE/DELETE grants, and the owner (superuser) bypasses grants entirely:
    in both cases only the insert-only TRIGGER stands in the way. (agent_write has no TRUNCATE grant,
    so for it TRUNCATE is refused one step earlier, by privilege.)"""
    col = {"artifacts": "media_type", "llm_spend": "agent_id", "effector_calls": "provider"}.get(table, "body")
    with seeded.connect() as c:
        assert c.execute(sa.text(f"SELECT count(*) FROM mbos.{table}")).scalar_one() > 0, "row triggers need rows"
    expected = "permission denied" if (role == "agent_write" and stmt.startswith("TRUNCATE")) else "insert-only ledger"
    with pytest.raises(sa.exc.DBAPIError, match=expected):
        with seeded.begin() as c:
            if role == "agent_write":
                c.execute(sa.text("SET LOCAL ROLE agent_write"))
                if not stmt.startswith("TRUNCATE"):
                    priv = "UPDATE" if stmt.startswith("UPDATE") else "DELETE"
                    assert c.execute(sa.text("SELECT has_table_privilege('agent_write', :t, :p)"),
                                     {"t": f"mbos.{table}", "p": priv}).scalar_one()
            c.execute(sa.text(stmt.format(t=table, col=col)))


def test_frozen_action_request_payload(seeded):
    with pytest.raises(sa.exc.DBAPIError, match="is frozen"):
        with seeded.begin() as c:
            c.execute(sa.text("SET LOCAL ROLE agent_write"))
            c.execute(sa.text("UPDATE mbos.action_requests SET body = jsonb_set(body, '{payload,summary}', '\"offer $1\"')"))


def test_items_are_never_deleted(seeded):
    with pytest.raises(sa.exc.DBAPIError, match="never deleted"):
        with seeded.begin() as c:
            c.execute(sa.text("SET LOCAL ROLE agent_write"))
            c.execute(sa.text("DELETE FROM mbos.items"))
