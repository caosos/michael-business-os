"""D-36 (ADR-0015 P-74-2): per-user prefs, saved/dismissed and watches never leak; alerts fire once per user per item."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import key, make_item

HUMAN = {"type": "human", "id": "michael"}
CLOSE = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)


def _login(db, handle):
    su = db.connect()
    su.execute(f"DROP ROLE IF EXISTS mbos_{handle}_t")
    su.execute(f"CREATE ROLE mbos_{handle}_t LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
    su.execute(f"GRANT agent_read, agent_write TO mbos_{handle}_t")
    uid = db.connect("approver").execute(
        "INSERT INTO mbos.app_user (handle, display_name, role, db_login) VALUES (%s,%s,'member',%s) RETURNING user_id",
        (handle, handle.title(), f"mbos_{handle}_t")).fetchone()[0]
    return uid, psycopg.connect(f"{db.base} dbname={db.name} user=mbos_{handle}_t", autocommit=True)


def _owner(db):
    return db.connect().execute("SELECT user_id FROM mbos.app_user WHERE role='owner'").fetchone()[0]


def test_prefs_and_item_state_are_private_per_user(db):
    item, _ = make_item(db.store(), "RESEARCHING")
    other, _ = make_item(db.store(), "RESEARCHING")
    ann, a = _login(db, "ann")
    bob, b = _login(db, "bob")
    a.execute("SELECT mbos.set_user_pref(%s,'more',%s)", (ann, Jsonb(["tools"])))
    a.execute("SELECT mbos.set_user_item_state(%s,%s,'saved')", (ann, item))
    a.execute("SELECT mbos.set_user_item_state(%s,%s,'dismissed')", (ann, other))
    b.execute("SELECT mbos.set_user_item_state(%s,%s,'dismissed')", (bob, item))
    assert a.execute("SELECT item_id, state FROM mbos.get_user_item_states(%s) ORDER BY 1", (ann,)).fetchall() == sorted(
        [(item, "saved"), (other, "dismissed")])
    assert b.execute("SELECT item_id, state FROM mbos.get_user_item_states(%s)", (bob,)).fetchall() == [(item, "dismissed")]
    assert b.execute("SELECT * FROM mbos.get_user_prefs(%s)", (bob,)).fetchall() == []
    assert a.execute("SELECT key, value FROM mbos.get_user_prefs(%s)", (ann,)).fetchall() == [("more", ["tools"])]
    # a member can neither read nor write another user's rows, including the owner's, and has no table access
    for target in (bob, _owner(db)):
        with pytest.raises(errors.InsufficientPrivilege):
            a.execute("SELECT * FROM mbos.get_user_prefs(%s)", (target,))
        with pytest.raises(errors.InsufficientPrivilege):
            a.execute("SELECT mbos.set_user_pref(%s,'less',%s)", (target, Jsonb([])))
        with pytest.raises(errors.InsufficientPrivilege):
            a.execute("SELECT mbos.set_user_item_state(%s,%s,'saved')", (target, item))
        with pytest.raises(errors.InsufficientPrivilege):
            a.execute("SELECT * FROM mbos.get_user_item_states(%s)", (target,))
        with pytest.raises(errors.InsufficientPrivilege):
            a.execute("SELECT * FROM mbos.get_user_watches(%s)", (target,))
    for t in ("user_pref", "user_item_state"):
        with pytest.raises(errors.InsufficientPrivilege):
            a.execute(f"SELECT * FROM mbos.{t}")
    with pytest.raises(errors.CheckViolation):
        db.connect("approver").execute("SELECT mbos.set_user_pref(%s,'saved','[]')", (ann,))
    a.execute("SELECT mbos.set_user_item_state(%s,%s,NULL)", (ann, item))
    assert a.execute("SELECT count(*) FROM mbos.get_user_item_states(%s)", (ann,)).fetchone()[0] == 1
    # an agent session with no user mapping cannot act as anyone
    with pytest.raises(errors.InsufficientPrivilege):
        db.connect("agent_write").execute("SELECT mbos.set_user_pref(%s,'more','[]')", (ann,))
    # the owner's saved/dismissed is untouched by the members
    assert db.connect("approver").execute("SELECT count(*) FROM mbos.get_user_item_states(%s)", (_owner(db),)).fetchone()[0] == 0


def _hp(c):
    return c.execute("""SELECT mbos.record_provenance('{"actor_type":"human","human_actor":"michael","basis":"FACT",
                        "tool_name":"mbos.watch","tool_version":"0.1.0"}')""").fetchone()[0]


def test_watches_are_per_user_and_alert_once_per_user_per_threshold(db):
    item, _ = make_item(db.store(), "RESEARCHING")
    ann, a = _login(db, "ann")
    ui = db.connect("approver")
    hp = _hp(ui)
    owner = _owner(db)
    w_owner = ui.execute("SELECT mbos.watch_auction(%s,%s,300,6,%s,%s,%s)", (item, CLOSE, Jsonb(HUMAN), [hp], key())).fetchone()[0]
    w_ann = ui.execute("SELECT mbos.watch_auction(%s,%s,200,6,%s,%s,%s,%s)", (item, CLOSE, ann, Jsonb(HUMAN), [hp], key())).fetchone()[0]
    assert ui.execute("SELECT user_id FROM mbos.auction_watches WHERE watch_id=%s", (w_owner,)).fetchone()[0] == owner
    with pytest.raises(psycopg.Error):
        ui.execute("SELECT mbos.watch_auction(%s,%s,200,6,%s,%s,%s,%s)", (item, CLOSE, ann, Jsonb(HUMAN), [hp], key()))
    at = CLOSE - timedelta(days=2)
    f1 = ui.execute("SELECT mbos.record_watch_observation(%s,250,3,%s,NULL,%s,%s,%s)", (w_ann, at, Jsonb(HUMAN), [hp], key())).fetchone()[0]
    f2 = ui.execute("SELECT mbos.record_watch_observation(%s,260,4,%s,NULL,%s,%s,%s)", (w_ann, at, Jsonb(HUMAN), [hp], key())).fetchone()[0]
    fo = ui.execute("SELECT mbos.record_watch_observation(%s,250,3,%s,NULL,%s,%s,%s)", (w_owner, at, Jsonb(HUMAN), [hp], key())).fetchone()[0]
    assert (f1, f2, fo) == (["price"], [], [])          # ann's 200 threshold fires once; the owner's 300 is not reached
    assert [r[0] for r in a.execute("SELECT watch_id FROM mbos.get_user_watches(%s)", (ann,)).fetchall()] == [w_ann]
    assert [r[0] for r in ui.execute("SELECT watch_id FROM mbos.get_user_watches(%s)", (owner,)).fetchall()] == [w_owner]
    # a member cannot create a watch or set a ceiling (owner-only paths unchanged)
    with pytest.raises(errors.InsufficientPrivilege):
        a.execute("SELECT mbos.watch_auction(%s,%s,200,6,%s,%s,%s,%s)", (item, CLOSE, ann, Jsonb(HUMAN), [hp], key()))
    with pytest.raises(errors.InsufficientPrivilege):
        a.execute("SELECT mbos.set_bid_ceiling(%s,100::numeric,'n',%s,%s,%s)", (w_ann, Jsonb(HUMAN), [hp], key()))
    assert db.store().verify_chain().ok
