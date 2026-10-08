"""P-06-12 (R14): connect as lane D's REAL Operator UI login (`mbos_operator_ui`, member of `approver` only), not the
pgserver superuser, and prove the database itself refuses what the UI must never do. DSN env var for production:
MBOS_APPROVER_DATABASE_URL (see operator_ui.__main__.ui_engine)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy.engine import make_url

pytestmark = pytest.mark.usefixtures("rtd")


@pytest.fixture(scope="module")
def ui_role(rtd):
    url = make_url(rtd.url).set(username="mbos_operator_ui", password=None)
    eng = sa.create_engine(url)
    with eng.connect() as c:
        assert c.execute(sa.text("SELECT current_user, (SELECT rolsuper FROM pg_roles WHERE rolname=current_user)")).one() == ("mbos_operator_ui", False)
    yield eng
    eng.dispose()


def refused(eng, sql, params=None):
    with pytest.raises(sa.exc.DBAPIError) as e:
        with eng.begin() as c:
            c.execute(sa.text(sql), params or {})
    return str(e.value.orig)


def test_ui_role_can_decide_approvals(ui_role):
    with ui_role.connect() as c:
        q = lambda s: c.execute(sa.text(s)).scalar_one()
        assert q("SELECT has_table_privilege('mbos.approvals','INSERT')")
        assert q("SELECT has_function_privilege('mbos.record_approval(jsonb,jsonb,text,text,text[])','EXECUTE')")
        assert q("SELECT has_column_privilege('mbos.action_requests','status','UPDATE')")
        assert q("SELECT has_table_privilege('mbos.items','SELECT')")


@pytest.mark.parametrize("sql", [
    "INSERT INTO mbos.capital_ledger DEFAULT VALUES",
    "UPDATE mbos.capital_ledger SET amount = 1000000",
    "DELETE FROM mbos.capital_ledger",
])
def test_ui_role_cannot_mint_or_edit_capital(ui_role, sql):
    assert "permission denied" in refused(ui_role, sql)


@pytest.mark.parametrize("sql", [
    "UPDATE mbos.receipts SET intent = 'edited'",
    "DELETE FROM mbos.receipts",
    "TRUNCATE mbos.receipts",
])
def test_ui_role_cannot_edit_receipts(ui_role, sql):
    assert "permission denied" in refused(ui_role, sql)


def test_ui_role_cannot_write_enrichment_or_items_doc(ui_role):
    assert "permission denied" in refused(
        ui_role, "SELECT mbos.append_item_research('x', '[]'::jsonb, '{}'::jsonb, 'i', ARRAY[]::text[], 'k', 'k', NULL)")
    assert "permission denied" in refused(ui_role, "UPDATE mbos.items SET doc = '{}'::jsonb")
    assert "permission denied" in refused(ui_role, "SELECT mbos.update_item_doc('x','{}'::jsonb,'k','{}'::jsonb,'i',ARRAY[]::text[],'k',1,NULL)")


def test_ui_role_cannot_execute_or_spend(ui_role):
    assert "permission denied" in refused(ui_role, "INSERT INTO mbos.budget_ledger DEFAULT VALUES")
    assert "permission denied" in refused(ui_role, "SELECT mbos.budget_reserve('a',1,'USD',1,'{}'::jsonb,'i',ARRAY[]::text[],'k')")
