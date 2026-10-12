"""D-35 (ADR-0015 P-74-1): app_user + owner seed; a member session is refused on every owner-only function."""

import json

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import key, make_item
from test_campaigns import EXAMPLE
from test_human_only_owner_paths import MISSION

HUMAN = {"type": "human", "id": "michael"}
MEMBER = "mbos_member_t"


def test_owner_seeded_exactly_once(db):
    c = db.connect()
    assert c.execute("SELECT handle, role, home_zip, home_state, default_radius_mi, status FROM mbos.app_user").fetchall() == [
        ("michael", "owner", "72032", "AR", 150, "active")]
    with pytest.raises(errors.UniqueViolation):
        c.execute("INSERT INTO mbos.app_user (handle, display_name, role) VALUES ('second','Second','owner')")
    with pytest.raises(errors.InsufficientPrivilege):
        c.execute("UPDATE mbos.app_user SET role='member'")
    with pytest.raises(errors.InsufficientPrivilege):
        c.execute("UPDATE mbos.app_user SET status='disabled'")
    with pytest.raises(errors.InsufficientPrivilege):
        c.execute("DELETE FROM mbos.app_user")


def test_owner_login_invites_member_but_readers_and_agents_cannot(db):
    ui = db.connect("approver")
    uid = ui.execute("INSERT INTO mbos.app_user (handle, display_name, role, home_zip, home_state) "
                     "VALUES ('pat','Pat','member','43004','OH') RETURNING user_id").fetchone()[0]
    assert uid.startswith("usr_")
    for role in ("reader", "agent_write", "gateway", "dbos"):
        with pytest.raises(errors.InsufficientPrivilege):
            db.connect(role).execute("INSERT INTO mbos.app_user (handle, display_name, role) VALUES ('x1','X','member')")


def _member(db):
    """A login holding the most a member could plausibly be given: read + agent_write. Never owner_channel/approver/gateway."""
    su = db.connect()
    su.execute(f"DROP ROLE IF EXISTS {MEMBER}")
    su.execute(f"CREATE ROLE {MEMBER} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS")
    su.execute(f"GRANT agent_read, agent_write TO {MEMBER}")
    for r in ("owner_channel", "approver", "gateway", "policy_admin"):
        assert su.execute("SELECT pg_has_role(%s,%s,'MEMBER')", (MEMBER, r)).fetchone()[0] is False
    return psycopg.connect(f"{db.base} dbname={db.name} user={MEMBER}", autocommit=True)


def test_member_session_refused_on_every_owner_only_function(db):
    item, _ = make_item(db.store(), "RESEARCHING")
    ui = db.connect("approver")
    hp = ui.execute("""SELECT mbos.record_provenance('{"actor_type":"human","human_actor":"michael","basis":"FACT",
                       "tool_name":"t","tool_version":"1"}')""").fetchone()[0]
    wid = ui.execute("SELECT mbos.watch_auction(%s,now()+interval '2 days',300,6,%s,%s,%s)",
                     (item, Jsonb(HUMAN), [hp], key())).fetchone()[0]
    m = _member(db)
    j, p = Jsonb(HUMAN), [hp]
    calls = [
        ("set_mission", "SELECT mbos.set_mission(%s,%s,'x',%s,%s)", (Jsonb(MISSION), j, p, key())),
        ("capital_fund", "SELECT mbos.capital_fund(5::numeric,%s,'x',%s,%s)", (j, p, key())),
        ("capital_withdraw", "SELECT mbos.capital_withdraw(5::numeric,%s,'x',%s,%s)", (j, p, key())),
        ("set_campaign", "SELECT mbos.set_campaign(%s,%s,'x',%s,%s)", (Jsonb(EXAMPLE), j, p, key())),
        ("cancel_campaign", "SELECT mbos.cancel_campaign(%s,%s,'x',%s,%s)", (EXAMPLE["campaign_id"], j, p, key())),
        ("panic_release", "SELECT mbos.panic_set('L3',NULL,false,%s,'release',%s,%s)", (j, p, key())),
        ("record_attestation", "SELECT mbos.record_attestation(%s,'title_in_hand','n',%s,%s,%s)", (item, j, p, key())),
        ("record_human_input", "SELECT mbos.record_human_input(%s,'scope_override','k',%s,'n',%s,%s,%s)",
         (item, Jsonb({"v": 1}), j, p, key())),
        ("record_acquisition", "SELECT mbos.record_acquisition(%s,10::numeric,'n',%s,%s,%s)", (item, j, p, key())),
        ("watch_auction", "SELECT mbos.watch_auction(%s,now()+interval '2 days',300,6,%s,%s,%s)", (item, j, p, key())),
        ("set_bid_ceiling", "SELECT mbos.set_bid_ceiling(%s,100::numeric,'n',%s,%s,%s)", (wid, j, p, key())),
        ("stop_watch", "SELECT mbos.stop_watch(%s,'n',%s,%s,%s)", (wid, j, p, key())),
        ("human_outcome", "SELECT mbos.record_outcome(%s,%s,'n',%s)", (Jsonb({"item_id": item}), j, key())),
    ]
    for name, sql, args in calls:
        with pytest.raises(errors.InsufficientPrivilege):
            m.execute(sql, args)
    # direct writes are closed as well
    with pytest.raises(errors.InsufficientPrivilege):
        m.execute("INSERT INTO mbos.app_user (handle, display_name, role) VALUES ('me','Me','member')")
    assert m.execute("SELECT count(*) FROM mbos.capital_ledger").fetchone()[0] == 0
    assert m.execute("SELECT count(*) FROM mbos.auction_watch_events WHERE kind IN ('ceiling','stopped')").fetchone()[0] == 0
    assert db.store().verify_chain().ok
