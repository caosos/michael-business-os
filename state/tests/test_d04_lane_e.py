"""D-04 (migration 0007): Lane E requirements — PANIC interface, execution claims, gateway edges, budget caps."""

import threading

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import AGENT, GATEWAY, MICHAEL, key, make_areq, make_item, payload_hash, to_pending, tool_prov

SYSTEM = MICHAEL.__class__("system", "ops")


def _panic(store, level, target, engage, actor=MICHAEL, reason="test"):
    pid = tool_prov(store)
    return store.conn.execute("SELECT mbos.panic_set(%s,%s,%s,%s,%s,%s,%s)",
                              (level, target, engage, actor.as_json(), reason, [pid], key("panic"))).fetchone()[0]


def _current(conn):
    return sorted((lvl, tgt) for lvl, tgt in conn.execute("SELECT level, target FROM mbos.panic_current"))


def _approved(s, **over):
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid, **over)
    to_pending(s, areq, pid)
    appr = s.record_approval({"action_request_id": areq, "decision": "YES", "decider": "michael", "channel": "web",
                              "payload_hash_seen": payload_hash(s, areq), "scope": "once",
                              "auth_context": {"method": "web", "step_up": True}}, MICHAEL, "YES", key())
    return areq, appr, pid


# ---------------------------------------------------------------------------
# §1 PANIC
# ---------------------------------------------------------------------------
def test_bootstrap_is_frozen_and_only_approver_releases(db):
    r = db.connect("reader")
    assert _current(r) == [("L3", None)]
    ev = r.execute("SELECT revision, level, target, engage, reason, receipt_id FROM mbos.panic_events").fetchall()
    assert len(ev) == 1 and ev[0][1:5] == ("L3", None, True, "initial state") and ev[0][5].startswith("rcpt_")
    for role in ("gateway", "policy_admin"):
        with pytest.raises(errors.InsufficientPrivilege):
            _panic(db.store(role), "L3", None, False)
    for role in ("agent_write", "reader"):
        with pytest.raises(errors.InsufficientPrivilege):
            _panic(db.store(role), "L3", None, True)
    _panic(db.store("approver"), "L3", None, False, reason="Michael releases")
    assert _current(r) == []


def test_panic_levels_validation_and_engage_roles(db):
    ui = db.store("approver")
    _panic(ui, "L3", None, False)
    gw, ops = db.store("gateway"), db.store("policy_admin")
    _panic(gw, "L2", "money.*", True, GATEWAY, "403 storm")
    _panic(ops, "L2", "category:sms", True, SYSTEM, "carrier block")
    _panic(gw, "L1", "agent-07-marketing", True, GATEWAY, "loop")
    assert _current(gw.conn) == [("L1", "agent-07-marketing"), ("L2", "category:sms"), ("L2", "money.*")]
    blocks = gw.conn.execute("SELECT mbos.panic_blocks('agent-06','money.payment.send','money')").fetchone()[0]
    assert blocks == ["PANIC_L2_CAPABILITY:money.*"]
    for bad in (("L3", "x", True), ("L1", None, True), ("L9", "x", True)):
        with pytest.raises(psycopg.Error) as ei:
            _panic(gw, *bad)
        assert ei.value.sqlstate == "MB004"
    with pytest.raises(psycopg.Error):
        _panic(gw, "L1", "a", True, GATEWAY, "   ")
    _panic(ui, "L2", "money.*", False, MICHAEL, "resolved")
    assert ("L2", "money.*") not in _current(gw.conn)
    assert gw.verify_chain().ok


def test_l3_engage_cancels_unstarted_approved_requests(db):
    s = db.store()
    _panic(db.store("approver"), "L3", None, False)
    a1, _, _ = _approved(s)
    a2, appr2, pid = _approved(s)
    db.store("gateway").set_action_status(a2, "executing", "ACTION_EXECUTING", GATEWAY, "started", [pid], key(),
                                          extra={"approval_id": appr2})
    rid = _panic(db.store("gateway"), "L3", None, True, GATEWAY, "PANIC")
    st = dict(s.conn.execute("SELECT action_request_id, status FROM mbos.action_requests").fetchall())
    assert st[a1] == "cancelled_by_freeze" and st[a2] == "executing"   # started work is the gateway's call
    n = s.conn.execute("""SELECT count(*) FROM mbos.receipts WHERE type='KILL_SWITCH_CHANGED'
                          AND action_request_id = %s AND after_state->>'status' = 'cancelled_by_freeze'""", (a1,))
    assert n.fetchone()[0] == 1 and rid.startswith("rcpt_")
    assert s.verify_chain().ok


def test_panic_current_fails_closed_when_tampered(db):
    _panic(db.store("approver"), "L3", None, False)
    su = db.connect("superuser")
    with su.transaction():
        su.execute("SET LOCAL session_replication_role = replica")
        su.execute("""UPDATE mbos.panic_state SET body = jsonb_set(body, '{global,state}', '"RUNNING"')
                      WHERE revision = 1""")
        su.execute("DELETE FROM mbos.panic_state WHERE revision = 2")
    rows = db.connect("reader").execute("SELECT level, reason FROM mbos.panic_current").fetchall()
    assert rows == [("L3", "UNREADABLE: checksum mismatch")]


# ---------------------------------------------------------------------------
# §2 execution claims
# ---------------------------------------------------------------------------
def test_execution_claim_lifecycle(db):
    s = db.store()
    areq, appr, pid = _approved(s)
    gw = db.store("gateway")
    with gw.transaction():   # claim in the same transaction as ACTION_EXECUTING (07 F-6)
        gw.set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "guard ok", [pid], key(),
                             extra={"approval_id": appr})
        assert gw.conn.execute("SELECT * FROM mbos.effector_claim(%s, %s)", (areq, Jsonb({"b": 1}))).fetchone() \
            == ("executing", None, False)
    assert gw.conn.execute("SELECT * FROM mbos.effector_claim(%s)", (areq,)).fetchone() == ("executing", None, True)
    resp = {"provider": "dry-run", "provider_msg_id": "dry_9", "status": "simulated", "dry_run": True}
    assert gw.conn.execute("SELECT mbos.effector_finish(%s,'executed','dry-run','dry_9',%s)",
                           (areq, Jsonb(resp))).fetchone()[0] == resp
    assert gw.conn.execute("SELECT mbos.effector_finish(%s,'executed','dry-run','dry_9',%s)",
                           (areq, Jsonb(resp))).fetchone()[0] == resp           # idempotent replay
    with pytest.raises(psycopg.Error) as ei:
        gw.conn.execute("SELECT mbos.effector_finish(%s,'failed',NULL,NULL,NULL)", (areq,))
    assert ei.value.sqlstate == "MB409"
    row = gw.conn.execute("SELECT state, finished_at IS NOT NULL FROM mbos.effector_calls").fetchone()
    assert row == ("executed", True)
    owner = db.connect("owner")
    for sql in ("UPDATE mbos.effector_calls SET state = 'failed'", "DELETE FROM mbos.effector_calls",
                "TRUNCATE mbos.effector_calls"):
        with pytest.raises(psycopg.Error) as ei:
            owner.execute(sql)
        assert ei.value.sqlstate == "MB001"
    with pytest.raises(errors.CheckViolation):   # dry-run only, still
        _a2, _ap2, _ = _approved(s)
        gw.set_action_status(_a2, "executing", "ACTION_EXECUTING", GATEWAY, "go", [pid], key(), extra={"approval_id": _ap2})
        gw.conn.execute("SELECT * FROM mbos.effector_claim(%s)", (_a2,))
        gw.conn.execute("SELECT mbos.effector_finish(%s,'executed','pm','x',%s)", (_a2, Jsonb({"dry_run": False})))


def test_claims_are_gateway_only_and_single_shot_still_works(db):
    s = db.store()
    areq, appr, pid = _approved(s)
    for role in ("agent_write", "approver"):
        with pytest.raises(errors.InsufficientPrivilege):
            db.connect(role).execute("SELECT * FROM mbos.effector_claim(%s)", (areq,))
    s.set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "go", [pid], key(), extra={"approval_id": appr})
    resp = {"provider": "dry-run", "provider_msg_id": "m", "status": "simulated", "dry_run": True}
    s.conn.execute("SELECT * FROM mbos.record_effector_call(%s,'dry-run','m','{}',%s)", (areq, Jsonb(resp)))
    assert s.conn.execute("SELECT state FROM mbos.effector_calls").fetchone()[0] == "executed"


# ---------------------------------------------------------------------------
# §3 gateway edges
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("to_status,rtype", [("expired", "POLICY_DECIDED"), ("failed", "ACTION_FAILED")])
def test_gateway_edges_from_approved(db, to_status, rtype):
    s = db.store()
    areq, appr, pid = _approved(s)
    extra = {"approval_id": appr, "effect": "none",
             "effector_response": {"provider": "gateway", "status": "refused", "dry_run": True}}
    with pytest.raises(errors.InsufficientPrivilege):
        db.store("approver").set_action_status(areq, to_status, rtype, MICHAEL, "x", [pid], key(), extra=extra)
    db.store("gateway").set_action_status(areq, to_status, rtype, GATEWAY, f"G: {to_status}", [pid], key(), extra=extra)


def test_executing_to_cancelled_by_freeze(db):
    s = db.store()
    areq, appr, pid = _approved(s)
    gw = db.store("gateway")
    gw.set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "go", [pid], key(), extra={"approval_id": appr})
    gw.set_action_status(areq, "cancelled_by_freeze", "KILL_SWITCH_CHANGED", GATEWAY, "PANIC re-read: frozen", [pid], key())


# ---------------------------------------------------------------------------
# §4 budget
# ---------------------------------------------------------------------------
COMMS = {"per_action": 2, "daily": 5, "global_daily": 100, "velocity_per_hour": None, "tz": "America/Chicago",
         "categories": ["message", "sms", "phone_call", "email"]}


def _reserve(store, areq, amount, caps, mode="dry_run"):
    return store.conn.execute("SELECT mbos.budget_reserve_caps(%s,%s::numeric,'USD',%s,%s,%s,'reserve',%s::text[],%s)",
                              (areq, amount, Jsonb(caps), mode, GATEWAY.as_json(), [tool_prov(store)], key("b"))).fetchone()[0]


def test_bucket_daily_cap_spans_categories(db):
    s = db.store()
    item_id, pid = make_item(s)
    sms = [make_areq(s, item_id, pid, category="sms", capability="comms.sms.send") for _ in range(3)]
    email = [make_areq(s, item_id, pid, category="email") for _ in range(3)]
    gw = db.store("gateway")
    for a in sms + email[:2]:
        _reserve(gw, a, 1, COMMS)                                   # 5 x $1 across sms + email
    with pytest.raises(psycopg.Error) as ei:
        _reserve(gw, email[2], 1, COMMS)
    assert ei.value.sqlstate == "MB006" and "daily cap" in ei.value.diag.message_primary
    assert gw.conn.execute("SELECT mbos.budget_exposure_day(ARRAY['sms','email'],'USD','dry_run','America/Chicago')"
                           ).fetchone()[0] == 5


def test_cap_rules(db):
    s = db.store()
    item_id, pid = make_item(s)
    a = make_areq(s, item_id, pid, category="sms", capability="comms.sms.send")
    gw = db.store("gateway")
    for caps, why in (({**COMMS, "per_action": 0.5}, "per_action"),
                      ({k: v for k, v in COMMS.items() if k != "velocity_per_hour"}, "missing"),
                      ({**COMMS, "daily": None}, "missing"),
                      ({**COMMS, "categories": ["email"]}, "bucket")):
        with pytest.raises(psycopg.Error) as ei:
            _reserve(gw, a, 1, caps)
        assert ei.value.sqlstate == "MB006", why
    with pytest.raises(psycopg.Error):
        _reserve(gw, a, 1, COMMS, mode="live")                     # live capped at $0
    _reserve(gw, a, 0, COMMS, mode="live")                        # zero-cost live is fine
    _reserve(gw, a, 0.0125, COMMS)                                # sub-cent kept exactly
    assert gw.conn.execute("SELECT max(amount) FROM mbos.budget_ledger WHERE mode='dry_run'").fetchone()[0] == \
        __import__("decimal").Decimal("0.012500")
    with pytest.raises(errors.InsufficientPrivilege):
        _reserve(db.store("agent_write"), a, 0, COMMS)


def test_velocity_counts_unreleased_reservations(db):
    s = db.store()
    item_id, pid = make_item(s)
    money = {"per_action": 500, "daily": 10000, "global_daily": 10000, "velocity_per_hour": 300, "tz": "UTC",
             "categories": ["offer", "money", "purchase", "external_commitment"]}
    kw = dict(category="purchase", capability="money.purchase", reversibility="irreversible")
    a = [make_areq(s, item_id, pid, **kw) for _ in range(3)]
    gw = db.store("gateway")
    r1 = _reserve(gw, a[0], 200, money)
    with pytest.raises(psycopg.Error) as ei:
        _reserve(gw, a[1], 200, money)
    assert "velocity" in ei.value.diag.message_primary
    gw.budget_settle(r1, "release", None, GATEWAY, "cancelled", [pid], key())
    _reserve(gw, a[1], 200, money)                                 # released reservations stop counting


def test_parallel_approvals_never_overshoot(db):
    s = db.store()
    item_id, pid = make_item(s)
    caps = {**COMMS, "per_action": 1, "daily": 25, "global_daily": 25}
    areqs = [make_areq(s, item_id, pid, category=c, capability="comms.x")
             for c in ("sms", "email", "message", "phone_call") * 25]
    ok = []

    def go(a):
        try:
            ok.append(_reserve(db.store("gateway"), a, 1, caps))
        except psycopg.Error as e:
            assert e.sqlstate == "MB006"

    ts = [threading.Thread(target=go, args=(a,)) for a in areqs]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(ok) == 25
    assert s.conn.execute("SELECT sum(amount) FROM mbos.budget_ledger").fetchone()[0] == 25
    assert s.verify_chain().ok


# ---------------------------------------------------------------------------
# D-11: action-count velocity
# ---------------------------------------------------------------------------
MONEY = {"per_action": 1500, "daily": 100000, "global_daily": 100000, "velocity_per_hour": None,
         "velocity_actions_per_hour": 3, "tz": "America/Chicago",
         "categories": ["offer", "money", "purchase", "external_commitment"]}


def test_velocity_actions_counts_unreleased_incl_zero_amount(db):
    s = db.store()
    item_id, pid = make_item(s)
    kw = dict(category="offer", capability="money.offer.make", reversibility="irreversible")
    a = [make_areq(s, item_id, pid, **kw) for _ in range(5)]
    gw = db.store("gateway")
    r = [_reserve(gw, a[0], 0, MONEY), _reserve(gw, a[1], 10, MONEY), _reserve(gw, a[2], 0, MONEY)]   # 3 actions
    with pytest.raises(psycopg.Error) as ei:
        _reserve(gw, a[3], 0, MONEY)                              # a zero-amount 4th action still counts
    assert ei.value.sqlstate == "MB006" and "action velocity" in ei.value.diag.message_primary
    gw.budget_settle(r[0], "release", None, GATEWAY, "cancelled", [pid], key())
    _reserve(gw, a[3], 0, MONEY)                                  # a released reservation frees a slot
    assert gw.conn.execute("SELECT mbos.budget_velocity_actions_hour(%s::text[], 'USD', 'dry_run')",
                           (MONEY["categories"],)).fetchone()[0] == 3


def test_velocity_actions_optional_and_validated(db):
    s = db.store()
    item_id, pid = make_item(s)
    a = make_areq(s, item_id, pid, category="sms", capability="comms.sms.send")
    gw = db.store("gateway")
    _reserve(gw, a, 0, COMMS)                                     # key absent: no count cap (05's current calls)
    _reserve(gw, make_areq(s, item_id, pid, category="sms", capability="comms.sms.send"), 0,
             {**COMMS, "velocity_actions_per_hour": None})
    for bad in ("3", -1, 2.5):
        with pytest.raises(psycopg.Error) as ei:
            _reserve(gw, make_areq(s, item_id, pid, category="sms", capability="comms.sms.send"), 0,
                     {**COMMS, "velocity_actions_per_hour": bad})
        assert ei.value.sqlstate == "MB006", bad


def test_velocity_actions_never_overshoot_in_parallel(db):
    s = db.store()
    item_id, pid = make_item(s)
    areqs = [make_areq(s, item_id, pid, category=c, capability="money.x", reversibility="irreversible")
             for c in ("offer", "money", "purchase", "external_commitment") * 10]
    ok = []

    def go(x):
        try:
            ok.append(_reserve(db.store("gateway"), x, 1, MONEY))
        except psycopg.Error as e:
            assert e.sqlstate == "MB006"

    ts = [threading.Thread(target=go, args=(x,)) for x in areqs]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(ok) == 3
