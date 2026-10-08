"""D-25 (F-80/F-81/F-83): the five owner paths need the owner_channel DB role, held only by mbos_operator_ui."""

import copy

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import key
from test_campaigns import EXAMPLE
from test_capital_ledger import Cap
from test_human_only_owner_paths import MISSION, N, _calls, real_dbos  # noqa: F401

HUMAN = {"type": "human", "id": "michael"}


def test_roles_membership_is_exactly_the_ui_login(real_dbos):
    p, _ = real_dbos
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:
        assert c.execute("SELECT pg_has_role(session_user,'owner_channel','MEMBER')").fetchone()[0] is False
    with psycopg.connect(p.app_conninfo.replace("user=mbos_dbos", "user=postgres"), autocommit=True) as su:
        members = {r[0] for r in su.execute("""SELECT m.rolname FROM pg_auth_members a JOIN pg_roles g ON g.oid = a.roleid
                                               JOIN pg_roles m ON m.oid = a.member WHERE g.rolname = 'owner_channel'""")}
    assert members == {"mbos_operator_ui"}


def test_real_mbos_dbos_refused_on_all_five_with_forged_human_and_real_provenance(real_dbos):
    p, pid = real_dbos
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:
        assert c.execute("SELECT session_user").fetchone()[0] == "mbos_dbos"
        for sql, args in _calls(HUMAN, pid):
            with pytest.raises(errors.InsufficientPrivilege):
                c.execute(sql, args)
        # direct table writes and a forged receipt through append_receipt are closed too
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("INSERT INTO mbos.mission (mission_version, period_start, period_end, created_by, provenance_ids) "
                      "VALUES ('1.0.0', now(), now(), 'michael', %s)", ([pid],))
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT mbos.append_receipt(%s)", (Jsonb({
                "type": "CONFIG_VERSION_BUMPED", "actor": HUMAN, "intent": "forge", "entity_type": "capital_fund",
                "entity_id": "capital:forged", "effect": "create", "idempotency_key": key(), "provenance_ids": [pid],
                "after_state": {"amount": 1000, "mode": "dry_run", "currency": "USD"},
                "details": {"kind": "money", "dry_run": True}}),))
        assert c.execute("SELECT count(*) FROM mbos.capital_ledger").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM mbos.campaigns").fetchone()[0] == 0


def test_operator_ui_login_works_for_all_five(db):
    cap = Cap(db)
    conn = cap.owner.conn
    assert conn.execute("SELECT session_user").fetchone()[0] == "mbos_operator_ui"
    for i, (sql, args) in enumerate(_calls(HUMAN, cap.pid)[:4]):
        if i == 2:       # withdraw: authorised, then refused on business grounds (nothing earned yet), not on privilege
            with pytest.raises(psycopg.DatabaseError, match="earned working capital"):
                conn.execute(sql, args)
            continue
        conn.execute(sql, args)
    conn.execute("SELECT mbos.cancel_campaign(%s,%s,'x',%s,%s)", (EXAMPLE["campaign_id"], Jsonb(HUMAN), [cap.pid], key()))
    assert cap.owner.verify_chain().ok


def _set(cap, body):
    return cap.owner.conn.execute("SELECT mbos.set_campaign(%s,%s,'x',%s,%s)",
                                  (Jsonb(body), Jsonb(HUMAN), [cap.pid], key())).fetchone()


def _mut(path, value):
    d = copy.deepcopy(EXAMPLE)
    o = d
    for k in path[:-1]:
        o = o[k]
    o[path[-1]] = value
    return d


BAD_BODIES = [
    _mut(["criteria", "max_price_usd"], -1), _mut(["criteria", "max_price_usd"], "600"),
    _mut(["criteria", "max_price_usd"], None), _mut(["criteria", "max_price_usd"], 1e15),
    _mut(["title"], ""), _mut(["title"], "  "), _mut(["owner"], ""), _mut(["owner"], 5),
    _mut(["title"], "x" * 201), _mut(["criteria", "keywords"], "5x8"), _mut(["criteria", "keywords"], ["a", 3]),
    _mut(["criteria", "keywords"], ["k" * 201]), _mut(["criteria", "must_have"], ["m" * 201]),
]


@pytest.mark.parametrize("body", BAD_BODIES)
def test_f81_bad_campaign_bodies_refused(db, body):
    cap = Cap(db)
    with pytest.raises(errors.CheckViolation):
        _set(cap, body)
    assert db.connect("reader").execute("SELECT count(*) FROM mbos.campaigns").fetchone()[0] == 0


def test_f81_boundary_values_accepted(db):
    cap = Cap(db)
    body = _mut(["criteria", "max_price_usd"], 0)
    body["title"] = "t" * 200
    _set(cap, body)


def test_f83_cancelled_campaign_cannot_be_resurrected(db):
    cap = Cap(db)
    _set(cap, EXAMPLE)
    cap.owner.conn.execute("SELECT mbos.cancel_campaign(%s,%s,'x',%s,%s)", (EXAMPLE["campaign_id"], Jsonb(HUMAN), [cap.pid], key()))
    for status in ("ACTIVE", "PAUSED", "CANCELLED"):
        with pytest.raises(errors.CheckViolation, match="CANCELLED"):
            _set(cap, {**EXAMPLE, "status": status})
    rows = db.connect("reader").execute("SELECT count(*), max(status) FROM mbos.campaigns").fetchone()
    assert rows == (2, "CANCELLED")
