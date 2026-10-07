"""E-05: stuck-claim reconciliation — provider-query-before-retry, dry-run, never re-send (05 §12, §17 #16–17)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from mbos_governance.effectors import DryRunEffector


class Crash(BaseException):
    """A process death: not an Exception, so nothing in the gateway swallows it."""


def _eff(env) -> DryRunEffector:
    return env.gw._effectors["dryrun"]


def _count_sends(monkeypatch) -> list:
    calls = []
    orig = DryRunEffector._execute
    monkeypatch.setattr(DryRunEffector, "_execute", lambda self, t, a: calls.append(a["action_request_id"]) or orig(self, t, a))
    return calls


def crash_after_effector(env, monkeypatch, category="purchase") -> dict:
    """Effector call happened (provider has a record), then the process died before the outcome receipt."""
    ar = env.approved(category)
    store_cls = type(env.store)
    real = store_cls.effector_finish

    def die(*a, **k):
        raise Crash()
    monkeypatch.setattr(store_cls, "effector_finish", staticmethod(die))
    with pytest.raises(Crash):
        env.gw.execute(ar["action_request_id"])
    monkeypatch.setattr(store_cls, "effector_finish", staticmethod(real))
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


def claim_state(env, areq):
    return env.sql("SELECT state FROM mbos.effector_calls WHERE action_request_id=%s", (areq,))[0][0]


def test_crash_after_send_reconciles_to_executed_without_resend(env, monkeypatch):
    sends = _count_sends(monkeypatch)
    ar = crash_after_effector(env, monkeypatch)
    areq = ar["action_request_id"]
    assert env.status(areq) == "executing" and claim_state(env, areq) == "executing" and sends == [areq]
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "executed" and res.reasons == ["RECONCILED:PROVIDER_FOUND"]
    assert sends == [areq]                                            # provider queried, NOT re-sent
    assert env.status(areq) == "executed" and claim_state(env, areq) == "executed"
    rs = env.store.receipts(areq)
    assert rs[-1]["type"] == "ACTION_EXECUTED" and rs[-1]["details"]["reconciled"] is True
    assert rs[-1]["effector_response"] == _eff(env).deliveries[ar["idempotency_key"]]
    assert "BUDGET_COMMITTED" in [r["type"] for r in rs]
    assert env.gw.execute(areq).outcome == "duplicate"                 # and a later re-drive is a no-op
    assert env.store.verify_chain()[0]


def test_crash_before_send_reconciles_to_failed_and_is_never_retried(env, monkeypatch):
    sends = _count_sends(monkeypatch)
    ar = crash_before_effector(env, monkeypatch)
    areq = ar["action_request_id"]
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "failed" and res.reasons == ["RECONCILED:PROVIDER_NOT_FOUND"]
    assert sends == [] and _eff(env).deliveries == {}                  # nothing sent, during or after
    assert env.status(areq) == "failed" and claim_state(env, areq) == "failed"
    types = [r["type"] for r in env.store.receipts(areq)]
    assert types[-2:] == ["BUDGET_RELEASED", "ACTION_FAILED"]
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


def test_provider_that_cannot_answer_leaves_the_claim_for_a_human(env, monkeypatch):
    ar = crash_before_effector(env, monkeypatch)

    def down(self, token, a):
        raise TimeoutError("provider API unreachable")
    monkeypatch.setattr(DryRunEffector, "_lookup", down)
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "refused" and res.reasons[0].startswith("NEEDS_HUMAN:LOOKUP_FAILED")
    assert claim_state(env, ar["action_request_id"]) == "executing" and env.status(ar["action_request_id"]) == "executing"


def test_reconciliation_works_under_l3_panic(env, monkeypatch):
    sends = _count_sends(monkeypatch)
    ar = crash_after_effector(env, monkeypatch)
    env.gw.engage_panic("L3", None, "michael", "incident")
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "executed" and len(sends) == 1               # records reality; never acts


def test_provider_record_claiming_live_effect_is_failed_and_freezes(env, monkeypatch):
    ar = crash_before_effector(env, monkeypatch)
    _eff(env).deliveries[ar["idempotency_key"]] = {"provider": "rogue", "status": "sent", "dry_run": False}
    [res] = env.gw.reconcile(older_than_seconds=0)
    assert res.outcome == "failed" and res.reasons == ["RECONCILED:PROVIDER_RECORD_NOT_DRY_RUN"]
    assert env.panic.read().globally_frozen
    assert env.store.receipts(ar["action_request_id"])[-1]["details"]["effector_reported"]["dry_run"] is False
