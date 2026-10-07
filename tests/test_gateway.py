"""Action Gateway + execution guard: governance acceptance tests (05 §17 / integration §8 B, A7, A9)."""
from __future__ import annotations

import json
import psycopg
from concurrent.futures import ThreadPoolExecutor
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
    for (doc,) in env.sql("SELECT doc FROM mbos.v_provenance_documents"):
        contracts.require_valid("provenance", doc)
    assert env.sql("SELECT count(*) FROM mbos.v_a7_live_effects")[0][0] == 0  # lane D's A7 audit view


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
    assert env.sql("SELECT count(*) FROM mbos.effector_calls WHERE action_request_id=%s", (ar["action_request_id"],))[0][0] == 0


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
    # Lane D requires the successor (derived_from) to exist before MODIFY is recorded.
    with pytest.raises(GatewayRefused, match="MODIFY must reference a new request"):
        env.gw.record_approval(appr)
    assert env.gw.propose(new, new["proposed_by"]).outcome == "pending_approval"
    assert env.gw.record_approval(appr).status == "rejected"
    assert env.gw.execute(ar["action_request_id"]).outcome == "refused"
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
def test_invalid_yes_is_refused_and_not_recorded(env, over, reason):
    """An invalid YES never becomes an approval row (lane D would refuse it too); a receipt notes it."""
    ar = env.propose("money")  # money => step-up required
    res = env.gw.record_approval(env.approval(ar, **over))
    assert res.outcome == "refused" and res.status == "pending_approval" and any(reason in r for r in res.reasons)
    assert env.sql("SELECT count(*) FROM mbos.approvals")[0][0] == 0
    note = env.store.receipts(ar["action_request_id"])[-1]
    assert note["type"] == "POLICY_DECIDED" and reason in " ".join(note["details"]["refused_approval"]["problems"])
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
    ar = env.approved("email", expires_at=fmt_ts(env.clock() + timedelta(hours=1)))
    env.clock.advance(hours=2)
    res = env.gw.execute(ar["action_request_id"])
    assert res.status == "expired" and any("ACTION_REQUEST_EXPIRED" in r for r in res.reasons)


# ---------------------------------------------------------------- payload hash (bait and switch)
def test_payload_mutated_after_approval_refused(env):
    """§17 #8."""
    ar = env.approved("sms")
    # Lane D freezes the payload column; only an attacker bypassing triggers can change it.
    env.tamper_payload(ar["action_request_id"], "template_id", "send-500-deposit")
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and res.status == "failed"
    assert any("PAYLOAD_MUTATED_AFTER_PROPOSAL" in r for r in res.reasons)


def test_payload_hash_mismatch_rejected_at_proposal(env):
    ar = env.ar("email")
    ar["payload_hash"] = "sha256:" + "a" * 64
    with pytest.raises(GatewayRefused, match="PAYLOAD_HASH_MISMATCH"):  # never stored (lane D: MB007)
        env.gw.propose(ar, ar["proposed_by"])


def test_float_money_payload_executes(env):
    """ADR-0010: money is a JSON number; float payloads hash and execute (850.0 == 850)."""
    ar = env.approved("offer", payload={"listing_ref": "x", "offer": 850.0})
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "executed"
    stored = env.store.action_request(ar["action_request_id"])
    assert stored["payload"]["offer"] == 850
    assert payload_hash(stored["payload"]) == ar["payload_hash"] == payload_hash({"listing_ref": "x", "offer": 850})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 2**53, "nul\x00"])
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

    def crash(*a, **k):
        raise RuntimeError("simulated crash after effector call")
    monkeypatch.setattr(type(env.store), "effector_finish", staticmethod(crash))
    with pytest.raises(RuntimeError):
        env.gw.execute(ar["action_request_id"])
    monkeypatch.undo()
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and "reconciliation required" in res.reasons[0]
    assert env.sql("SELECT state FROM mbos.effector_calls WHERE action_request_id=%s",
                   (ar["action_request_id"],))[0][0] == "executing"   # claim survives the crash for E-05


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
    with ThreadPoolExecutor(max_workers=20) as pool:   # 20 concurrent connections per role
        list(pool.map(worker, ars))
    assert not errors, errors[:3]
    spent = env.sql("SELECT coalesce(sum(reserved - released), 0) FROM mbos.v_budget_reservations")[0][0]
    executed = env.sql("SELECT count(*) FROM mbos.action_requests WHERE status='executed'")[0][0]
    assert spent <= 1500 and executed == 37  # floor(1500/40)
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
    env.clock.advance(hours=11, minutes=30)  # 15:00Z -> 02:30Z next day = 21:30 America/Chicago
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
    assert env.store.action_request(queued["action_request_id"])["status"] == "cancelled_by_freeze"
    ar = env.ar("email")
    res = env.gw.propose(ar, ar["proposed_by"])
    assert res.outcome == "rejected" and "PANIC_L3_FROZEN" in res.reasons
    assert "KILL_SWITCH_CHANGED" in [r["type"] for r in env.store.receipts()]
    assert_ledger_sound(env)


def test_l3_freeze_between_approval_and_execute(env):
    ar = env.approved("email")
    env.freeze_sql("L3")  # another operator process freezes through lane D directly
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "refused" and "G7:PANIC_L3_FROZEN" in res.reasons
    assert res.status == "cancelled_by_freeze"  # lane D's panic_set cancelled the unstarted request


def test_freeze_after_guard_before_effector(env, monkeypatch):
    ar = env.approved("email")
    real = env.panic.read
    calls = {"n": 0}

    def flip():
        calls["n"] += 1
        if calls["n"] == 2:  # 1st read = guard G7, 2nd = last-instant check
            env.freeze_sql("L3", reason="race")
        return real()
    monkeypatch.setattr(env.panic, "read", flip)
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "failed" and res.status == "cancelled_by_freeze"
    assert receipt_types(env, ar["action_request_id"])[-2:] == ["BUDGET_RELEASED", "ACTION_FAILED"]


@pytest.mark.parametrize("breakage", ["empty", "wrong_schema", "tamper", "no_database"])
def test_unreadable_panic_state_fails_closed(env, breakage):
    """§17 #20 / A9: an empty, malformed or tampered panic_state — or no database — reads as FROZEN."""
    ar = env.approved("email")
    if breakage == "empty":
        env.sql("DELETE FROM mbos.panic_state", replica=True)
    elif breakage == "wrong_schema":
        env.sql("UPDATE mbos.panic_state SET body = jsonb_set(body, '{schema}', '\"x\"') "
                "WHERE revision = (SELECT max(revision) FROM mbos.panic_state)", replica=True)
    elif breakage == "tamper":  # someone flips L3 to RUNNING / clears freezes without re-sealing
        env.freeze_sql("L2", "comms.*")
        env.sql("UPDATE mbos.panic_state SET body = jsonb_set(body, '{capabilities}', '{}') "
                "WHERE revision = (SELECT max(revision) FROM mbos.panic_state)", replica=True)
    else:
        env.gw.panic = type(env.panic)(env.dsn("gateway").replace("dbname=", "dbname=does_not_exist_"))
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


def test_release_needs_approver_role_in_the_database(env):
    """R5: even code that skips the gateway's checks cannot release as the gateway (or agent) login."""
    env.gw.engage_panic("L3", None, "michael", "x")
    for role in ("gateway", "agent_write"):
        with psycopg.connect(env.dsn(role), autocommit=True) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
            c.execute("SELECT mbos.panic_set('L3', NULL, false, '{\"type\":\"human\",\"id\":\"michael\"}'::jsonb, "
                      "'sneaky release', ARRAY['prov_00000000000000000000000000'], 'k')")
    assert env.panic.read().globally_frozen


def test_agents_cannot_engage_panic_directly(env):
    with psycopg.connect(env.dsn("agent_write"), autocommit=True) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("SELECT mbos.panic_set('L3', NULL, true, '{\"type\":\"agent\",\"id\":\"agent-02-opportunity\"}'::jsonb, "
                  "'x', ARRAY['prov_00000000000000000000000000'], 'k')")


def test_freeze_when_database_unreachable_fails_closed(env):
    from mbos_governance import ActionGateway, PgGovernanceStore, PgPanicStore
    bad = env.dsn("gateway").replace("dbname=", "dbname=gone_")
    gw = ActionGateway(PgGovernanceStore(bad), env.gw.policies, PgPanicStore(bad), clock=env.clock,
                       journal_path=env.tmp / "j.jsonl")
    out = gw.engage_panic("L3", None, "michael", "db is down")
    assert out["error"] and out["state"]["readable"] is False and gw.panic.read().globally_frozen
    assert "KILL_SWITCH_ENGAGE_FAILED" in (env.tmp / "j.jsonl").read_text()


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
    # Lane D CHECKs dry_run=true on stored responses (A7); what the effector claimed is kept verbatim.
    assert last["type"] == "ACTION_FAILED" and last["effector_response"]["status"] == "invariant_violation"
    assert last["details"]["effector_reported"]["dry_run"] is False


# ---------------------------------------------------------------- ledger integrity
def test_receipts_are_insert_only(env):
    env.gw.execute(env.approved("purchase")["action_request_id"])  # rows in every ledger incl. effector_calls/budget
    for role in ("gateway", "superuser"):
        with psycopg.connect(env.dsn(role), autocommit=True) as c:
            for q in ("UPDATE mbos.receipts SET intent='x'", "DELETE FROM mbos.receipts", "UPDATE mbos.approvals SET reason='x'",
                      "DELETE FROM mbos.provenance", "DELETE FROM mbos.panic_state", "DELETE FROM mbos.effector_calls",
                      "UPDATE mbos.budget_ledger SET amount = 0"):
                with pytest.raises(psycopg.Error):
                    c.execute(q)


def test_tampering_detected(env):
    """§17 #28 / A3."""
    env.gw.execute(env.approved("email")["action_request_id"])
    assert env.store.verify_chain()[0]
    env.sql("UPDATE mbos.receipts SET intent='nothing to see here' WHERE seq=5", replica=True)  # attacker bypassing triggers
    ok, msg = env.store.verify_chain()
    assert not ok and "seq 5" in msg


# ---------------------------------------------------------------- R4: the gateway owns action-status edges
@pytest.mark.parametrize("to,rtype", [("executing", "ACTION_EXECUTING"), ("executed", "ACTION_EXECUTED"),
                                      ("cancelled_by_freeze", "KILL_SWITCH_CHANGED")])
def test_agents_cannot_move_action_status(env, to, rtype):
    ar = env.approved("email")
    with psycopg.connect(env.dsn("agent_write"), autocommit=True) as c, pytest.raises(psycopg.errors.InsufficientPrivilege):
        c.execute("SELECT mbos.set_action_status(%s, %s, %s, '{\"type\":\"agent\",\"id\":\"agent-06-communications\"}'::jsonb,"
                  " 'self-execute', %s, %s)", (ar["action_request_id"], to, rtype, ar["provenance_ids"], new_id("k")))
    assert env.status(ar["action_request_id"]) == "approved"


def test_every_status_edge_is_receipted_by_the_gateway(env):
    """R4: every ACTION_EXECUTING/EXECUTED receipt is the gateway's, and lane D saw a receipt for each move."""
    ar = env.approved("email")
    env.gw.execute(ar["action_request_id"])
    rs = {r["type"]: r for r in env.store.receipts(ar["action_request_id"])}
    for t in ("POLICY_DECIDED", "APPROVAL_REQUESTED", "ACTION_EXECUTING", "ACTION_EXECUTED"):
        assert rs[t]["actor"] == {"type": "system", "id": "action-gateway"}, t
    assert rs["APPROVAL_DECIDED"]["actor"] == {"type": "human", "id": "michael"}
