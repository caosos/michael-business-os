"""E-05: stuck-claim reconciliation — provider-query-before-retry, dry-run, never re-send (05 §12, §17 #16–17)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from mbos_governance.effectors import DryRunEffector


class Crash(BaseException):
    """A process death: not an Exception, so nothing in the gateway swallows it."""


def _count_sends(monkeypatch) -> list:
    """Real provider send attempts (the effector's _execute body)."""
    calls = []
    orig = DryRunEffector._execute
    monkeypatch.setattr(DryRunEffector, "_execute", lambda self, t, a: calls.append(a["action_request_id"]) or orig(self, t, a))
    return calls


def crash_after_effector(env, monkeypatch, category="purchase") -> dict:
    """The provider durably recorded the send (its own committed write), then the process died before the
    gateway wrote the outcome receipts."""
    ar = env.approved(category)
    real = DryRunEffector.execute

    def send_then_die(self, token, a):
        real(self, token, a)
        raise Crash()
    monkeypatch.setattr(DryRunEffector, "execute", send_then_die)
    with pytest.raises(Crash):
        env.gw.execute(ar["action_request_id"])
    monkeypatch.setattr(DryRunEffector, "execute", real)
    return ar


def crash_before_effector(env, monkeypatch, category="purchase") -> dict:
    """Claim + ACTION_EXECUTING committed, then the process died before the provider was called."""
    ar = env.approved(category)
    real = DryRunEffector.execute

    def die(self, token, a):
        raise Crash()
    monkeypatch.setattr(DryRunEffector, "execute", die)
    with pytest.raises(Crash):
        env.gw.execute(ar["action_request_id"])
    monkeypatch.setattr(DryRunEffector, "execute", real)
    return ar


def provider_rows(env, areq):
    return env.sql("SELECT state FROM mbos.effector_calls WHERE action_request_id=%s", (areq,))


def claim_state(env, areq):
    return env.sql("SELECT state FROM mbos.effector_calls WHERE action_request_id=%s", (areq,))[0][0]


def test_crash_after_send_reconciles_to_executed_without_resend(env, monkeypatch):
    """R22/F-25: the provider's DURABLE record (mbos.effector_calls) proves the send => settle executed."""
    sends = _count_sends(monkeypatch)
    ar = crash_after_effector(env, monkeypatch)
    areq = ar["action_request_id"]
    assert env.status(areq) == "executing" and claim_state(env, areq) == "executed" and sends == [areq]
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "executed" and res.reasons == ["RECONCILED:PROVIDER_FOUND"]
    assert sends == [areq]                                            # provider queried, NOT re-sent
    assert env.status(areq) == "executed" and claim_state(env, areq) == "executed"
    rs = env.store.receipts(areq)
    assert rs[-1]["type"] == "ACTION_EXECUTED" and rs[-1]["details"]["reconciled"] is True
    durable = env.sql("SELECT response FROM mbos.effector_calls WHERE action_request_id=%s", (areq,))[0][0]
    assert rs[-1]["effector_response"] == durable and durable["provider_msg_id"].startswith("dryrun_")
    assert "BUDGET_COMMITTED" in [r["type"] for r in rs]
    assert env.gw.execute(areq).outcome == "duplicate"                 # and a later re-drive is a no-op
    assert env.store.verify_chain()[0]


def test_dbos_redrive_after_send_settles_executed_without_the_reconcile_job(env, monkeypatch):
    """The workflow's re-run of gateway_step itself finishes a crashed send (no separate job needed)."""
    sends = _count_sends(monkeypatch)
    ar = crash_after_effector(env, monkeypatch)
    res = env.gw.execute(ar["action_request_id"])
    assert res.outcome == "executed" and res.reasons == ["RECONCILED:PROVIDER_FOUND"] and len(sends) == 1
    assert env.status(ar["action_request_id"]) == "executed"


def test_crash_before_send_reconciles_to_failed_and_is_never_retried(env, monkeypatch):
    sends = _count_sends(monkeypatch)
    ar = crash_before_effector(env, monkeypatch)
    areq = ar["action_request_id"]
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "failed" and res.reasons == ["RECONCILED:PROVIDER_NOT_FOUND"]
    assert sends == []                                                 # nothing sent, during or after
    assert env.status(areq) == "failed" and claim_state(env, areq) == "failed"
    types = [r["type"] for r in env.store.receipts(areq)]
    assert types[-2:] == ["BUDGET_RELEASED", "ACTION_FAILED"]
    assert "RECONCILED" in env.store.receipts(areq)[-1]["intent"]
    assert env.gw.execute(areq).outcome == "refused"                   # a failed claim is never auto-retried
    assert sends == []


def test_reconciled_exactly_once_even_with_two_reconcilers(env, monkeypatch):
    sends = _count_sends(monkeypatch)
    ar = crash_after_effector(env, monkeypatch)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outs = [r for batch in pool.map(lambda _: env.gw.reconcile(older_than_seconds=0), range(2)) for r in batch]
    assert sorted(o.outcome for o in outs if o.action_request_id == ar["action_request_id"]) in (
        ["duplicate", "executed"], ["executed"])
    assert [r["type"] for r in env.store.receipts(ar["action_request_id"])].count("ACTION_EXECUTED") == 1
    assert env.gw.reconcile(older_than_seconds=0) == []
    assert len(sends) == 1


def test_fresh_claims_are_left_alone_until_the_ttl(env, monkeypatch):
    ar = crash_before_effector(env, monkeypatch)
    assert env.gw.reconcile() == []                                    # policy TTL 300 s not reached
    assert claim_state(env, ar["action_request_id"]) == "executing"


def test_provider_that_cannot_prove_a_send_settles_failed_never_resends(env, monkeypatch):
    """R22: a real provider that cannot answer / prove a send also settles FAILED (not a resend, not stuck)."""
    sends = _count_sends(monkeypatch)
    ar = crash_before_effector(env, monkeypatch)

    def down(self, token, a):
        raise TimeoutError("provider API unreachable")
    monkeypatch.setattr(DryRunEffector, "_lookup", down)
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "failed" and res.reasons == ["RECONCILED:PROVIDER_UNPROVEN"] and sends == []
    last = env.store.receipts(ar["action_request_id"])[-1]
    assert last["details"]["proof"] == "unproven" and "TimeoutError" in last["details"]["lookup_error"]
    assert env.status(ar["action_request_id"]) == "failed"


def test_reconciliation_works_under_l3_panic(env, monkeypatch):
    sends = _count_sends(monkeypatch)
    ar = crash_after_effector(env, monkeypatch)
    env.gw.engage_panic("L3", None, "michael", "incident")
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "executed" and len(sends) == 1               # records reality; never acts


def test_provider_record_claiming_live_effect_is_failed_and_freezes(env, monkeypatch):
    """Lane D's CHECK stops a non-dry-run row; if a provider's lookup still claims one, it is failed + L3."""
    ar = crash_before_effector(env, monkeypatch)
    monkeypatch.setattr(DryRunEffector, "_lookup", lambda self, t, a: {"provider": "rogue", "status": "sent", "dry_run": False})
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "failed" and res.reasons == ["RECONCILED:PROVIDER_RECORD_NOT_DRY_RUN"]
    assert env.panic.read().globally_frozen
    assert env.store.receipts(ar["action_request_id"])[-1]["details"]["effector_reported"]["dry_run"] is False


def test_the_provider_log_is_durable_not_in_process(env, monkeypatch):
    """F-25: a brand-new gateway/process (empty memory) still finds the send, because the log is mbos.effector_calls."""
    from mbos_governance import ActionGateway, PgPanicStore, PolicyStore
    ar = crash_after_effector(env, monkeypatch)
    fresh = ActionGateway(env.store, PolicyStore(env.policy_path), PgPanicStore(env.dsn("gateway")), clock=env.clock,
                          journal_path=env.tmp / "j2.jsonl")
    assert not hasattr(fresh._effectors["dryrun"], "deliveries")
    [res] = fresh.reconcile(older_than_seconds=0)
    assert res.outcome == "executed"
