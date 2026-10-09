"""D-33: auction watchlist, alerts fire once, bid ceiling is storage only, and no bid path exists. Real roles."""

from datetime import datetime, timedelta, timezone

import psycopg
import pytest
from psycopg.types.json import Jsonb

from conftest import key, make_item

HUMAN = {"type": "human", "id": "michael"}
AGENT = {"type": "agent", "id": "agent-02-opportunity"}
CLOSE = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)


def _hp(conn):
    return conn.execute("""SELECT mbos.record_provenance('{"actor_type":"human","human_actor":"michael","basis":"FACT",
                           "tool_name":"mbos.watch","tool_version":"0.1.0"}')""").fetchone()[0]


def _watch(ui, item, hp, price=300, hours=6, idem=None):
    return ui.conn.execute("SELECT mbos.watch_auction(%s,%s,%s,%s,%s,%s,%s)",
                           (item, CLOSE, price, hours, Jsonb(HUMAN), [hp], idem or key("w"))).fetchone()[0]


def _obs(conn, wid, hp, bid, count, at, actor=HUMAN, closes=None, idem=None):
    return conn.execute("SELECT mbos.record_watch_observation(%s,%s,%s,%s,%s,%s,%s,%s)",
                        (wid, bid, count, at, closes, Jsonb(actor), [hp], idem or key("o"))).fetchone()[0]


def _setup(db):
    item, _ = make_item(db.store(), "RESEARCHING")
    ui = db.store("approver")
    hp = _hp(ui.conn)
    return item, ui, hp, _watch(ui, item, hp)


def test_alerts_fire_once_per_event_and_replay_is_silent(db):
    item, ui, hp, wid = _setup(db)
    h = timedelta(hours=1)
    assert _obs(ui.conn, wid, hp, 100, 2, CLOSE - 48 * h) == []                              # nothing yet
    k = key("o")
    assert _obs(ui.conn, wid, hp, 320, 5, CLOSE - 20 * h, idem=k) == ["price"]               # crosses $300
    assert _obs(ui.conn, wid, hp, 320, 5, CLOSE - 20 * h, idem=k) == []                     # idempotent replay
    assert _obs(ui.conn, wid, hp, 350, 6, CLOSE - 10 * h) == []                              # price already fired
    assert _obs(ui.conn, wid, hp, 360, 7, CLOSE - 5 * h) == ["closing"]                      # inside last 6 hours
    assert _obs(ui.conn, wid, hp, 380, 8, CLOSE - 1 * h) == []                               # closing already fired
    assert _obs(ui.conn, wid, hp, 400, 9, CLOSE + h) == []                                  # after close: no closing alert
    cur = ui.conn.execute("SELECT current_bid, bid_count, alerts_fired, stopped FROM mbos.v_auction_watch_current WHERE watch_id=%s", (wid,)).fetchone()
    assert cur == (400, 9, ["price", "closing"], False)
    assert ui.conn.execute("SELECT count(*) FROM mbos.auction_watch_events WHERE kind='alert'").fetchone()[0] == 2
    assert ui.conn.execute("SELECT count(*) FROM mbos.auction_watch_events WHERE kind='observation'").fetchone()[0] == 6
    assert ui.verify_chain().ok


def test_ceiling_reached_fires_once_and_latest_ceiling_wins(db):
    item, ui, hp, wid = _setup(db)
    c = lambda amt: ui.conn.execute("SELECT mbos.set_bid_ceiling(%s,%s,'my max',%s,%s,%s)", (wid, amt, Jsonb(HUMAN), [hp], key("c"))).fetchone()[0]
    c(200)
    c(250)
    at = CLOSE - timedelta(hours=30)
    assert _obs(ui.conn, wid, hp, 200, 3, at) == []
    assert _obs(ui.conn, wid, hp, 250, 4, at + timedelta(minutes=1)) == ["ceiling_reached"]
    assert _obs(ui.conn, wid, hp, 260, 5, at + timedelta(minutes=2)) == []
    assert ui.conn.execute("SELECT bid_ceiling_usd FROM mbos.v_auction_watch_current WHERE watch_id=%s", (wid,)).fetchone()[0] == 250
    for bad in (0, -1, 0.001, 1e9):
        with pytest.raises(psycopg.DatabaseError, match="ceiling"):
            c(bad)


def test_soft_close_extension_moves_the_closing_window(db):
    item, ui, hp, wid = _setup(db)
    at = CLOSE - timedelta(hours=10)
    assert _obs(ui.conn, wid, hp, 10, 1, at, closes=CLOSE + timedelta(hours=24)) == []      # extended: 10h out is now 34h out
    assert ui.conn.execute("SELECT closes_at FROM mbos.v_auction_watch_current WHERE watch_id=%s", (wid,)).fetchone()[0] == CLOSE + timedelta(hours=24)


def test_stop_ends_observations_and_only_owner_channel_humans_manage(db):
    item, ui, hp, wid = _setup(db)
    with pytest.raises(psycopg.DatabaseError, match="already on the watchlist"):
        _watch(ui, item, hp)
    ui.conn.execute("SELECT mbos.stop_watch(%s,'won elsewhere',%s,%s,%s)", (wid, Jsonb(HUMAN), [hp], key("s")))
    with pytest.raises(psycopg.DatabaseError, match="stopped"):
        _obs(ui.conn, wid, hp, 1, 1, CLOSE - timedelta(days=1))
    assert ui.verify_chain().ok


def test_agent_may_observe_but_not_watch_ceiling_or_stop(db):
    item, ui, hp, wid = _setup(db)
    ag = db.store("agent_write")
    ap = ag.conn.execute("""SELECT mbos.record_provenance('{"actor_type":"agent","agent_name":"agent-02","basis":"FACT",
                            "tool_name":"fixture","tool_version":"0.1.0"}')""").fetchone()[0]
    assert _obs(ag.conn, wid, ap, 301, 3, CLOSE - timedelta(days=2), actor=AGENT) == ["price"]
    for sql, args in (("SELECT mbos.watch_auction(%s,%s,1,6,%s,%s,%s)", (item, CLOSE, Jsonb(HUMAN), [hp], key("x"))),
                      ("SELECT mbos.set_bid_ceiling(%s,10,'x',%s,%s,%s)", (wid, Jsonb(HUMAN), [hp], key("x"))),
                      ("SELECT mbos.stop_watch(%s,'x',%s,%s,%s)", (wid, Jsonb(HUMAN), [hp], key("x")))):
        with pytest.raises(psycopg.DatabaseError):
            ag.conn.execute(sql, args)
            ag.conn.commit()
        ag.conn.rollback()
    for tbl in ("auction_watches", "auction_watch_events"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            ag.conn.execute(f"INSERT INTO mbos.{tbl} DEFAULT VALUES")
        ag.conn.rollback()
    with pytest.raises(psycopg.DatabaseError, match="human"):                              # agent may not claim to be a human
        ui.conn.execute("SELECT mbos.set_bid_ceiling(%s,10,'x',%s,%s,%s)", (wid, Jsonb(AGENT), [hp], key("x")))


def test_negative_no_bid_path(db):
    """Dry-run guarantee: no bid function exists, and watching, alerting and a stored ceiling touch no action, budget or capital."""
    item, ui, hp, wid = _setup(db)
    ui.conn.execute("SELECT mbos.set_bid_ceiling(%s,250,'max',%s,%s,%s)", (wid, Jsonb(HUMAN), [hp], key("c")))
    assert _obs(ui.conn, wid, hp, 999, 50, CLOSE - timedelta(hours=1)) == ["price", "closing", "ceiling_reached"]
    names = [r[0] for r in ui.conn.execute(
        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='mbos'").fetchall()]
    assert not [n for n in names if "bid" in n and n != "set_bid_ceiling"], names
    assert not [n for n in names if any(w in n for w in ("place", "submit", "snipe", "auto_bid"))], names
    assert ui.conn.execute("SELECT count(*) FROM mbos.action_requests WHERE item_id=%s", (item,)).fetchone()[0] == 0
    assert ui.conn.execute("SELECT count(*) FROM mbos.receipts WHERE type IN ('BUDGET_COMMITTED','BUDGET_RESERVED','ACTION_EXECUTED')"
                           " AND item_id=%s", (item,)).fetchone()[0] == 0
    assert ui.conn.execute("SELECT count(*) FROM mbos.capital_ledger WHERE item_id=%s", (item,)).fetchone()[0] == 0
    assert ui.conn.execute("SELECT count(*) FROM mbos.receipts WHERE entity_type='auction_watch' AND effect IN ('send','pay','publish','commit')").fetchone()[0] == 0
    assert ui.verify_chain().ok
