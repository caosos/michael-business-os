"""End-to-end dry-run flow plus approval / provenance / role / budget invariants."""

import threading

import psycopg
import pytest
from psycopg import errors

from mbos_state.ids import new_id
from conftest import AGENT, GATEWAY, MICHAEL, key, make_areq, make_item, payload_hash, to_pending, tool_prov


def yes(areq, h, **over):
    a = {"action_request_id": areq, "decision": "YES", "decider": "michael", "channel": "web",
         "payload_hash_seen": h, "scope": "once", "auth_context": {"method": "webauthn", "step_up": True}}
    a.update(over)
    return a


def test_full_dry_run_flow_with_role_separation(db):
    agent, gw, ui = db.store("agent_write"), db.store("gateway"), db.store("approver")
    item_id, pid = make_item(agent, "RECOMMENDED")
    areq = make_areq(agent, item_id, pid)
    agent.transition_item(item_id, "AWAITING_APPROVAL", AGENT, "YES verdict -> ask Michael", [pid], key())
    to_pending(gw, areq, pid)
    appr = ui.record_approval(yes(areq, payload_hash(ui, areq)), MICHAEL, "Michael: YES", key())
    ui.transition_item(item_id, "APPROVED", MICHAEL, "approved", [pid], key())
    gw.transition_item(item_id, "ACTING", GATEWAY, "executing", [pid], key())
    gw.set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "guard passed", [pid], key(),
                         extra={"approval_id": appr})
    gw.set_action_status(areq, "executed", "ACTION_EXECUTED", GATEWAY, "dry-run send", [pid], key(),
                         extra={"approval_id": appr, "effect": "send", "tool_name": "comms-mock 0.1",
                                "effector_response": {"provider": "mock", "status": "accepted", "dry_run": True},
                                "details": {"kind": "comms"}})
    gw.transition_item(item_id, "ACTED", GATEWAY, "done", [pid], key())
    oid = agent.record_outcome({"item_id": item_id, "action_request_id": areq, "kind": "message_replied",
                                "provenance_ids": [pid]}, AGENT, "seller replied", key())
    st = agent.conn.execute("SELECT status FROM mbos.action_requests WHERE action_request_id=%s", (areq,)).fetchone()[0]
    assert st == "outcome_recorded" and oid.startswith("outc_")
    # approval decision is itself provenance (human)
    prov = agent.conn.execute("SELECT actor_type, human_actor FROM mbos.provenance WHERE approval_id=%s", (appr,))
    assert prov.fetchone() == ("human", "michael")
    # A7: zero live effects
    assert agent.conn.execute("SELECT count(*) FROM mbos.v_a7_live_effects").fetchone()[0] == 0
    assert agent.verify_chain().ok
    doc = agent.item_document(item_id)
    assert areq in doc["action_request_ids"] and appr in doc["approval_ids"] and oid in doc["outcome_ids"]


def test_role_boundaries(db):
    agent, gw, ui = db.store("agent_write"), db.store("gateway"), db.store("approver")
    item_id, pid = make_item(agent, "AWAITING_APPROVAL")
    areq = make_areq(agent, item_id, pid)
    with pytest.raises(errors.InsufficientPrivilege):      # agents cannot classify their own proposals
        agent.set_action_status(areq, "classified", "POLICY_DECIDED", AGENT, "self-approve", [pid], key())
    to_pending(gw, areq, pid)
    h = payload_hash(gw, areq)
    with pytest.raises(errors.InsufficientPrivilege):      # agents cannot approve
        agent.record_approval(yes(areq, h), MICHAEL, "forged", key())
    with pytest.raises(errors.InsufficientPrivilege):      # nor can the gateway
        gw.record_approval(yes(areq, h), MICHAEL, "forged", key())
    with pytest.raises(errors.InsufficientPrivilege):      # approver cannot execute
        ui.set_action_status(areq, "executing", "ACTION_EXECUTING", MICHAEL, "x", [pid], key())
    with pytest.raises(errors.InsufficientPrivilege):
        agent.publish_policy({"policy_key": "category:money", "decision": "deny", "created_by": "agent",
                              "reason": "x", "provenance_ids": [pid]}, AGENT, "x", key())
    with pytest.raises(errors.InsufficientPrivilege):
        db.store("reader").record_provenance(actor_type="system", basis="FACT", tool_name="t", tool_version="1")
    relay = db.connect("outbox_relay")
    with pytest.raises(errors.InsufficientPrivilege):
        relay.execute("SELECT count(*) FROM mbos.receipts")


def test_execution_requires_live_yes(db):
    s = db.store()
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid)
    to_pending(s, areq, pid)
    with pytest.raises(psycopg.Error) as ei:   # approved without any approval row
        s.set_action_status(areq, "approved", "APPROVAL_DECIDED", GATEWAY, "x", [pid], key(),
                            extra={"approval_id": new_id("appr")})
    assert ei.value.sqlstate in ("MB005", "23503")


def test_payload_hash_mismatch_voids_approval(db):
    s = db.store()
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid)
    to_pending(s, areq, pid)
    with pytest.raises(psycopg.Error) as ei:
        s.record_approval(yes(areq, "sha256:" + "99" * 32), MICHAEL, "stale card", key())
    assert ei.value.sqlstate == "MB005"


def test_irreversible_yes_requires_step_up_and_no_requires_reason(db):
    s = db.store()
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid)
    to_pending(s, areq, pid)
    h = payload_hash(s, areq)
    with pytest.raises(psycopg.Error) as ei:
        s.record_approval(yes(areq, h, auth_context={"method": "web"}), MICHAEL, "no step-up", key())
    assert ei.value.sqlstate == "MB005"
    with pytest.raises(psycopg.errors.CheckViolation):
        s.record_approval(yes(areq, h, decision="NO"), MICHAEL, "no reason", key())
    s.record_approval(yes(areq, h, decision="NO", reason="price too high"), MICHAEL, "NO", key())
    assert s.conn.execute("SELECT status FROM mbos.action_requests WHERE action_request_id=%s",
                          (areq,)).fetchone()[0] == "rejected"


def test_modify_creates_derived_request_and_closes_original(db):
    s = db.store()
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid)
    to_pending(s, areq, pid)
    with s.transaction():
        new = make_areq(s, item_id, pid, derived_from=areq, payload={"body": "Would you take $400?"})
        s.record_approval(yes(areq, payload_hash(s, areq), decision="MODIFY",
                              modifications={"diff": {"body": "changed"}, "new_action_request_id": new,
                                             "new_payload_hash": payload_hash(s, new)}), MICHAEL, "MODIFY", key())
    rows = dict(s.conn.execute("SELECT action_request_id, status FROM mbos.action_requests WHERE item_id=%s",
                               (item_id,)).fetchall())
    assert rows == {areq: "rejected", new: "drafted"}
    with pytest.raises(psycopg.Error):  # MODIFY pointing at a non-derived request is refused
        other = make_areq(s, item_id, pid)
        to_pending(s, other, pid)
        s.record_approval(yes(other, payload_hash(s, other), decision="MODIFY",
                              modifications={"new_action_request_id": new, "new_payload_hash": payload_hash(s, new)}),
                          MICHAEL, "bad MODIFY", key())


def test_hold_parks_and_never_executes(db):
    s = db.store()
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid)
    to_pending(s, areq, pid)
    s.record_approval(yes(areq, payload_hash(s, areq), decision="HOLD",
                          hold={"hold_until": "2026-10-08T12:00:00Z", "wake_on": ["time", "price_change"],
                                "renotify_after": "PT24H"}), MICHAEL, "HOLD", key())
    assert s.conn.execute("SELECT count(*) FROM mbos.v_hold_backlog").fetchone()[0] == 1
    with pytest.raises(psycopg.Error) as ei:   # held -> executing is not a legal edge
        s.set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "auto-exec", [pid], key())
    assert ei.value.sqlstate == "MB004"
    s.set_action_status(areq, "pending_approval", "APPROVAL_REQUESTED", GATEWAY, "wake: re-present", [pid], key())


def test_live_effect_receipt_rejected_in_wave_one(db):
    s = db.store()
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid)
    to_pending(s, areq, pid)
    appr = s.record_approval(yes(areq, payload_hash(s, areq)), MICHAEL, "YES", key())
    s.set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "go", [pid], key(), extra={"approval_id": appr})
    with pytest.raises(psycopg.errors.CheckViolation) as ei:
        s.set_action_status(areq, "executed", "ACTION_EXECUTED", GATEWAY, "LIVE send", [pid], key(),
                            extra={"approval_id": appr, "effect": "send",
                                   "effector_response": {"provider": "postmark", "dry_run": False}})
    assert "receipts_wave1_dry_run_only" in str(ei.value)


def test_tier_rules_enforced(db):
    s = db.store()
    item_id, pid = make_item(s)
    for over in ({"reversibility": "irreversible", "tier": 1},
                 {"reversibility": "reversible", "category": "money", "capability": "money.payment.send", "tier": 2},
                 {"reversibility": "reversible", "untrusted_inputs_present": True, "tier": 1}):
        with pytest.raises(psycopg.errors.CheckViolation):
            make_areq(s, item_id, pid, **over)


def test_provenance_rules(db):
    s = db.store()
    with pytest.raises(psycopg.errors.CheckViolation):  # resolves to nothing
        s.record_provenance(actor_type="agent", basis="INFERENCE", agent_name="agent-03")
    pid = tool_prov(s)
    base = {"type": "INJECTION_SUSPECTED", "actor": {"type": "agent", "id": "x"}, "intent": "t"}
    with pytest.raises(psycopg.errors.CheckViolation):
        s.append_receipt({**base, "idempotency_key": key(), "provenance_ids": []})
    with pytest.raises(psycopg.Error) as ei:
        s.append_receipt({**base, "idempotency_key": key(), "provenance_ids": [pid, new_id("prov")]})
    assert ei.value.sqlstate == "MB002"


def test_budget_never_exceeds_cap_under_parallel_reservations(db):
    s = db.store()
    item_id, pid = make_item(s)
    areqs = [make_areq(s, item_id, pid, category="purchase", capability="money.purchase", reversibility="irreversible")
             for _ in range(40)]
    ok, denied = [], []

    def reserve(a):
        g = db.store("gateway")
        try:
            ok.append(g.budget_reserve(a, 50, "USD", 1000, GATEWAY, "reserve", [pid], key("bud")))
        except psycopg.Error as e:
            assert e.sqlstate == "MB006"
            denied.append(a)

    threads = [threading.Thread(target=reserve, args=(a,)) for a in areqs]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 20 and len(denied) == 20
    assert s.conn.execute("SELECT mbos.budget_exposure('purchase','USD')").fetchone()[0] == 1000
    # releasing frees headroom; over-settling is refused
    s.budget_settle(ok[0], "release", None, GATEWAY, "cancelled", [pid], key())
    s.budget_reserve(denied[0], 50, "USD", 1000, GATEWAY, "retry", [pid], key())
    with pytest.raises(psycopg.Error) as ei:
        s.budget_settle(ok[1], "commit", 51, GATEWAY, "overspend", [pid], key())
    assert ei.value.sqlstate == "MB006"
    with pytest.raises(psycopg.Error) as ei:
        s.budget_reserve(denied[1], 1, "USD", None, GATEWAY, "no cap", [pid], key())
    assert ei.value.sqlstate == "MB006"
    assert s.verify_chain().ok


def test_policy_versions_are_append_only_and_sequential(db):
    p = db.store("policy_admin")
    pid = tool_prov(p)
    pol = {"policy_key": "category:sms", "category": "sms", "tier": 0, "decision": "require_approval",
           "created_by": "michael", "reason": "wave one", "provenance_ids": [pid]}
    p.publish_policy(pol, MICHAEL, "v1", key())
    p.publish_policy({**pol, "decision": "deny", "reason": "PANIC drill"}, MICHAEL, "v2", key())
    cur = p.conn.execute("SELECT version, decision FROM mbos.policy_current WHERE policy_key='category:sms'").fetchone()
    assert cur == (2, "deny")
    with pytest.raises(psycopg.errors.CheckViolation):
        p.publish_policy({**pol, "policy_key": "category:money", "category": "money", "decision": "allow"},
                         MICHAEL, "never auto-allow money", key())
