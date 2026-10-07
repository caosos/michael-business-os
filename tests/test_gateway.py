"""Action Gateway + execution guard: governance acceptance tests (05 §17 / integration §8 B, A7, A9)."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

import pytest

from mbos_governance import contracts
from mbos_governance.effectors import DryRunEffector, EffectorRefused, GuardToken
from mbos_governance.gateway import GatewayRefused
from mbos_governance.ids import fmt_ts, new_id, payload_hash

from .conftest import CATEGORY_CAPABILITY


def receipt_types(env, areq):
    return [r["type"] for r in env.store.receipts(areq)]


def assert_ledger_sound(env):
    ok, msg = env.store.verify_chain()
    assert ok, msg
    for r in env.store.receipts():
        contracts.require_valid("receipt", r)
        if "effector_response" in r:
            assert r["effector_response"]["dry_run"] is True, r  # A7: 100% dry-run
    conn = sqlite3.connect(env.store.path)
    for (body,) in conn.execute("SELECT body FROM provenance"):
        contracts.require_valid("provenance", json.loads(body))


# ---------------------------------------------------------------- happy path
def test_yes_executes_once_dry_run_with_full_receipt_chain(env):
    ar = env.approved("email")
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "executed" and res.effector_response["dry_run"] is True
    assert receipt_types(env, ar["action_request_id"]) == [
        "ACTION_PROPOSED", "POLICY_DECIDED", "APPROVAL_REQUESTED", "APPROVAL_DECIDED", "BUDGET_RESERVED",
        "ACTION_EXECUTING", "BUDGET_COMMITTED", "ACTION_EXECUTED"]
    executed = env.store.receipts(ar["action_request_id"])[-1]
    assert executed["approval_id"] and executed["effector_response"]["provider_msg_id"].startswith("dryrun_")
    assert executed["payload_hash"] == ar["payload_hash"]
    assert_ledger_sound(env)


def test_full_chain_reconstructable(env):
    """§17 #27: why -> asked -> policy -> approved -> executed, from the ledger alone."""
    ar = env.approved("purchase", estimated_cost={"amount": 250, "currency": "USD"})
    env.gw.execute(ar["action_request_id"])
    rs = {r["type"]: r for r in env.store.receipts(ar["action_request_id"])}
    assert set(ar["provenance_ids"]) <= set(rs["ACTION_PROPOSED"]["provenance_ids"])          # why
    assert rs["POLICY_DECIDED"]["details"]["decision"] == "require_approval"                  # policy
    assert rs["APPROVAL_DECIDED"]["actor"] == {"type": "human", "id": "michael"}              # approved
    assert rs["BUDGET_COMMITTED"]["budget_effect"]["amount"] == 250                            # cost
    assert rs["ACTION_EXECUTED"]["effect"] == "pay"                                            # executed


# ---------------------------------------------------------------- gating
@pytest.mark.parametrize("category", sorted(CATEGORY_CAPABILITY))
def test_every_category_blocked_without_approval(env, category):
    """§17 #2: each of the 11 gated categories without approval -> blocked + receipted."""
    ar = env.propose(category)
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and any("NO_APPROVAL" in r for r in res.reasons)
    assert receipt_types(env, ar["action_request_id"])[-1] == "POLICY_DECIDED"
    assert env.store.get_claim(env.store._conn(), ar["idempotency_key"]) is None


@pytest.mark.parametrize("category", sorted(CATEGORY_CAPABILITY))
def test_every_category_executes_dry_run_with_approval(env, category):
    ar = env.approved(category)
    assert env.gw.execute(ar["action_request_id"]).outcome == "executed"


def test_no_never_executes(env):
    ar = env.propose("sms")
    env.gw.record_approval(env.approval(ar, "NO"))
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and res.status == "rejected"


def test_hold_never_executes(env):
    ar = env.propose("sms")
    assert env.gw.record_approval(env.approval(ar, "HOLD")).status == "held"
    env.clock.advance(hours=13)  # past hold_until — still never auto-executes
    assert env.gw.execute(ar["action_request_id"]).outcome == "refused"


def test_yes_after_hold_executes(env):
    ar = env.propose("email")
    env.gw.record_approval(env.approval(ar, "HOLD"))
    assert env.gw.record_approval(env.approval(ar, "YES")).status == "approved"
    assert env.gw.execute(ar["action_request_id"]).outcome == "executed"


def test_modify_closes_original_and_new_request_is_gated(env):
    ar = env.propose("email")
    new = env.ar("email", payload={"to_ref": "relay:EXAMPLE-0001", "template_id": "t2"},
                 derived_from=ar["action_request_id"])
    appr = env.approval(ar, "MODIFY", modifications={"diff": {"template_id": "t2"},
                                                      "new_action_request_id": new["action_request_id"],
                                                      "new_payload_hash": new["payload_hash"]})
    assert env.gw.record_approval(appr).status == "rejected"
    assert env.gw.execute(ar["action_request_id"]).outcome == "refused"
    assert env.gw.propose(new, new["proposed_by"]).outcome == "pending_approval"
    assert env.gw.execute(new["action_request_id"]).outcome == "refused"  # needs its own YES
    env.gw.record_approval(env.approval(new))
    assert env.gw.execute(new["action_request_id"]).outcome == "executed"


def test_later_decision_supersedes_yes(env):
    ar = env.propose("email")
    env.gw.record_approval(env.approval(ar, "HOLD"))
    env.gw.record_approval(env.approval(ar, "YES"))
    with pytest.raises(GatewayRefused):  # approved requests take no further decisions
        env.gw.record_approval(env.approval(ar, "NO"))


# ---------------------------------------------------------------- approval validation
@pytest.mark.parametrize("over,reason", [
    ({"decider": "agent-06-communications"}, "DECIDER_NOT_APPROVER"),
    ({"channel": "sms_reply"}, "CHANNEL_NOT_ALLOWED"),
    ({"scope": "standing_rule"}, "SCOPE_NOT_ALLOWED"),
    ({"auth_context": {"method": "webauthn", "step_up": False}}, "STEP_UP_REQUIRED"),
    ({"auth_context": {"step_up": True}}, "AUTH_CONTEXT_REQUIRED"),
    ({"payload_hash_seen": "sha256:" + "1" * 64}, "APPROVAL_PAYLOAD_HASH_MISMATCH"),
])
def test_invalid_yes_is_recorded_but_not_executable(env, over, reason):
    ar = env.propose("money")  # money => step-up required
    res = env.gw.record_approval(env.approval(ar, **over))
    assert res.status == "pending_approval" and any(reason in r for r in res.reasons)
    out = env.gw.execute(ar["action_request_id"])
    assert out.outcome == "refused"


def test_step_up_required_for_irreversible(env):
    ar = env.propose("email", reversibility="irreversible")
    res = env.gw.record_approval(env.approval(ar, auth_context={"method": "telegram_user_id", "step_up": False}))
    assert "STEP_UP_REQUIRED" in res.reasons


def test_expired_approval_refused(env):
    """§17 #7."""
    ar = env.propose("email")
    env.gw.record_approval(env.approval(ar, expires_at=fmt_ts(env.clock() + timedelta(minutes=30))))
    env.clock.advance(minutes=31)
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and res.status == "expired"
    assert any("APPROVAL_EXPIRED" in r for r in res.reasons)


def test_approval_ttl_capped_by_policy(env):
    ar = env.propose("email")
    env.gw.record_approval(env.approval(ar, expires_at=fmt_ts(env.clock() + timedelta(days=30))))
    env.clock.advance(hours=25)  # policy max_approval_ttl_seconds = 24h
    assert any("APPROVAL_EXPIRED" in r for r in env.gw.execute(ar["action_request_id"]).reasons)


def test_expired_action_request_refused(env):
    ar = env.approved("email", expires_at=fmt_ts(datetime(2026, 10, 7, 16, 0, tzinfo=timezone.utc)))
    env.clock.advance(hours=2)
    res = env.gw.execute(ar["action_request_id"])
    assert res.status == "expired" and any("ACTION_REQUEST_EXPIRED" in r for r in res.reasons)


# ---------------------------------------------------------------- payload hash (bait and switch)
def test_payload_mutated_after_approval_refused(env):
    """§17 #8."""
    ar = env.approved("sms")
    conn = sqlite3.connect(env.store.path)
    body = json.loads(conn.execute("SELECT body FROM action_requests WHERE action_request_id=?",
                                   (ar["action_request_id"],)).fetchone()[0])
    body["payload"]["template_id"] = "send-500-deposit"
    conn.execute("UPDATE action_requests SET body=? WHERE action_request_id=?", (json.dumps(body), ar["action_request_id"]))
    conn.commit()
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and res.status == "failed"
    assert any("PAYLOAD_MUTATED_AFTER_PROPOSAL" in r for r in res.reasons)


def test_payload_hash_mismatch_rejected_at_proposal(env):
    ar = env.ar("email")
    ar["payload_hash"] = "sha256:" + "a" * 64
    assert env.gw.propose(ar, ar["proposed_by"]).reasons[0] == "PAYLOAD_HASH_MISMATCH"


# Golden vectors produced by Agent 01's mbos.hashing.sha256_of (agent-01-coordinator@bed7609)
# and confirmed identical with Agent 06's operator_ui.util.canonical_json (agent-06@3e51ba4).
R3_VECTORS = [
    ({"offer": 850.0}, "sha256:74a32f5ce8dbf6acfb239519e6f1f628b41128af54ecc80773199f99fda89492"),
    ({"offer": 850}, "sha256:8a3d480d3aabd209ab8e7241995c63ae272dbe3c5d5289e6478822a54f06994e"),
    ({"to_ref": "relay:EXAMPLE-0001", "template_id": "seller_condition_q_v1", "offer": 1050},
     "sha256:c94d8a80ad5387b3118c9db7379a2790a100c2d61466c6fde3a68219e64a7364"),
    ({"note": "caf\u00e9 \u2713", "n": [1, 2.5, {"b": None, "a": True}]},
     "sha256:a7e3d4627629234cd1a58e46f728e5de16e83314f18af7dffb400ffb4fa3ec18"),
]


@pytest.mark.parametrize("payload,expected", R3_VECTORS)
def test_payload_hash_matches_r3_cross_lane_vectors(payload, expected):
    """Ruling R3: byte-identical canonical JSON with lanes 01 and 06."""
    assert payload_hash(payload) == expected


def test_float_money_payload_executes(env):
    """R3: money values are JSON numbers; a float payload round-trips and executes."""
    ar = env.approved("offer", payload={"listing_ref": "x", "offer": 850.0})
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "executed"
    stored = env.store.get_action_request(None, ar["action_request_id"])
    assert stored["payload"]["offer"] == 850.0 and isinstance(stored["payload"]["offer"], float)
    assert payload_hash(stored["payload"]) == ar["payload_hash"]


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_json_numbers_refused(env, bad):
    ar = env.ar("email")
    ar["payload"] = {"offer": bad}
    with pytest.raises(GatewayRefused, match="PAYLOAD_NOT_HASHABLE"):
        env.gw.propose(ar, ar["proposed_by"])


def test_r7_coordinator_may_propose_email_and_sms_but_still_gated(env):
    for cat in ("email", "sms"):
        ar = env.ar(cat, proposed_by="agent-01-coordinator")
        res = env.gw.propose(ar, "agent-01-coordinator")
        assert res.outcome == "pending_approval", res
        assert env.gw.execute(ar["action_request_id"]).outcome == "refused"  # no YES yet
        env.gw.record_approval(env.approval(ar))
        assert env.gw.execute(ar["action_request_id"]).outcome == "executed"
    call = env.ar("phone_call", proposed_by="agent-01-coordinator")
    assert any("CAPABILITY_NOT_HELD" in r for r in env.gw.propose(call, "agent-01-coordinator").reasons)


# ---------------------------------------------------------------- idempotency
def test_double_delivery_calls_effector_once(env, monkeypatch):
    """§17 #15."""
    calls = []
    orig = DryRunEffector._execute
    monkeypatch.setattr(DryRunEffector, "_execute", lambda self, t, a: calls.append(1) or orig(self, t, a))
    ar = env.approved("sms")
    first = env.gw.execute(ar["action_request_id"])
    second = env.gw.execute(ar["action_request_id"])
    assert first.outcome == "executed" and second.outcome == "duplicate"
    assert second.effector_response == first.effector_response and len(calls) == 1


def test_crash_in_flight_is_never_blind_retried(env, monkeypatch):
    """§17 #16 (wave-one form): a claim stuck in 'executing' blocks re-execution."""
    ar = env.approved("sms")

    def crash(self, cur, *a, **k):
        raise RuntimeError("simulated crash after effector call")
    monkeypatch.setattr(type(env.store), "finish_claim", crash)
    with pytest.raises(RuntimeError):
        env.gw.execute(ar["action_request_id"])
    monkeypatch.undo()
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and "reconciliation required" in res.reasons[0]


def test_duplicate_proposal_collapses(env):
    ar = env.propose("email")
    dup = env.ar("email", idempotency_key=ar["idempotency_key"])
    res = env.gw.propose(dup, dup["proposed_by"])
    assert res.outcome == "duplicate" and res.action_request_id == ar["action_request_id"]


# ---------------------------------------------------------------- budget
def test_max_cost_over_per_action_cap_refused(env):
    """§17 #9."""
    ar = env.propose("purchase", estimated_cost={"amount": 100, "currency": "USD"},
                     max_cost={"amount": 1500.01, "currency": "USD"})
    res = env.gw.record_approval(env.approval(ar))
    assert any("BUDGET_PER_ACTION_CAP" in r for r in res.reasons)
    assert any("BUDGET_PER_ACTION_CAP" in r for r in env.gw.execute(ar["action_request_id"]).reasons)


def test_daily_cap_is_hard(env):
    """§17 #10."""
    a = env.approved("purchase", estimated_cost={"amount": 1000, "currency": "USD"})
    b = env.propose("purchase", estimated_cost={"amount": 600, "currency": "USD"})
    env.gw.record_approval(env.approval(b))
    assert env.gw.execute(a["action_request_id"]).outcome == "executed"
    res = env.gw.execute(b["action_request_id"])
    assert res.outcome == "refused" and any("BUDGET_DAILY_CAP:money" in r for r in res.reasons)


def test_velocity_cap(env):
    """§17 #12: N+1 money actions within the hour -> refused (N=3)."""
    ok = [env.approved("money", estimated_cost={"amount": 1, "currency": "USD"}) for _ in range(3)]
    fourth = env.propose("money", estimated_cost={"amount": 1, "currency": "USD"})
    assert "BUDGET_VELOCITY_CAP:money" in env.gw.record_approval(env.approval(fourth)).reasons
    assert all(env.gw.execute(a["action_request_id"]).outcome == "executed" for a in ok)


def test_parallel_approvals_never_overshoot(env):
    """§17 #11: many concurrent approvals jointly exceeding the cap never commit past it."""
    env.policy_edit(lambda d: d["budgets"]["velocity"].__setitem__("money_bucket_actions_per_hour", 1000))
    ars = [env.propose("purchase", estimated_cost={"amount": 40, "currency": "USD"}) for _ in range(100)]
    errors = []

    def worker(ar):
        try:
            env.gw.record_approval(env.approval(ar))
            env.gw.execute(ar["action_request_id"])
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)
    threads = [threading.Thread(target=worker, args=(a,)) for a in ars]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors, errors[:3]
    conn = sqlite3.connect(env.store.path)
    committed = conn.execute("SELECT COALESCE(SUM(amount_micros),0) FROM budget_reservations "
                             "WHERE state IN ('reserved','committed')").fetchone()[0]
    executed = conn.execute("SELECT COUNT(*) FROM action_requests WHERE status='executed'").fetchone()[0]
    assert committed <= 1500 * 1_000_000 and executed == 37  # floor(1500/40)
    assert_ledger_sound(env)


def test_reservation_released_on_expiry(env):
    ar = env.propose("purchase")
    env.gw.record_approval(env.approval(ar, expires_at=fmt_ts(env.clock() + timedelta(minutes=5))))
    env.clock.advance(minutes=6)
    env.gw.execute(ar["action_request_id"])
    assert "BUDGET_RELEASED" in receipt_types(env, ar["action_request_id"])


# ---------------------------------------------------------------- capability / grant constraints
def test_caller_cannot_propose_as_another_agent(env):
    ar = env.ar("sms")
    res = env.gw.propose(ar, "agent-02-opportunity")
    assert res.outcome == "rejected" and res.reasons[0].startswith("CALLER_MISMATCH")


def test_grant_revoked_between_approval_and_execution(env):
    ar = env.approved("sms")
    env.policy_edit(lambda d: d["agent_grants"].__setitem__("agent-06-communications", ["comms.email.send"]))
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and any("G6:CAPABILITY_NOT_HELD" in r for r in res.reasons)


def test_quiet_hours_refuses_sms_and_calls(env):
    """§17 #14: 21:30 America/Chicago."""
    sms, call, email = env.approved("sms"), env.approved("phone_call"), env.approved("email")
    env.clock.now = datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc)
    assert "G6:QUIET_HOURS" in env.gw.execute(sms["action_request_id"]).reasons
    assert "G6:QUIET_HOURS" in env.gw.execute(call["action_request_id"]).reasons
    assert env.gw.execute(email["action_request_id"]).outcome == "executed"


def test_untrusted_input_forced_tier0_by_schema(env):
    """§17 #24 (schema half): tainted request cannot claim tier > 0."""
    ar = env.ar("sms", untrusted_inputs_present=True, tier=2)
    with pytest.raises(contracts.ContractViolation):
        env.gw.propose(ar, ar["proposed_by"])


def test_no_action_without_provenance(env):
    ar = env.ar("email", provenance_ids=[new_id("prov")])  # never recorded
    with pytest.raises(GatewayRefused, match="provenance"):
        env.gw.propose(ar, ar["proposed_by"])


# ---------------------------------------------------------------- PANIC
def test_l3_freeze_refuses_execution_and_proposals_and_cancels_queue(env):
    """§17 #18 + ADR-0005 L3: queued approved work becomes cancelled_by_freeze."""
    queued = env.approved("email")
    out = env.gw.engage_panic("L3", None, "michael", "test")
    assert out["cancelled"] == [queued["action_request_id"]]
    assert env.store.get_action_request(None, queued["action_request_id"])["status"] == "cancelled_by_freeze"
    ar = env.ar("email")
    res = env.gw.propose(ar, ar["proposed_by"])
    assert res.outcome == "rejected" and "PANIC_L3_FROZEN" in res.reasons
    assert "KILL_SWITCH_CHANGED" in [r["type"] for r in env.store.receipts()]
    assert_ledger_sound(env)


def test_l3_freeze_between_approval_and_execute(env):
    ar = env.approved("email")
    env.panic.mutate("L3", None, True, "michael", "out-of-band freeze")  # e.g. CLI with DB down
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and "G7:PANIC_L3_FROZEN" in res.reasons


def test_freeze_after_guard_before_effector(env, monkeypatch):
    ar = env.approved("email")
    real = env.panic.read
    calls = {"n": 0}

    def flip():
        calls["n"] += 1
        if calls["n"] == 2:  # 1st read = guard G7, 2nd = last-instant check
            env.panic.mutate("L3", None, True, "michael", "race")
        return real()
    monkeypatch.setattr(env.panic, "read", flip)
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "failed" and res.status == "cancelled_by_freeze"
    assert receipt_types(env, ar["action_request_id"])[-2:] == ["BUDGET_RELEASED", "ACTION_FAILED"]


@pytest.mark.parametrize("breakage", ["delete", "garbage", "tamper"])
def test_unreadable_panic_state_fails_closed(env, breakage):
    """§17 #20 / A9."""
    ar = env.approved("email")
    if breakage == "delete":
        env.panic.path.unlink()
    elif breakage == "garbage":
        env.panic.path.write_text("{")
    else:
        raw = json.loads(env.panic.path.read_text())
        raw["revision"] += 1
        env.panic.path.write_text(json.dumps(raw))
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and any(r.startswith("G7:PANIC_STATE_UNREADABLE") for r in res.reasons)
    new = env.ar("email")
    assert env.gw.propose(new, new["proposed_by"]).outcome == "rejected"


def test_unreadable_policy_fails_closed(env):
    ar = env.approved("email")
    env.policy_path.write_text("{")
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and all(any(r.startswith(f"G{i}:POLICY_UNREADABLE") for r in res.reasons)
                                            for i in range(1, 9))
    new = env.ar("email")
    assert env.gw.propose(new, new["proposed_by"]).outcome == "rejected"
    assert_ledger_sound(env)


def test_l2_money_freeze_leaves_comms_running(env):
    """§17 #19."""
    money, email = env.approved("money"), env.approved("email")
    env.gw.engage_panic("L2", "money.*", "michael", "freeze money")
    assert "G7:PANIC_L2_CAPABILITY:money.*" in env.gw.execute(money["action_request_id"]).reasons
    assert env.gw.execute(email["action_request_id"]).outcome == "executed"


def test_l1_agent_freeze(env):
    pub, email = env.approved("publishing"), env.approved("email")
    env.gw.engage_panic("L1", "agent-07-marketing", "michael", "misbehaving")
    assert "G7:PANIC_L1_AGENT:agent-07-marketing" in env.gw.execute(pub["action_request_id"]).reasons
    assert env.gw.execute(email["action_request_id"]).outcome == "executed"


def test_release_requires_approver_and_reason(env):
    env.gw.engage_panic("L3", None, "agent-06-communications", "agents may freeze")
    with pytest.raises(GatewayRefused):
        env.gw.release_panic("L3", None, "agent-06-communications", "agents may not release")
    with pytest.raises(GatewayRefused):
        env.gw.release_panic("L3", None, "michael", "  ")
    env.gw.release_panic("L3", None, "michael", "all clear")
    assert not env.panic.read().globally_frozen


def test_release_refused_while_policy_unreadable(env):
    env.gw.engage_panic("L3", None, "michael", "x")
    env.policy_path.write_text("{")
    with pytest.raises(GatewayRefused):
        env.gw.release_panic("L3", None, "michael", "try")
    assert env.panic.read().globally_frozen


def test_release_rolled_back_if_receipt_fails(env, monkeypatch):
    env.gw.engage_panic("L3", None, "michael", "x")
    monkeypatch.setattr(type(env.store), "append_receipt", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(RuntimeError):
        env.gw.release_panic("L3", None, "michael", "try")
    assert env.panic.read().globally_frozen


def test_freeze_stands_even_if_receipt_fails(env, monkeypatch):
    monkeypatch.setattr(type(env.store), "append_receipt", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")))
    env.gw.engage_panic("L3", None, "michael", "db is down")
    assert env.panic.read().globally_frozen
    assert "db down" in env.gw._journal.read_text()


# ---------------------------------------------------------------- dry-run guard / bypass
def test_effector_rejects_forged_token(env):
    ar = env.approved("email")
    eff = DryRunEffector(env.gw._minter)
    forged = GuardToken(ar["action_request_id"], ar["payload_hash"], ar["idempotency_key"], True, "0" * 64)
    with pytest.raises(EffectorRefused):
        eff.execute(forged, ar)


def test_effector_refuses_live_even_with_valid_token(env):
    ar = env.approved("email")
    token = env.gw._minter.mint(ar["action_request_id"], ar["payload_hash"], ar["idempotency_key"], False)
    with pytest.raises(EffectorRefused):
        env.gw._effectors["dryrun"].execute(token, ar)


def test_effector_claiming_live_trips_l3_panic(env, monkeypatch):
    ar = env.approved("email")
    monkeypatch.setattr(DryRunEffector, "_execute",
                        lambda self, t, a: {"provider": "rogue", "status": "sent", "dry_run": False})
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "failed" and "DRY_RUN_INVARIANT_VIOLATED" in res.reasons[0]
    assert env.panic.read().globally_frozen
    last = env.store.receipts(ar["action_request_id"])[-1]
    assert last["type"] == "ACTION_FAILED" and last["effector_response"]["dry_run"] is False  # recorded truthfully


# ---------------------------------------------------------------- ledger integrity
def test_receipts_are_insert_only(env):
    env.approved("email")
    conn = sqlite3.connect(env.store.path)
    for sql in ("UPDATE receipts SET type='X'", "DELETE FROM receipts", "UPDATE approvals SET body='{}'",
                "DELETE FROM provenance"):
        with pytest.raises(sqlite3.IntegrityError, match="insert-only"):
            conn.execute(sql)


def test_tampering_detected(env):
    """§17 #28 / A3."""
    env.gw.execute(env.approved("email")["action_request_id"])
    assert env.store.verify_chain()[0]
    conn = sqlite3.connect(env.store.path)
    conn.execute("DROP TRIGGER receipts_no_update")  # attacker with DDL rights
    body = json.loads(conn.execute("SELECT body FROM receipts WHERE seq=2").fetchone()[0])
    body["intent"] = "nothing to see here"
    conn.execute("UPDATE receipts SET body=? WHERE seq=2", (json.dumps(body),))
    conn.commit()
    ok, msg = env.store.verify_chain()
    assert not ok and "seq 2" in msg
