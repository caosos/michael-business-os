"""E-10: Agent 05's governance behind Agent 01's `mbos.interfaces` (A-03 wiring).

    from mbos_governance.spine_adapter import build
    gov = build({"agent_write": .., "gateway": .., "approver": .., "policy_admin": ..}, "policy/policy.v1.json",
                panic_hooks=[DbosCancelHook(DBOS), EgressPolicyHook(..), LiteLLMBudgetHook(..)])
    Components(gateway=gov.gateway, kill_switch=gov.kill_switch, pdp=gov.pdp, ...)
    DBOS.scheduled("*/5 * * * *")(lambda *_: reconcile(gov.action_gateway))   # E-05

R4 CONTRACT (the spine must follow this; see docs/integration/05-spine-adapter-R4-contract.md):
  The gateway OWNS, for every ActionRequest, the edges   approved -> executing -> executed | failed | cancelled_by_freeze
  and approved -> expired | failed, plus every receipt on them:  ACTION_EXECUTING, ACTION_EXECUTED, ACTION_FAILED,
  BUDGET_RESERVED / BUDGET_COMMITTED / BUDGET_RELEASED, and the mbos.effector_calls claim.
  The spine moves only the ITEM (APPROVED -> ACTING -> ACTED | FAILED) and must not call set_action_status for
  those edges nor write those receipts. Michael's decisions (pending_approval|held -> approved|rejected|held)
  stay the spine's/approver's via mbos.record_approval.

Writes use the gateway's own role connections (login in the `gateway` group), not the spine's engine: the
spine's DBOS login need not hold `gateway` (lane D RECOMMENDATION: revoke it once the gateway runs alone).
Every return value is a plain JSON-serialisable dataclass (DBOS checkpoints it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mbos.interfaces import GuardResult, PolicyDecision  # Agent 01's types (runtime dependency of the spine)

from .gateway import ActionGateway, GatewayRefused, Result
from .policy import PolicyStore, PolicyUnavailable, decide
from .store_pg import PgGovernanceStore, PgPanicStore

# mbos.interfaces check names (as in mbos.reference.governance) <- the gateway's G1..G8
CHECK_NAMES = {"G1": "approval_valid", "G2": "not_expired", "G3": "payload_hash_match", "G4": "idempotency_unused",
               "G5": "budget_reserved", "G6": "grant_ok", "G7": "kill_switch_clear", "G8": "dry_run_mode"}


def _checks(reasons: list[str]) -> dict[str, bool]:
    failed = {r.split(":", 1)[0] for r in reasons}
    return {name: g not in failed for g, name in CHECK_NAMES.items()}


class SpineGateway:
    """`mbos.interfaces.Gateway`. Runs the 8 guard checks and the (dry-run) effector through ActionGateway."""

    def __init__(self, gw: ActionGateway):
        self.gw = gw

    def execute(self, engine: Any, action_request_id: str, approval_id: str) -> GuardResult:
        all_ok = {n: True for n in CHECK_NAMES.values()}
        # The spine names the approval it acted on; the gateway always uses the LATEST one. They must match.
        with self.gw.store.tx("gateway") as cur:
            latest = self.gw.store.latest_approval(cur, action_request_id)
        if latest is None or latest["approval_id"] != approval_id:
            return GuardResult(False, {**all_ok, "approval_valid": False},
                               f"approval {approval_id} is not the latest decision on {action_request_id}",
                               {"provider": "gateway", "status": "denied", "dry_run": True})
        try:
            res = self.gw.execute(action_request_id)
        except GatewayRefused as exc:
            return GuardResult(False, {**all_ok, "approval_valid": False}, str(exc),
                               {"provider": "gateway", "status": "denied", "dry_run": True})
        if res.outcome == "refused" and res.reasons and res.reasons[0].startswith("IN_FLIGHT_OR_CRASHED"):
            # DBOS recovery re-ran this step after a crash mid-execution: settle it by provider lookup now
            # (E-05 semantics: found -> executed with the provider's record; not found -> failed). Never re-send.
            res = self.gw._reconcile_one(action_request_id, self.gw.policies.current())
        return self._to_guard(res)

    @staticmethod
    def _to_guard(res: Result) -> GuardResult:
        if res.outcome in ("executed", "duplicate") and res.effector_response:
            reason = ("idempotent replay: effector already ran for this key; not re-executed"
                      if res.outcome == "duplicate" else "all 8 guard checks passed")
            if "RECONCILED:PROVIDER_FOUND" in res.reasons:
                reason = "reconciled after crash: provider confirms delivery; not re-sent"
            return GuardResult(True, {n: True for n in CHECK_NAMES.values()}, reason, res.effector_response)
        frozen = res.status == "cancelled_by_freeze" or any(r.startswith(("G7:", "FROZE_BEFORE_EFFECTOR")) for r in res.reasons)
        return GuardResult(False, _checks(res.reasons), "; ".join(res.reasons)[:1000] or res.outcome,
                           {"provider": "gateway", "status": res.status or "denied", "dry_run": True}, frozen)


class SpineKillSwitch:
    """`mbos.interfaces.KillSwitch` over lane D's PANIC, inside the caller's transaction. Fail closed."""

    def __init__(self, policies: PolicyStore):
        self.policies = policies

    def is_clear(self, conn: Any, *, capability: str, agent_id: str) -> tuple[bool, str]:
        import sqlalchemy as sa
        try:
            try:
                cap = self.policies.current().capability(capability)
            except PolicyUnavailable:
                cap = None  # category unknown: L3/L1/L2-capability freezes still apply
            reasons = conn.execute(sa.text("SELECT mbos.panic_blocks(:a, :c, :g)"),
                                   {"a": agent_id, "c": capability, "g": cap["category"] if cap else None}).scalar_one()
        except Exception as exc:  # noqa: BLE001 — unreadable means frozen (A9)
            return False, f"PANIC_STATE_UNREADABLE: {type(exc).__name__}; failing closed"
        return (not reasons, "; ".join(reasons) if reasons else "clear")


class SpinePDP:
    """`mbos.interfaces.PolicyDecisionPoint`: the non-LLM PDP on the full ActionRequest. Fail closed."""

    def __init__(self, policies: PolicyStore):
        self.policies = policies

    def decide(self, action_request: dict[str, Any]) -> PolicyDecision:
        category = str(action_request.get("category", "?"))
        try:
            policy = self.policies.current()
        except PolicyUnavailable as exc:
            return PolicyDecision("deny", 0, category, f"POLICY_UNREADABLE: {exc}", "UNAVAILABLE")
        try:
            d = decide(action_request, policy)
        except (KeyError, TypeError) as exc:  # incomplete draft: never allow
            return PolicyDecision("deny", 0, category, f"MALFORMED_REQUEST: {exc}", policy.version)
        return PolicyDecision(d.decision, d.tier, category, "; ".join(d.reasons), policy.version)


def reconcile(gw: ActionGateway, older_than_seconds: int | None = None) -> list[dict[str, Any]]:
    """E-05 as a plain, schedulable function (JSON-serialisable result for DBOS)."""
    return [{"action_request_id": r.action_request_id, "outcome": r.outcome, "status": r.status, "reasons": r.reasons}
            for r in gw.reconcile(older_than_seconds)]


@dataclass
class Governance:
    action_gateway: ActionGateway
    gateway: SpineGateway
    kill_switch: SpineKillSwitch
    pdp: SpinePDP


def build(dsns: str | dict[str, str], policy_path: str, *, panic_hooks: list | None = None, **gateway_kw: Any) -> Governance:
    policies = PolicyStore(policy_path)
    store = PgGovernanceStore(dsns)
    gateway_dsn = dsns if isinstance(dsns, str) else dsns["gateway"]
    gw = ActionGateway(store, policies, PgPanicStore(gateway_dsn), panic_hooks=panic_hooks, **gateway_kw)
    return Governance(gw, SpineGateway(gw), SpineKillSwitch(policies), SpinePDP(policies))
