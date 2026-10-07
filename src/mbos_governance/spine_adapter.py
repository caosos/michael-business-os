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
from .hooks import DbosCancelHook, EgressPolicyHook, LiteLLMBudgetHook
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
        reason = "; ".join(d.reasons) + ("; step_up=required" if d.step_up else "")
        return PolicyDecision(d.decision, d.tier, category, reason, policy.version)


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


def build(dsns: str | dict[str, str], policy_path: str | None = None, *, dbos: Any = None,
          egress_file: str | None = "var/egress_policy.json", litellm_file: str | None = "var/litellm_keys.json",
          panic_hooks: list | None = None, **gateway_kw: Any) -> Governance:
    """policy_path=None (production, E-06): the PDP reads lane D's mbos.policy_current; a file path is for dev/tests.

    L3/L1/L2 side-effect hooks (E-03) are wired here so `engage_panic()` runs them:
      * `dbos` (the DBOS class)  -> DbosCancelHook: L3 cancels ENQUEUED/DELAYED workflows
      * `egress_file`            -> EgressPolicyHook: sealed deny-all/allow-list file for the egress proxy
      * `litellm_file`           -> LiteLLMBudgetHook: per-agent LiteLLM key specs (budgets 0 when frozen)
    Pass None to skip one; `panic_hooks=[...]` replaces the default set entirely."""
    store = PgGovernanceStore(dsns)
    gateway_dsn = dsns if isinstance(dsns, str) else dsns["gateway"]
    if policy_path is None:
        from .policy_pg import PgPolicyStore
        policies: Any = PgPolicyStore(gateway_dsn)
    else:
        policies = PolicyStore(policy_path)
    if panic_hooks is None:
        panic_hooks = []
        if dbos is not None:
            panic_hooks.append(DbosCancelHook(dbos))
        if egress_file:
            panic_hooks.append(EgressPolicyHook(egress_file, policies))
        if litellm_file:
            panic_hooks.append(LiteLLMBudgetHook(litellm_file, policies))
    gw = ActionGateway(store, policies, PgPanicStore(gateway_dsn), panic_hooks=panic_hooks, **gateway_kw)
    return Governance(gw, SpineGateway(gw), SpineKillSwitch(policies), SpinePDP(policies))


# ---------------------------------------------------------------- A-18 helpers (plain functions, JSON-serialisable)
def engage_panic(gov: Governance, level: str, target: str | None, actor: str, reason: str) -> dict[str, Any]:
    """Freeze (any actor may engage). Runs the wired hooks. Returns {"state", "cancelled", "hooks", ["error"]}.
    FAIL CLOSED: if the freeze cannot be written the DB is unreachable, PANIC then reads FROZEN everywhere and
    the attempt is journaled; `error` is set. Never raises for a database outage."""
    return gov.action_gateway.engage_panic(level, target, actor, reason)


def release_panic(gov: Governance, level: str, target: str | None, actor: str, reason: str) -> dict[str, Any]:
    """Release as the `approver` role (Michael). Raises GatewayRefused if `actor` is not a policy approver, the
    reason is blank or the policy is unreadable, and the database error if the login lacks `approver`.
    Loosening hooks run only after the release committed with its receipt."""
    return gov.action_gateway.release_panic(level, target, actor, reason)


def panic_state(gov: Governance) -> dict[str, Any]:
    st = gov.action_gateway.panic.read()
    return {"global": st.global_state, "readable": st.readable, "error": st.error, "revision": st.revision,
            "frozen_agents": sorted(st.frozen_agents), "frozen_capabilities": sorted(st.frozen_capabilities)}


@dataclass
class ScheduledReconcile:
    """Result of `schedule_reconcile`: the registered DBOS workflow and the post-launch activation."""
    workflow: Any
    name: str
    schedule_name: str
    crontab: str
    _dbos: Any

    def activate(self) -> str:
        """Create (or refresh) the persistent DBOS schedule. Call AFTER `DBOS.launch()` (DBOS 3.x schedules live in
        the system database). Idempotent: an existing schedule with the same cron is left alone; a changed cron is
        replaced. Returns "created" | "unchanged" | "replaced"."""
        existing = self._dbos.get_schedule(self.schedule_name)
        if existing is not None:
            if existing.get("schedule") == self.crontab:     # WorkflowSchedule is a TypedDict (a dict)
                return "unchanged"
            self._dbos.delete_schedule(self.schedule_name)
        self._dbos.create_schedule(schedule_name=self.schedule_name, workflow_fn=self.workflow, schedule=self.crontab)
        return "replaced" if existing is not None else "created"


def schedule_reconcile(gov: Governance, dbos: Any, crontab: str = "*/5 * * * *", name: str = "mbos_reconcile_claims",
                       older_than_seconds: int | None = None) -> ScheduledReconcile:
    """DBOS (3.x) scheduled-workflow factory for E-05. At worker start:

        sched = schedule_reconcile(gov, DBOS)        # 1. BEFORE DBOS.launch(): registers the workflow
        DBOS.launch()
        sched.activate()                             # 2. AFTER launch: creates the persistent cron schedule

    Each run settles execution claims left `executing` past the policy TTL (provider lookup, never a resend).
    Reconciliation is allowed under PANIC: it records what already happened and never acts, so the L3 cancel hook
    is told never to cancel this workflow's queued runs. `crontab` may have 6 fields (seconds first)."""
    def step_body() -> list[dict[str, Any]]:
        return reconcile(gov.action_gateway, older_than_seconds)

    step_body.__name__ = step_body.__qualname__ = f"{name}_step"      # names are DBOS registration keys: set first
    step = dbos.step()(step_body)

    def workflow(scheduled_time: Any, context: Any = None) -> list[dict[str, Any]]:
        return step()
    workflow.__name__ = workflow.__qualname__ = name
    wf = dbos.workflow()(workflow)
    for hook in gov.action_gateway.panic_hooks:       # reconcile must keep running while frozen
        if isinstance(hook, DbosCancelHook):
            hook.protect.add(name)
    return ScheduledReconcile(wf, name, name, crontab, dbos)
