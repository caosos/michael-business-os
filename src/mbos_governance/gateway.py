"""Action Gateway (PEP) + execution guard — the ONLY path from a proposal to an effector.

Core law: no action without a receipt; no receipt without provenance.
Governance rule: models PROPOSE (ActionRequest); this non-LLM code AUTHORIZES.

Lifecycle (statuses from action-request.schema.json; every transition writes a receipt
in the same transaction as the status change):

  propose()          drafted -> pending_approval | rejected      ACTION_PROPOSED, POLICY_DECIDED, APPROVAL_REQUESTED
  record_approval()  YES -> approved (+BUDGET_RESERVED) | NO -> rejected | HOLD -> held | MODIFY -> rejected(closed)
  execute()          approved -> executing -> executed | failed | expired | cancelled_by_freeze

Execution guard — all 8 checks (ADR-0005 §2), evaluated inside one write transaction:
  G1 approval valid      latest Approval is YES, by an allowed approver/channel/scope, step-up when required
  G2 not expired         approval expiry, approval TTL cap, ActionRequest.expires_at
  G3 payload_hash        sha256(canonical(payload)) == ActionRequest.payload_hash == Approval.payload_hash_seen
  G4 idempotency         no execution claim for this idempotency_key (exactly-once effect)
  G5 budget reserved     reservation exists (or can be made now) within per-action/daily/global/velocity caps
  G6 grant constraints   PDP re-run on CURRENT policy: capability still held, category still gated, tier 0,
                         scope=once (no delegation), quiet hours
  G7 kill switch clear   PANIC L3 / L1 agent / L2 capability|category; unreadable => FROZEN
  G8 dry-run forced      system_mode round_one|mvp => dry_run=True; effector must support it and must echo it
Policy unreadable => every check fails closed.
"""
from __future__ import annotations

import json
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from . import __version__, contracts
from .effectors import DryRunEffector, Effector, TokenMinter
from .ids import fmt_ts, new_id, new_ulid, parse_ts, payload_hash, utcnow
from .panic import PanicStore
from .policy import DENY, REQUIRE_APPROVAL, Policy, PolicyStore, PolicyUnavailable, decide

GATEWAY_ACTOR = {"type": "system", "id": "action-gateway"}
DRY_RUN_MODES = ("round_one", "mvp")

EFFECT_BY_CATEGORY = {
    "message": "send", "sms": "send", "email": "send", "phone_call": "send",
    "offer": "commit", "external_commitment": "commit", "money": "pay", "purchase": "pay",
    "publishing": "publish", "price_change": "update", "scheduling": "schedule",
}


class GatewayRefused(Exception):
    """Raised when a request cannot even be recorded (invalid contract, unknown id, wrong caller)."""


@dataclass
class Result:
    outcome: str  # pending_approval | rejected | duplicate | recorded | executed | refused | failed
    action_request_id: str | None = None
    status: str | None = None
    reasons: list[str] = field(default_factory=list)
    receipts: list[str] = field(default_factory=list)
    effector_response: dict | None = None


def to_micros(amount) -> int:
    return int((Decimal(str(amount)) * 1_000_000).to_integral_value(rounding=ROUND_CEILING))


class ActionGateway:
    def __init__(self, store, policy_store: PolicyStore, panic_store: PanicStore, clock=utcnow,
                 journal_path: str | Path | None = None):
        self.store = store
        self.policies = policy_store
        self.panic = panic_store
        self.clock = clock
        self._minter = TokenMinter(secrets.token_bytes(32))
        self._effectors: dict[str, Effector] = {"dryrun": DryRunEffector(self._minter)}
        self._journal = Path(journal_path) if journal_path else Path(str(panic_store.path) + ".journal.jsonl")

    # ------------------------------------------------------------------ helpers
    def _policy(self) -> tuple[Policy | None, str | None]:
        try:
            return self.policies.current(), None
        except PolicyUnavailable as exc:
            return None, f"POLICY_UNREADABLE:{exc}"

    def _tool_provenance(self, cur, config_version: str, tool: str = "mbos_governance.gateway",
                         human: str | None = None) -> str:
        prov = {
            "provenance_id": new_id("prov"),
            "created_at": fmt_ts(self.clock()),
            "actor_type": "human" if human else "system",
            "basis": "FACT",
            "tool_name": tool,
            "tool_version": __version__,
            "config_version": config_version,
        }
        if human:
            prov["human_actor"] = human
        self.store.insert_provenance(cur, prov)
        return prov["provenance_id"]

    def _action_receipt(self, cur, rtype: str, ar: dict, intent: str, prov_ids: list[str], *,
                        actor: dict = GATEWAY_ACTOR, key: str | None = None, **extra) -> dict:
        partial = {
            "type": rtype,
            "actor": actor,
            "intent": intent,
            "item_id": ar["item_id"],
            "action_request_id": ar["action_request_id"],
            "capability": ar["capability"],
            "payload_hash": ar["payload_hash"],
            "provenance_ids": prov_ids,
            "idempotency_key": key or f"{ar['action_request_id']}:{rtype}:{new_ulid()}",
            "details": {"kind": "generic"},
            **extra,
        }
        return self.store.append_receipt(cur, partial)

    def _now_local(self, policy: Policy) -> datetime:
        return self.clock().astimezone(ZoneInfo(policy.data["quiet_hours"]["timezone"]))

    def _in_quiet_hours(self, policy: Policy) -> bool:
        qh = policy.data["quiet_hours"]
        t = self._now_local(policy).strftime("%H:%M")
        start, end = qh["start"], qh["end"]
        return (start <= t or t < end) if start > end else (start <= t < end)

    def _dry_run_forced(self, policy: Policy) -> bool:
        # Wave one: there is no live mode. Any mode not in DRY_RUN_MODES is refused by the
        # policy schema; this check is the second lock.
        return policy.data["system_mode"] in DRY_RUN_MODES

    # ------------------------------------------------------------------ provenance
    def record_provenance(self, prov: dict) -> str:
        with self.store.tx() as cur:
            self.store.insert_provenance(cur, prov)
        return prov["provenance_id"]

    # ------------------------------------------------------------------ propose
    def _proposal_problems(self, ar: dict, caller: str, policy: Policy | None) -> list[str]:
        p: list[str] = []
        now = self.clock()
        if ar["proposed_by"] != caller:
            p.append(f"CALLER_MISMATCH:{caller} cannot propose as {ar['proposed_by']}")
        try:
            if payload_hash(ar["payload"]) != ar["payload_hash"]:
                p.append("PAYLOAD_HASH_MISMATCH")
        except ValueError as exc:
            p.append(f"PAYLOAD_NOT_HASHABLE:{exc}")
        if policy is None:
            return p
        rules = policy.data["action_request"]
        skew = timedelta(seconds=policy.data["clock_skew_seconds"])
        if ar["status"] not in rules["allowed_initial_status"]:
            p.append(f"INITIAL_STATUS_NOT_ALLOWED:{ar['status']}")
        if ar.get("on_behalf_of") != rules["on_behalf_of_required"]:
            p.append("ON_BEHALF_OF_REQUIRED:michael")
        try:
            created, expires = parse_ts(ar["created_at"]), parse_ts(ar["expires_at"])
            if created > now + skew:
                p.append("CREATED_IN_FUTURE")
            if expires <= now:
                p.append("ALREADY_EXPIRED")
            if expires - created > timedelta(seconds=rules["max_lifetime_seconds"]):
                p.append("LIFETIME_EXCEEDS_POLICY")
        except ValueError as exc:
            p.append(f"BAD_TIMESTAMP:{exc}")
        return p

    def propose(self, ar: dict, caller: str) -> Result:
        """An agent submits a proposed side-effect. Never executes anything."""
        contracts.require_valid("action-request", ar)
        policy, policy_err = self._policy()
        panic_state = self.panic.read()
        with self.store.tx() as cur:
            existing = self.store.find_by_idempotency_key(cur, ar["idempotency_key"])
            if existing is not None:
                return Result("duplicate", existing["action_request_id"], existing["status"],
                              ["IDEMPOTENCY_KEY_ALREADY_PROPOSED"])
            if self.store.get_action_request(cur, ar["action_request_id"]) is not None:
                raise GatewayRefused(f"{ar['action_request_id']} already exists")
            try:
                self.store.require_provenance(cur, ar["provenance_ids"])
            except ValueError as exc:
                raise GatewayRefused(f"no action without provenance: {exc}") from exc
            if ar.get("derived_from") and self.store.get_action_request(cur, ar["derived_from"]) is None:
                raise GatewayRefused(f"derived_from {ar['derived_from']} unknown")

            reasons = self._proposal_problems(ar, caller, policy)
            reasons += panic_state.blocks(ar["proposed_by"], ar["capability"], ar["category"])
            if policy_err:
                reasons.append(policy_err)
            decision = None
            if policy is not None and not reasons:
                decision = decide(ar, policy)
                if decision.decision != REQUIRE_APPROVAL:
                    reasons += decision.reasons or [f"PDP_{decision.decision.upper()}"]
            config_version = policy.version if policy else "UNAVAILABLE"
            gw_prov = self._tool_provenance(cur, config_version)
            pdp_ref = decision.policy_decision_ref if decision else new_id("pdp")
            final_status = "rejected" if reasons else "pending_approval"
            stored = {**ar, "status": final_status, "policy_decision_ref": pdp_ref}
            if decision and not reasons:
                stored["tier"] = decision.tier
            self.store.insert_action_request(cur, stored)

            agent_actor = {"type": "agent", "id": ar["proposed_by"]}
            rids = [self._action_receipt(cur, "ACTION_PROPOSED", ar, f"{ar['proposed_by']} proposed {ar['capability']}",
                                         ar["provenance_ids"], actor=agent_actor, effect="none",
                                         before_state=None, after_state={"status": "drafted"})["receipt_id"]]
            verdict = DENY if reasons else REQUIRE_APPROVAL
            rids.append(self._action_receipt(
                cur, "POLICY_DECIDED", stored, f"PDP: {verdict}", [gw_prov] + ar["provenance_ids"],
                policy_decision_ref=pdp_ref, effect="none",
                before_state={"status": "drafted"}, after_state={"status": final_status},
                details={"kind": "generic", "decision": verdict, "tier": 0, "reasons": reasons,
                         "policy_version": config_version})["receipt_id"])
            if not reasons:
                rids.append(self._action_receipt(
                    cur, "APPROVAL_REQUESTED", stored, "Michael's YES/NO/MODIFY/HOLD required (tier 0)",
                    [gw_prov] + ar["provenance_ids"], policy_decision_ref=pdp_ref, effect="none")["receipt_id"])
            return Result("rejected" if reasons else "pending_approval", ar["action_request_id"], final_status,
                          reasons, rids)

    # ------------------------------------------------------------------ approvals
    def _approval_problems(self, approval: dict, ar: dict, policy: Policy) -> list[str]:
        p: list[str] = []
        rules = policy.data["approval"]
        if approval["decider"] not in rules["approvers"]:
            p.append(f"DECIDER_NOT_APPROVER:{approval['decider']}")
        if approval["channel"] not in rules["allowed_channels"]:
            p.append(f"CHANNEL_NOT_ALLOWED:{approval['channel']}")
        if approval["scope"] not in rules["allowed_scopes"]:
            p.append(f"SCOPE_NOT_ALLOWED:{approval['scope']} (no delegation in wave one)")
        if approval["payload_hash_seen"] != ar["payload_hash"]:
            p.append("APPROVAL_PAYLOAD_HASH_MISMATCH")
        need_step_up = (ar["category"] in rules["step_up_required"]["categories"]
                        or ar["reversibility"] in rules["step_up_required"]["reversibility"])
        if need_step_up and not (approval.get("auth_context") or {}).get("step_up"):
            p.append("STEP_UP_REQUIRED")
        if not (approval.get("auth_context") or {}).get("method"):
            p.append("AUTH_CONTEXT_REQUIRED")
        return p

    def _expiry_problems(self, approval: dict, ar: dict, policy: Policy) -> list[str]:
        p: list[str] = []
        now = self.clock()
        skew = timedelta(seconds=policy.data["clock_skew_seconds"])
        try:
            decided = parse_ts(approval["decided_at"])
            if decided > now + skew:
                p.append("APPROVAL_DECIDED_IN_FUTURE")
            ttl_cap = decided + timedelta(seconds=policy.data["approval"]["max_approval_ttl_seconds"])
            exp = parse_ts(approval["expires_at"]) if approval.get("expires_at") else ttl_cap
            if now >= min(exp, ttl_cap):
                p.append("APPROVAL_EXPIRED")
            if now >= parse_ts(ar["expires_at"]):
                p.append("ACTION_REQUEST_EXPIRED")
        except ValueError as exc:
            p.append(f"BAD_TIMESTAMP:{exc}")
        return p

    def record_approval(self, approval: dict) -> Result:
        """Record Michael's decision (append-only). Called by the Operator UI / CLI approval
        surface, never by an agent. Validity is re-checked at execution time (G1–G3)."""
        contracts.require_valid("approval", approval)
        policy, policy_err = self._policy()
        with self.store.tx() as cur:
            ar = self.store.get_action_request(cur, approval["action_request_id"])
            if ar is None:
                raise GatewayRefused(f"unknown action request {approval['action_request_id']}")
            if ar["status"] not in ("pending_approval", "held"):
                raise GatewayRefused(f"{ar['action_request_id']} is {ar['status']}; not awaiting a decision")
            self.store.insert_approval(cur, approval)
            human_prov = {"provenance_id": new_id("prov"), "created_at": fmt_ts(self.clock()), "actor_type": "human",
                          "human_actor": approval["decider"], "basis": "FACT", "approval_id": approval["approval_id"]}
            self.store.insert_provenance(cur, human_prov)

            problems = [policy_err] if policy_err else (
                self._approval_problems(approval, ar, policy) + self._expiry_problems(approval, ar, policy))
            d = approval["decision"]
            if d == "YES":
                new_status = "approved" if not problems else ar["status"]
            elif d == "NO":
                new_status = "rejected"
            elif d == "HOLD":
                new_status = "held"
            else:  # MODIFY: this request is closed; the new one is proposed with derived_from
                new_status = "rejected"
            before = ar["status"]
            ar = self.store.set_status(cur, ar, new_status)
            rids = [self._action_receipt(
                cur, "APPROVAL_DECIDED", ar, f"Michael decided {d}" + (" (INVALID: not executable)" if problems and d == "YES" else ""),
                [human_prov["provenance_id"]], actor={"type": "human", "id": approval["decider"]},
                approval_id=approval["approval_id"], effect="none",
                before_state={"status": before}, after_state={"status": new_status},
                details={"kind": "generic", "decision": d, "problems": problems,
                         **({"closed_by": "MODIFY", "new_action_request_id": approval["modifications"].get("new_action_request_id")}
                            if d == "MODIFY" else {})})["receipt_id"]]
            if d == "YES" and not problems:
                reasons, rid = self._reserve(cur, ar, policy, approval["approval_id"])
                if rid:
                    rids.append(rid)
                problems += reasons
            return Result("recorded", ar["action_request_id"], new_status, problems, rids)

    # ------------------------------------------------------------------ budget (G5)
    def _required_micros(self, ar: dict) -> int:
        est = to_micros(ar["estimated_cost"]["amount"]) if "estimated_cost" in ar else 0
        mx = to_micros(ar["max_cost"]["amount"]) if "max_cost" in ar else None
        return max(est, mx if mx is not None else 0)

    def _budget_problems(self, cur, ar: dict, policy: Policy, mode: str, exclude_own: int = 0) -> list[str]:
        p: list[str] = []
        caps = policy.data["budgets"][mode]
        bucket = policy.bucket_for(ar["category"])
        bcaps = caps["buckets"][bucket]
        need = self._required_micros(ar)
        if "estimated_cost" in ar and "max_cost" in ar and ar["estimated_cost"]["amount"] > ar["max_cost"]["amount"]:
            p.append("ESTIMATE_EXCEEDS_MAX_COST")
        day = self._now_local(policy).date().isoformat()
        if need > to_micros(bcaps["per_action_hard_cap"]):
            p.append(f"BUDGET_PER_ACTION_CAP:{bucket}:{mode}")
        if self.store.spent_micros(cur, mode, day, bucket) - exclude_own + need > to_micros(bcaps["daily_hard_cap"]):
            p.append(f"BUDGET_DAILY_CAP:{bucket}:{mode}")
        if self.store.spent_micros(cur, mode, day) - exclude_own + need > to_micros(caps["global_daily_hard_cap"]):
            p.append(f"BUDGET_GLOBAL_DAILY_CAP:{mode}")
        if bucket == "money" and not exclude_own:
            since = fmt_ts(self.clock() - timedelta(hours=1))
            limit = policy.data["budgets"]["velocity"]["money_bucket_actions_per_hour"]
            if self.store.bucket_actions_since(cur, mode, bucket, since) + 1 > limit:
                p.append("BUDGET_VELOCITY_CAP:money")
        return p

    def _reserve(self, cur, ar: dict, policy: Policy, approval_id: str | None) -> tuple[list[str], str | None]:
        mode = "dry_run" if self._dry_run_forced(policy) else "live"
        problems = self._budget_problems(cur, ar, policy, mode)
        if problems:
            return problems, None
        need = self._required_micros(ar)
        day = self._now_local(policy).date().isoformat()
        self.store.reserve(cur, ar["action_request_id"], mode, policy.bucket_for(ar["category"]), need, day)
        gw = self._tool_provenance(cur, policy.version)
        extra = {"approval_id": approval_id} if approval_id else {}
        r = self._action_receipt(cur, "BUDGET_RESERVED", ar, f"reserved {need / 1e6:.6f} USD ({mode})",
                                 [gw] + ar["provenance_ids"], effect="none", **extra,
                                 budget_effect={"category": policy.bucket_for(ar["category"]),
                                                "amount": need / 1e6, "currency": "USD"},
                                 details={"kind": "money", "mode": mode, "state": "reserved"})
        return [], r["receipt_id"]

    def _release(self, cur, ar: dict, prov: list[str], approval_id: str | None, why: str) -> None:
        res = self.store.reservation(cur, ar["action_request_id"])
        if res is None or res["state"] != "reserved":
            return
        self.store.settle(cur, ar["action_request_id"], "released")
        extra = {"approval_id": approval_id} if approval_id else {}
        self._action_receipt(cur, "BUDGET_RELEASED", ar, f"released reservation: {why}", prov + ar["provenance_ids"],
                             effect="none", **extra,
                             budget_effect={"category": res["bucket"], "amount": res["amount_micros"] / 1e6, "currency": "USD"},
                             details={"kind": "money", "mode": res["mode"], "state": "released"})

    # ------------------------------------------------------------------ execution guard
    def _guard(self, cur, ar: dict, policy: Policy | None, policy_err: str | None) -> tuple[dict[str, list[str]], dict | None, bool]:
        """Run all 8 checks. Returns ({check: [failures]}, approval, dry_run)."""
        f: dict[str, list[str]] = {f"G{i}": [] for i in range(1, 9)}
        # G7 first: kill switch (fail closed on unreadable).
        f["G7"] += self.panic.read().blocks(ar["proposed_by"], ar["capability"], ar["category"])
        if policy is None:
            for k in f:
                f[k].append(policy_err or "POLICY_UNREADABLE")
            return f, self.store.latest_approval(cur, ar["action_request_id"]), True
        approval = self.store.latest_approval(cur, ar["action_request_id"])
        # G1 approval valid
        if approval is None:
            f["G1"].append("NO_APPROVAL")
        else:
            if approval["decision"] != "YES":
                f["G1"].append(f"LATEST_DECISION_IS_{approval['decision']}")
            f["G1"] += [x for x in self._approval_problems(approval, ar, policy) if x != "APPROVAL_PAYLOAD_HASH_MISMATCH"]
            # G2 expiry
            f["G2"] += self._expiry_problems(approval, ar, policy)
        if ar["status"] != "approved":
            f["G1"].append(f"STATUS_NOT_APPROVED:{ar['status']}")
        # G3 payload hash equality (recomputed, stored, and what Michael saw)
        try:
            recomputed = payload_hash(ar["payload"])
        except ValueError as exc:
            recomputed = f"unhashable:{exc}"
        if recomputed != ar["payload_hash"]:
            f["G3"].append("PAYLOAD_MUTATED_AFTER_PROPOSAL")
        if approval is not None and approval["payload_hash_seen"] != ar["payload_hash"]:
            f["G3"].append("APPROVAL_PAYLOAD_HASH_MISMATCH")
        # G4 idempotency
        if self.store.get_claim(cur, ar["idempotency_key"]) is not None:
            f["G4"].append("IDEMPOTENCY_KEY_ALREADY_CLAIMED")
        # G6 grant constraints: re-run the PDP against the CURRENT policy.
        try:
            contracts.require_valid("action-request", ar)
        except contracts.ContractViolation as exc:
            f["G6"].append(f"CONTRACT:{exc}")
        else:
            d = decide(ar, policy)
            if d.decision != REQUIRE_APPROVAL:
                f["G6"] += d.reasons
            if ar["tier"] != 0:
                f["G6"].append(f"TIER_NOT_ZERO:{ar['tier']}")
        cat = policy.category(ar["category"])
        if cat and cat["quiet_hours"] and self._in_quiet_hours(policy):
            f["G6"].append("QUIET_HOURS")
        # G8 dry-run forced
        dry_run = self._dry_run_forced(policy)
        if not dry_run:
            f["G8"].append("LIVE_MODE_NOT_AVAILABLE_IN_WAVE_ONE")
        cap = policy.capability(ar["capability"])
        eff = self._effectors.get(cap["effector"]) if cap else None
        if eff is None:
            f["G8"].append("NO_EFFECTOR")
        elif dry_run and not eff.supports_dry_run:
            f["G8"].append(f"EFFECTOR_CANNOT_DRY_RUN:{eff.name}")
        # G5 budget (only meaningful once the request is otherwise executable)
        if not any(f.values()):
            res = self.store.reservation(cur, ar["action_request_id"])
            mode = "dry_run" if dry_run else "live"
            if res is not None and res["state"] == "reserved":
                if res["mode"] != mode or res["amount_micros"] < self._required_micros(ar):
                    f["G5"].append("RESERVATION_DOES_NOT_COVER_ACTION")
                else:
                    f["G5"] += self._budget_problems(cur, ar, policy, mode, exclude_own=res["amount_micros"])
            elif res is not None:
                f["G5"].append(f"RESERVATION_{res['state'].upper()}")
            else:
                reasons, _ = self._reserve(cur, ar, policy, approval["approval_id"] if approval else None)
                f["G5"] += reasons
        return f, approval, dry_run

    def execute(self, action_request_id: str) -> Result:
        """Run the guard; on success call the effector (DRY-RUN) and receipt the outcome."""
        policy, policy_err = self._policy()
        # ---- Phase A: guard + claim + ACTION_EXECUTING, one transaction --------------
        with self.store.tx() as cur:
            ar = self.store.get_action_request(cur, action_request_id)
            if ar is None:
                raise GatewayRefused(f"unknown action request {action_request_id}")
            claim = self.store.get_claim(cur, ar["idempotency_key"])
            if claim is not None and claim["state"] == "executed":
                return Result("duplicate", action_request_id, ar["status"], ["ALREADY_EXECUTED"],
                              effector_response=json.loads(claim["result"]))
            if claim is not None and claim["state"] == "executing":
                return Result("refused", action_request_id, ar["status"],
                              ["IN_FLIGHT_OR_CRASHED: reconciliation required, never blind-retry"])
            failures, approval, dry_run = self._guard(cur, ar, policy, policy_err)
            gw = self._tool_provenance(cur, policy.version if policy else "UNAVAILABLE")
            flat = [f"{k}:{r}" for k, rs in failures.items() for r in rs]
            if flat:
                new_status = ar["status"]
                if failures["G2"] and ar["status"] in ("approved", "held", "pending_approval"):
                    new_status = "expired"
                elif failures["G3"] and ar["status"] == "approved":
                    new_status = "failed"
                before = ar["status"]
                ar = self.store.set_status(cur, ar, new_status)
                if new_status in ("expired", "failed"):
                    self._release(cur, ar, [gw], approval["approval_id"] if approval else None, new_status)
                details = {"kind": "generic", "guard": "refused", "failed_checks": failures}
                if approval is not None:
                    r = self._action_receipt(cur, "ACTION_FAILED", ar, "execution guard refused; effector NOT called",
                                             [gw] + ar["provenance_ids"], approval_id=approval["approval_id"],
                                             effect="none", before_state={"status": before}, after_state={"status": new_status},
                                             effector_response={"provider": "none", "status": "guard_refused", "dry_run": True},
                                             details=details)
                else:
                    r = self._action_receipt(cur, "POLICY_DECIDED", ar, "execution guard refused: no approval",
                                             [gw] + ar["provenance_ids"], effect="none",
                                             before_state={"status": before}, after_state={"status": new_status},
                                             details={**details, "decision": DENY})
                return Result("refused", action_request_id, new_status, flat, [r["receipt_id"]])
            self.store.claim(cur, ar["idempotency_key"], action_request_id)
            ar = self.store.set_status(cur, ar, "executing")
            r_exec = self._action_receipt(cur, "ACTION_EXECUTING", ar, f"guard passed (8/8); calling effector dry_run={dry_run}",
                                          [gw] + ar["provenance_ids"], approval_id=approval["approval_id"],
                                          key=f"{ar['idempotency_key']}:EXECUTING", effect="none",
                                          policy_decision_ref=ar.get("policy_decision_ref"),
                                          before_state={"status": "approved"}, after_state={"status": "executing"},
                                          details={"kind": "generic", "guard": "passed", "dry_run": dry_run})
            prov = [gw]
        approval_id = approval["approval_id"]

        # ---- Phase B: last-instant kill-switch read, then the effector ------------
        late = self.panic.read().blocks(ar["proposed_by"], ar["capability"], ar["category"])
        response, error = None, None
        if late:
            error = "FROZE_BEFORE_EFFECTOR:" + ",".join(late)
        else:
            effector = self._effectors[policy.capability(ar["capability"])["effector"]]
            token = self._minter.mint(action_request_id, ar["payload_hash"], ar["idempotency_key"], dry_run)
            try:
                response = effector.execute(token, ar)
            except Exception as exc:  # noqa: BLE001 - any effector failure is receipted
                error = f"EFFECTOR_ERROR:{type(exc).__name__}:{exc}"
            if response is not None and dry_run and response.get("dry_run") is not True:
                error = "DRY_RUN_INVARIANT_VIOLATED: effector did not confirm dry_run"
                self.engage_panic("L3", None, actor="action-gateway", reason=error)

        # ---- Phase C: outcome receipts + budget settle, one transaction -----------
        with self.store.tx() as cur:
            if error:
                status = "cancelled_by_freeze" if error.startswith("FROZE_BEFORE") else "failed"
                self.store.finish_claim(cur, ar["idempotency_key"], "failed", {"error": error})
                ar = self.store.set_status(cur, ar, status)
                self._release(cur, ar, prov, approval_id, status)
                r = self._action_receipt(cur, "ACTION_FAILED", ar, error, prov + ar["provenance_ids"],
                                         approval_id=approval_id, key=f"{ar['idempotency_key']}:FAILED", effect="none",
                                         before_state={"status": "executing"}, after_state={"status": status},
                                         # Recorded as returned — an invariant violation must stay visible.
                                         effector_response=response or {"provider": "none", "status": "not_called",
                                                                        "dry_run": True},
                                         details={"kind": "generic", "error": error})
                return Result("failed", action_request_id, status, [error], [r_exec["receipt_id"], r["receipt_id"]], response)
            res = self.store.reservation(cur, action_request_id)
            self.store.settle(cur, action_request_id, "committed")
            self.store.finish_claim(cur, ar["idempotency_key"], "executed", response)
            ar = self.store.set_status(cur, ar, "executed")
            rids = [r_exec["receipt_id"]]
            if res is not None:
                rids.append(self._action_receipt(
                    cur, "BUDGET_COMMITTED", ar, f"committed ({res['mode']}; no real money moved)" if dry_run else "committed",
                    prov + ar["provenance_ids"], approval_id=approval_id, effect="none",
                    budget_effect={"category": res["bucket"], "amount": res["amount_micros"] / 1e6, "currency": "USD"},
                    details={"kind": "money", "mode": res["mode"], "state": "committed"})["receipt_id"])
            rids.append(self._action_receipt(
                cur, "ACTION_EXECUTED", ar, f"{ar['capability']} executed (DRY-RUN)" if dry_run else f"{ar['capability']} executed",
                prov + ar["provenance_ids"], approval_id=approval_id, key=f"{ar['idempotency_key']}:EXECUTED",
                effect=EFFECT_BY_CATEGORY[ar["category"]], tool_name=f"effector:{response['provider']}",
                before_state={"status": "executing"}, after_state={"status": "executed"},
                effector_response=response, details={"kind": "generic", "dry_run": dry_run})["receipt_id"])
            return Result("executed", action_request_id, "executed", [], rids, response)

    # ------------------------------------------------------------------ PANIC
    def _panic_receipt(self, cur, level: str, target: str | None, engage: bool, actor: str, reason: str,
                       before: dict, after: dict, config_version: str) -> dict:
        prov = self._tool_provenance(cur, config_version, tool="mbos_governance.panic", human=actor if actor == "michael" else None)
        strip = lambda b: {k: v for k, v in b.items() if k != "checksum"}  # noqa: E731
        return self.store.append_receipt(cur, {
            "type": "KILL_SWITCH_CHANGED",
            "actor": {"type": "human" if actor == "michael" else "system", "id": actor},
            "intent": f"PANIC {level} {'ENGAGE' if engage else 'RELEASE'} {target or 'global'}: {reason}",
            "entity_type": "panic_state", "entity_id": f"{level}:{target or 'global'}",
            "effect": "update", "before_state": strip(before), "after_state": strip(after),
            "provenance_ids": [prov], "idempotency_key": f"panic:{after['revision']}:{new_ulid()}",
            "details": {"kind": "generic", "level": level, "engage": engage},
        })

    def engage_panic(self, level: str, target: str | None, actor: str, reason: str) -> dict:
        """Freeze. Anyone (human, gateway, ops script) may engage. The state file is written
        FIRST so a broken database can never prevent a freeze; the receipt follows. If the
        receipt cannot be written the freeze stands and the event is journaled for replay."""
        before, after = self.panic.mutate(level, target, True, actor, reason)
        policy, _ = self._policy()
        cancelled: list[str] = []
        try:
            with self.store.tx() as cur:
                self._panic_receipt(cur, level, target, True, actor, reason, before, after,
                                    policy.version if policy else "UNAVAILABLE")
                if level == "L3":
                    cancelled = self._cancel_queued(cur, policy)
        except Exception as exc:  # noqa: BLE001
            line = json.dumps({"ts": fmt_ts(self.clock()), "event": "KILL_SWITCH_CHANGED", "level": level,
                               "target": target, "actor": actor, "reason": reason, "revision": after["revision"],
                               "receipt_error": f"{type(exc).__name__}: {exc}"})
            with open(self._journal, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            print(f"WARNING: freeze engaged but receipt failed ({exc}); journaled to {self._journal}", file=sys.stderr)
        return {"state": after, "cancelled": cancelled}

    def release_panic(self, level: str, target: str | None, actor: str, reason: str) -> dict:
        """Unfreeze. Only a policy approver may release, the policy must be readable, and the
        release only stands if its receipt commits; otherwise the previous state is restored."""
        policy, err = self._policy()
        if policy is None:
            raise GatewayRefused(f"cannot release PANIC while policy is unreadable: {err}")
        if actor not in policy.data["approval"]["approvers"]:
            raise GatewayRefused(f"{actor} may not release PANIC")
        if not reason.strip():
            raise GatewayRefused("release requires a reason")
        before_raw = self.panic.read_raw()
        before, after = self.panic.mutate(level, target, False, actor, reason)
        try:
            with self.store.tx() as cur:
                self._panic_receipt(cur, level, target, False, actor, reason, before, after, policy.version)
        except BaseException:
            if before_raw is not None and self.panic.read().readable:
                self.panic.mutate(level, target, True, "action-gateway", "release rolled back: receipt failed")
            raise
        return {"state": after}

    def _cancel_queued(self, cur, policy: Policy | None) -> list[str]:
        """L3: approved-but-not-started requests become cancelled_by_freeze (never retried)."""
        out = []
        gw = self._tool_provenance(cur, policy.version if policy else "UNAVAILABLE")
        for ar in self.store.requests_with_status(cur, ("approved",)):
            approval = self.store.latest_approval(cur, ar["action_request_id"])
            ar = self.store.set_status(cur, ar, "cancelled_by_freeze")
            self._release(cur, ar, [gw], approval["approval_id"] if approval else None, "cancelled_by_freeze")
            if approval is not None:
                self._action_receipt(cur, "ACTION_FAILED", ar, "cancelled by L3 PANIC before start", [gw] + ar["provenance_ids"],
                                     approval_id=approval["approval_id"], effect="none",
                                     before_state={"status": "approved"}, after_state={"status": "cancelled_by_freeze"},
                                     effector_response={"provider": "none", "status": "cancelled_by_freeze", "dry_run": True})
            out.append(ar["action_request_id"])
        return out
