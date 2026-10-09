"""D-31 (F-114/F-115): Michael records an off-system purchase; capital deploys only then. Real roles."""

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import flip_doc, key
from test_capital_ledger import Cap
from test_human_only_owner_paths import real_dbos  # noqa: F401

AGENT = {"type": "agent", "id": "agent-03-economics"}
HUMAN = {"type": "human", "id": "michael"}


def _hp(conn):
    return conn.execute("""SELECT mbos.record_provenance('{"actor_type":"human","human_actor":"michael","basis":"FACT",
                           "tool_name":"mbos.human_input","tool_version":"0.1.0"}')""").fetchone()[0]


def _acq(conn, item_id, pid, amount, actor=HUMAN, idem=None, note="bought it"):
    return conn.execute("SELECT mbos.record_acquisition(%s,%s::numeric,%s,%s,%s,%s)",
                        (item_id, amount, note, Jsonb(actor), [pid], idem or key("acq"))).fetchone()[0]


def test_acquisition_deploys_then_close_returns_principal_and_profit(db):
    cap = Cap(db)
    cap.fund(500)
    item = cap.item()
    ui = db.store("approver")
    hp = _hp(ui.conn)
    k = key("acq")
    rid = _acq(ui.conn, item, hp, 120, idem=k)
    assert _acq(ui.conn, item, hp, 120, idem=k) == rid                           # idempotent replay deploys once
    assert cap.pos()[:5] == (500, 0, 120, 0, 380)                                # available falls, deployed rises
    r = ui.conn.execute("SELECT type, actor->>'type', budget_effect->>'category', details->>'dry_run' FROM mbos.receipts"
                        " WHERE receipt_id=%s", (rid,)).fetchone()
    assert r == ("BUDGET_COMMITTED", "human", "purchase", "true")
    assert ui.conn.execute("SELECT status FROM mbos.action_requests WHERE item_id=%s", (item,)).fetchone()[0] == "executed"
    cap.close(item, 200, 120, store=ui)                                          # principal 120 back + 80 profit
    assert cap.pos()[:5] == (500, 80, 0, 80, 580)
    with pytest.raises(psycopg.DatabaseError, match="already closed"):           # F-115
        cap.close(item, 999, 120, store=ui)
    with pytest.raises(psycopg.DatabaseError, match="already closed"):
        cap.close(item, 1, 120, store=ui, kind="flip_sold")
    assert cap.pos()[:5] == (500, 80, 0, 80, 580)
    assert cap.verified()[0] and ui.verify_chain().ok


def test_over_available_and_unfunded_refused_and_roll_back(db):
    cap = Cap(db)
    ui = db.store("approver")
    hp = _hp(ui.conn)
    item = cap.item()
    with pytest.raises(psycopg.DatabaseError, match="not funded"):
        _acq(ui.conn, item, hp, 10)
    cap.fund(100)
    with pytest.raises(psycopg.DatabaseError, match="exceeds available"):
        _acq(ui.conn, item, hp, 100.01)
    assert cap.pos()[:5] == (100, 0, 0, 0, 100)
    assert ui.conn.execute("SELECT count(*) FROM mbos.action_requests WHERE item_id=%s", (item,)).fetchone()[0] == 0
    _acq(ui.conn, item, hp, 100)
    assert cap.pos()[:5] == (100, 0, 100, 0, 0)
    with pytest.raises(psycopg.DatabaseError, match="exceeds available"):
        _acq(ui.conn, cap.item(), hp, 0.01)
    assert ui.verify_chain().ok


@pytest.mark.parametrize("amount", [0, -5, 0.001, 1e9])
def test_bad_amount_refused(db, amount):
    cap = Cap(db)
    cap.fund(100)
    ui = db.store("approver")
    with pytest.raises(psycopg.DatabaseError, match="amount"):
        _acq(ui.conn, cap.item(), _hp(ui.conn), amount)


@pytest.mark.parametrize("actor", [{"type": "agent", "id": "agent-x"}, {"type": "human"}])
def test_non_human_actor_refused(db, actor):
    cap = Cap(db)
    cap.fund(100)
    ui = db.store("approver")
    with pytest.raises(errors.InsufficientPrivilege):
        _acq(ui.conn, cap.item(), _hp(ui.conn), 10, actor=actor)


def test_needs_human_provenance(db):
    cap = Cap(db)
    cap.fund(100)
    with pytest.raises(psycopg.DatabaseError, match="human provenance"):
        _acq(db.store("approver").conn, cap.item(), cap.pid, 10)


def test_workflow_roles_refused(db):
    cap = Cap(db)
    cap.fund(100)
    item = cap.item()
    hp = _hp(db.store("approver").conn)
    for role in ("agent_write", "gateway"):
        with pytest.raises(errors.InsufficientPrivilege):
            _acq(db.store(role).conn, item, hp, 10)
    assert cap.pos()[:5] == (100, 0, 0, 0, 100)


def test_real_mbos_dbos_refused(real_dbos):
    p, pid = real_dbos
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:
        hp = _hp(c)
        doc = flip_doc()
        doc["sources"][0]["provenance_id"] = pid
        item_id = c.execute("SELECT mbos.create_item(%s,%s,'x',%s,%s)", (Jsonb(doc), Jsonb(AGENT), [pid], key())).fetchone()[0]
        with pytest.raises(errors.InsufficientPrivilege):
            _acq(c, item_id, hp, 10)
