"""D-23: (a) F-78: the capital/mission functions refuse a non-human actor from the owner login, in the database;
(b) campaign persistence: insert-only revisions, receipts, E-17 CHECK, current-revision view."""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import key
from test_capital_ledger import Cap

ADD = Path(__file__).parent / "contracts-additive"
SCHEMA = Draft202012Validator(json.loads((ADD / "campaign.schema.json").read_text()),
                              format_checker=Draft202012Validator.FORMAT_CHECKER)
EXAMPLE = json.loads((ADD / "examples/campaign/trailer-wanted.example.json").read_text())


@pytest.fixture
def cap(db):
    return Cap(db)


def _ex(**over):
    d = copy.deepcopy(EXAMPLE)
    for k, val in over.items():
        if k == "level":
            d["autonomy"]["level"] = val
        else:
            d[k] = val
    return d


def _set(cap, body, actor=None, k=None, conn=None):
    return (conn or cap.owner.conn).execute("SELECT mbos.set_campaign(%s,%s,'set campaign',%s,%s)",
                                            (Jsonb(body), Jsonb(actor) if actor else cap.human, [cap.pid],
                                             k or key("c"))).fetchone()[0]


BAD_ACTORS = [{"type": "agent", "id": "agent-x"}, {"type": "system", "id": "gw"}, {"type": "human", "id": " "},
              {"type": "human"}]


@pytest.mark.parametrize("actor", BAD_ACTORS)
def test_owner_login_refuses_non_human_for_capital_and_mission(cap, actor):
    assert cap.owner.conn.execute("SELECT session_user").fetchone()[0] == "mbos_operator_ui"
    a = Jsonb(actor)
    mission = json.loads((ADD / "examples/mission/mission-unknown-target.example.json").read_text())
    for sql, args in (("SELECT mbos.capital_fund(5::numeric,%s,'x',%s,%s)", (a, [cap.pid], key())),
                      ("SELECT mbos.capital_withdraw(5::numeric,%s,'x',%s,%s)", (a, [cap.pid], key())),
                      ("SELECT mbos.set_mission(%s,%s,'x',%s,%s)", (Jsonb(mission), a, [cap.pid], key()))):
        with pytest.raises(errors.InsufficientPrivilege, match="as a human"):
            cap.owner.conn.execute(sql, args)
        cap.owner.conn.rollback()
    assert cap.db.connect("reader").execute("SELECT count(*) FROM mbos.capital_ledger").fetchone()[0] == 0
    cap.fund(10)                                    # a human still can
    assert cap.owner.verify_chain().ok


def test_campaign_set_revise_cancel_with_receipts_and_current_view(cap):
    body = _ex()
    assert not list(SCHEMA.iter_errors(body))
    cid = _set(cap, body)
    assert cid == body["campaign_id"]
    rev = _ex(title="5x8 trailer, price dropped", criteria={**body["criteria"], "max_price_usd": 1500})
    _set(cap, rev)
    rd = cap.db.connect("reader")
    row = rd.execute("SELECT revision, status, doc FROM mbos.v_campaigns_current").fetchall()
    assert len(row) == 1 and row[0][0] == 2 and row[0][1] == "ACTIVE"
    assert row[0][2]["title"] == rev["title"] and not list(SCHEMA.iter_errors(row[0][2]))
    k = key("cancel")
    cap.owner.conn.execute("SELECT mbos.cancel_campaign(%s,%s,'cancel',%s,%s)", (cid, cap.human, [cap.pid], k))
    assert cap.owner.conn.execute("SELECT mbos.cancel_campaign(%s,%s,'cancel',%s,%s)",
                                  (cid, cap.human, [cap.pid], k)).fetchone()[0] == cid         # idempotent replay
    cur = rd.execute("SELECT revision, status, doc FROM mbos.v_campaigns_current").fetchone()
    assert cur[0] == 3 and cur[1] == "CANCELLED" and cur[2]["title"] == rev["title"] and not list(SCHEMA.iter_errors(cur[2]))
    assert rd.execute("SELECT count(*) FROM mbos.campaigns").fetchone()[0] == 3                # history kept
    rcpts = rd.execute("SELECT effect, after_state->>'revision', after_state->>'status' FROM mbos.receipts "
                       "WHERE entity_type='campaign' AND entity_id=%s ORDER BY seq", (cid,)).fetchall()
    assert rcpts == [("create", "1", "ACTIVE"), ("update", "2", "ACTIVE"), ("update", "3", "CANCELLED")]
    assert rd.execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]
    with pytest.raises(errors.CheckViolation, match="already CANCELLED"):
        cap.owner.conn.execute("SELECT mbos.cancel_campaign(%s,%s,'again',%s,%s)", (cid, cap.human, [cap.pid], key()))


@pytest.mark.parametrize("level", ["ASSISTED_DEAL", "BOUNDED_AUTOPILOT"])
def test_autonomy_above_recommend_cannot_be_active(cap, level):
    body = _ex(level=level)
    if level == "BOUNDED_AUTOPILOT":
        body["autonomy"]["limits"] = {"max_total_spend_usd": 100, "max_offer_usd": 50,
                                    "expires_at": "2027-01-01T00:00:00Z"}
    assert not list(SCHEMA.iter_errors(body))                         # the contract allows it; storage must not
    with pytest.raises(errors.CheckViolation, match="campaign_active_only_up_to_recommend"):
        _set(cap, body)
    cap.owner.conn.rollback()
    _set(cap, {**body, "status": "PAUSED"})                           # stored only as non-ACTIVE
    # ...and an ACTIVE row cannot be smuggled in by revising a paused one
    with pytest.raises(errors.CheckViolation):
        _set(cap, {**body, "status": "ACTIVE"})
    for ok_level in ("WATCH_ONLY", "RECOMMEND"):
        _set(cap, _ex(campaign_id="cmp_" + "0" * 25 + ("1" if ok_level == "RECOMMEND" else "2"), level=ok_level))


def test_malformed_and_unauthorised_campaigns_are_refused(cap):
    for bad in ({k: v for k, v in _ex().items() if k != "criteria"}, _ex(status="BOGUS"), _ex(level="YOLO")):
        with pytest.raises(errors.CheckViolation):
            _set(cap, bad)
        cap.owner.conn.rollback()
    autopilot = _ex(level="BOUNDED_AUTOPILOT", status="PAUSED")        # autopilot without limits
    with pytest.raises(errors.CheckViolation):
        _set(cap, autopilot)
    cap.owner.conn.rollback()
    for actor in BAD_ACTORS:
        with pytest.raises(errors.InsufficientPrivilege, match="as a human"):
            _set(cap, _ex(), actor=actor)
        cap.owner.conn.rollback()
    for role in ("agent_write", "gateway", "policy_admin", "reader"):
        with pytest.raises(errors.InsufficientPrivilege):
            cap.db.connect(role).execute("SELECT mbos.set_campaign(%s,%s,'x',%s,%s)",
                                         (Jsonb(_ex()), cap.human, [cap.pid], key()))
    with pytest.raises(errors.InsufficientPrivilege):
        cap.db.connect("agent_write").execute("INSERT INTO mbos.campaigns (campaign_id,revision,status,autonomy_level,"
                                              "body,created_by,provenance_ids) VALUES ('x',1,'ACTIVE','RECOMMEND','{}','a','{}')")
    assert cap.db.connect("reader").execute("SELECT count(*) FROM mbos.campaigns").fetchone()[0] == 0


def test_campaigns_are_insert_only(cap):
    _set(cap, _ex())
    cap.owner.conn.commit()
    for sql in ("UPDATE mbos.campaigns SET status='PAUSED'", "DELETE FROM mbos.campaigns"):
        with pytest.raises(Exception):
            cap.db.connect("dbos").execute(sql)
