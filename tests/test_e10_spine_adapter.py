"""E-10: the spine adapter, driven through Agent 01's `mbos.interfaces` types on lane D (A-03 support).
mbos/interfaces.py is vendored test-only from agent-01-coordinator @ 8c3e4fd (sha256 pinned below)."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import psycopg
import pytest
import sqlalchemy as sa

VENDOR = Path(__file__).resolve().parent / "vendor" / "agent01_mbos"
sys.path.insert(0, str(VENDOR))
from mbos import interfaces as I  # noqa: E402

from mbos_governance.effectors import DryRunEffector  # noqa: E402
from mbos_governance.spine_adapter import SpineGateway, SpineKillSwitch, SpinePDP, reconcile  # noqa: E402

from .test_e05_reconcile import crash_after_effector, crash_before_effector  # noqa: E402

INTERFACES_SHA = "7109cfed29f097b294bf3e4f99c899b9431d7e187fd0b523754f8b85235c81b9"


def test_vendored_interfaces_pinned():
    assert hashlib.sha256((VENDOR / "mbos" / "interfaces.py").read_bytes()).hexdigest() == INTERFACES_SHA


@pytest.fixture
def gov(env):
    return SpineGateway(env.gw), SpineKillSwitch(env.gw.policies), SpinePDP(env.gw.policies)


@pytest.fixture
def engine(env):
    """The spine's SQLAlchemy engine (DBOS login stand-in). The adapter must not need it for writes."""
    e = sa.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(env.dsn("agent_write")))
    yield e
    e.dispose()


def latest_approval_id(env, areq):
    return env.sql("SELECT approval_id FROM mbos.approvals WHERE action_request_id=%s ORDER BY seq DESC LIMIT 1",
                   (areq,))[0][0]


def test_satisfies_01_protocols(gov):
    g, k, p = gov
    assert isinstance(g, I.Gateway) and isinstance(k, I.KillSwitch) and isinstance(p, I.PolicyDecisionPoint)


# ---------------------------------------------------------------- Gateway.execute
def test_execute_ok_and_json_serialisable(env, gov, engine):
    g, _, _ = gov
    ar = env.approved("email")
    r = g.execute(engine, ar["action_request_id"], latest_approval_id(env, ar["action_request_id"]))
    assert isinstance(r, I.GuardResult) and r.ok and not r.frozen
    assert set(r.checks) == {"approval_valid", "not_expired", "payload_hash_match", "idempotency_unused",
                             "budget_reserved", "grant_ok", "kill_switch_clear", "dry_run_mode"} and all(r.checks.values())
    assert r.effector_response["dry_run"] is True
    json.dumps(r.__dict__)  # DBOS checkpoints it


def test_replay_returns_original_response_a5(env, gov, engine):
    g, _, _ = gov
    ar = env.approved("sms")
    appr = latest_approval_id(env, ar["action_request_id"])
    first = g.execute(engine, ar["action_request_id"], appr)
    again = g.execute(engine, ar["action_request_id"], appr)
    assert again.ok and again.effector_response == first.effector_response and "replay" in again.reason
    assert env.sql("SELECT count(*) FROM mbos.effector_calls WHERE action_request_id=%s AND state='executed'",
                   (ar["action_request_id"],))[0][0] == 1


def test_wrong_or_stale_approval_id_denied(env, gov, engine):
    g, _, _ = gov
    ar = env.approved("email")
    r = g.execute(engine, ar["action_request_id"], "appr_01JA0000000000000000000099")
    assert not r.ok and r.checks["approval_valid"] is False
    assert env.status(ar["action_request_id"]) == "approved"


def test_freeze_maps_to_frozen(env, gov, engine):
    g, _, _ = gov
    ar = env.approved("email")
    appr = latest_approval_id(env, ar["action_request_id"])
    env.gw.engage_panic("L2", "comms.*", "michael", "incident")
    r = g.execute(engine, ar["action_request_id"], appr)
    assert not r.ok and r.frozen and r.checks["kill_switch_clear"] is False and r.checks["approval_valid"] is True


def test_guard_refusal_reports_failed_checks(env, gov, engine):
    g, _, _ = gov
    ar = env.approved("email")
    appr = latest_approval_id(env, ar["action_request_id"])
    env.clock.advance(hours=25)  # past the 24 h approval TTL
    r = g.execute(engine, ar["action_request_id"], appr)
    assert not r.ok and not r.frozen and r.checks["not_expired"] is False and "APPROVAL_EXPIRED" in r.reason


def test_dbos_recovery_after_send_reconciles_not_resends(env, gov, engine, monkeypatch):
    """gateway_step re-run by DBOS after the process died post-effector: settled by provider lookup."""
    g, _, _ = gov
    ar = crash_after_effector(env, monkeypatch, "email")
    r = g.execute(engine, ar["action_request_id"], latest_approval_id(env, ar["action_request_id"]))
    assert r.ok and "RECONCILED" in r.reason.upper() and "reconciled" in r.reason.lower()
    assert env.status(ar["action_request_id"]) == "executed"


def test_dbos_recovery_before_send_fails_safely(env, gov, engine, monkeypatch):
    g, _, _ = gov
    ar = crash_before_effector(env, monkeypatch, "email")
    r = g.execute(engine, ar["action_request_id"], latest_approval_id(env, ar["action_request_id"]))
    assert not r.ok and not r.frozen and "PROVIDER_NOT_FOUND" in r.reason
    assert env.sql("SELECT state FROM mbos.effector_calls WHERE action_request_id=%s", (ar["action_request_id"],))[0][0] == "failed"
    assert env.status(ar["action_request_id"]) == "failed"


# ---------------------------------------------------------------- R4: the spine must not write the action edges
def test_r4_spine_writing_executing_itself_breaks_execution(env, gov, engine):
    """Today's begin_act moves approved->executing; with 05's gateway that makes the guard refuse
    (STATUS_NOT_APPROVED). Hence the contract: begin_act/finish_act move only the Item."""
    g, _, _ = gov
    ar = env.approved("email")
    appr = latest_approval_id(env, ar["action_request_id"])
    with env.store.tx("gateway") as cur:  # what the old begin_act does (as a gateway-member login)
        env.store.set_status(cur, ar["action_request_id"], "executing", "ACTION_EXECUTING",
                             {"type": "system", "id": "mbos-spine"}, "old begin_act", ar["provenance_ids"],
                             "spine:executing", {"approval_id": appr, "effect": "none"})
    r = g.execute(engine, ar["action_request_id"], appr)
    assert not r.ok and "STATUS_NOT_APPROVED:executing" in r.reason


def test_r4_one_receipt_per_edge_when_spine_follows_contract(env, gov, engine):
    g, _, _ = gov
    ar = env.approved("email")
    assert g.execute(engine, ar["action_request_id"], latest_approval_id(env, ar["action_request_id"])).ok
    types = [r["type"] for r in env.store.receipts(ar["action_request_id"])]
    assert types.count("ACTION_EXECUTING") == 1 and types.count("ACTION_EXECUTED") == 1
    assert {r["actor"]["id"] for r in env.store.receipts(ar["action_request_id"])
            if r["type"] in ("ACTION_EXECUTING", "ACTION_EXECUTED")} == {"action-gateway"}


# ---------------------------------------------------------------- KillSwitch.is_clear (caller's connection)
def test_kill_switch_in_callers_transaction(env, gov, engine):
    _, k, _ = gov
    with engine.begin() as conn:
        assert k.is_clear(conn, capability="comms.sms.send", agent_id="agent-06-communications") == (True, "clear")
    env.gw.engage_panic("L2", "category:sms", "michael", "sms incident")  # category resolved via policy data
    with engine.begin() as conn:
        ok, why = k.is_clear(conn, capability="comms.sms.send", agent_id="agent-06-communications")
        assert not ok and "PANIC_L2_CATEGORY:sms" in why
        assert k.is_clear(conn, capability="comms.email.send", agent_id="agent-06-communications")[0]


def test_kill_switch_fails_closed(env, gov, engine):
    _, k, _ = gov
    env.sql("DELETE FROM mbos.panic_state", replica=True)
    with engine.begin() as conn:
        ok, why = k.is_clear(conn, capability="comms.email.send", agent_id="agent-06-communications")
    assert not ok and "UNREADABLE" in why
    broken = sa.create_engine("postgresql+psycopg://", creator=lambda: psycopg.connect(env.dsn("agent_write")))
    with broken.connect() as conn:
        conn.close()  # a dead connection: is_clear must fail closed, not raise
        ok, why = k.is_clear(conn, capability="comms.email.send", agent_id="x")
    assert not ok and "failing closed" in why
    broken.dispose()


# ---------------------------------------------------------------- PDP.decide (full areq)
def test_pdp_decisions(env, gov):
    _, _, p = gov
    ok = p.decide(env.ar("email"))
    assert isinstance(ok, I.PolicyDecision) and (ok.decision, ok.tier, ok.category) == ("require_approval", 0, "email")
    assert ok.policy_version.startswith("2026.10.08")
    bad = p.decide({**env.ar("email"), "capability": "comms.fax.send"})
    assert bad.decision == "deny" and "UNKNOWN_CAPABILITY" in bad.reason
    assert p.decide({"category": "money"}).decision == "deny"           # malformed draft: fail closed
    env.policy_path.write_text("{")
    down = p.decide(env.ar("email"))
    assert down.decision == "deny" and down.policy_version == "UNAVAILABLE"


# ---------------------------------------------------------------- reconcile() as a schedulable function
def test_reconcile_function_is_json_serialisable(env, monkeypatch):
    ar = crash_after_effector(env, monkeypatch, "email")
    out = reconcile(env.gw, older_than_seconds=0)
    assert json.loads(json.dumps(out)) == out
    assert out == [{"action_request_id": ar["action_request_id"], "outcome": "executed", "status": "executed",
                    "reasons": ["RECONCILED:PROVIDER_FOUND"]}]
