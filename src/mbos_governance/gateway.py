"""Action Gateway (PEP) + execution guard — the ONLY path from a proposal to an effector.

Core law: no action without a receipt; no receipt without provenance.
Governance rule: models PROPOSE (ActionRequest); this non-LLM code AUTHORIZES.

Storage is lane D's canonical Postgres schema through `mbos.*` (E-02; R1/R2/R4/R5). Every status change
and its receipt commit in one transaction, and lane D's deferred triggers refuse a commit without one.
R4: the gateway owns the action-status edges and their receipts.

  propose()          drafted -> classified -> pending_approval | rejected
                     receipts: ACTION_PROPOSED, POLICY_DECIDED, APPROVAL_REQUESTED (+INJECTION_SUSPECTED)
  record_approval()  valid YES -> approved (+BUDGET_RESERVED) | NO -> rejected | HOLD -> held | MODIFY -> rejected(closed)
                     an invalid YES is NOT recorded as an approval (lane D refuses it too); POLICY_DECIDED notes it
  execute()          approved -> executing (+claim) -> executed | failed | cancelled_by_freeze; approved -> expired | failed

Execution guard — all 8 checks (ADR-0005 §2), evaluated in one transaction with the request row locked:
  G1 approval valid      latest Approval is YES, by an allowed approver/channel/scope, step-up when required
  G2 not expired         approval expiry, approval TTL cap, ActionRequest.expires_at
  G3 payload_hash        sha256(CJSON(payload)) == ActionRequest.payload_hash == Approval.payload_hash_seen
  G4 idempotency         no execution claim (mbos.effector_calls) for this request (exactly-once effect)
  G5 budget reserved     reservation exists or is made now (mbos.budget_reserve_caps: per-action/daily/global/velocity)
  G6 grant constraints   PDP re-run on CURRENT policy, tier 0, quiet hours, secret re-scan
  G7 kill switch clear   PANIC L3 / L1 agent / L2 capability|category; unreadable => FROZEN
  G8 dry-run forced      system_mode round_one|mvp => dry_run=True; effector must support it and must echo it
Policy unreadable => every check fails closed. Lane D re-checks G1–G3 at the approved->executing edge.
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

import psycopg

from . import __version__, contracts
from .campaigns import decide_campaign
from .content_guard import ContentRulesStore, ContentRulesUnavailable, injection_findings, secret_findings
from .effectors import DryRunEffector, Effector, TokenMinter
from .hooks import run_hooks
from .ids import fmt_ts, new_ulid, parse_ts, payload_hash, utcnow
from .policy import DENY, REQUIRE_APPROVAL, Policy, PolicyStore, PolicyUnavailable, decide, step_up_required
from .store_pg import DurableProviderLedger, PgGovernanceStore, PgPanicStore

GATEWAY_ACTOR = {"type": "system", "id": "action-gateway"}
DRY_RUN_MODES = ("round_one", "mvp")
CURRENCY = "USD"

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


def to_amount(value) -> Decimal:
    """Money to lane D's numeric(14,6), rounded UP (never under-reserve)."""
    return Decimal(str(value)).quantize(Decimal("0.000001"), rounding=ROUND_CEILING)


def actor_json(actor: str) -> dict:
    if actor == "michael":
        return {"type": "human", "id": actor}
    if actor.startswith("agent-"):
        return {"type": "agent", "id": actor}
    return {"type": "system", "id": actor}


class ActionGateway:
    def __init__(self, store: PgGovernanceStore, policy_store: PolicyStore, panic_store: PgPanicStore, clock=utcnow,
                 journal_path: str | Path | None = None, panic_hooks: list | None = None,
                 content_rules: ContentRulesStore | None = None):
        self.store = store
        self.policies = policy_store
        self.panic = panic_store
        self.clock = clock
        self._minter = TokenMinter(secrets.token_bytes(32))
        self._effectors: dict[str, Effector] = {"dryrun": DryRunEffector(self._minter, DurableProviderLedger(store))}
        self._journal = Path(journal_path) if journal_path else Path("var/panic.journal.jsonl")
        self.panic_hooks = list(panic_hooks or [])  # hooks.py: DBOS cancel, egress, LiteLLM (E-03)
        # E-04: secret scan + injection tripwire rules (data). Default: next to the policy file.
        if content_rules is None:  # rules travel with the policy: DB store (E-06) or the file next to policy.v1.json
            content_rules = (policy_store.content_rules_store() if hasattr(policy_store, "content_rules_store")
                             else ContentRulesStore(Path(policy_store.path).with_name("content_rules.v1.json")))
        self.content_rules = content_rules

    # ------------------------------------------------------------------ helpers
    def _policy(self) -> tuple[Policy | None, str | None]:
        try:
            return self.policies.current(), None
        except PolicyUnavailable as exc:
            return None, f"POLICY_UNREADABLE:{exc}"

    def _tool_provenance(self, cur, config_version: str, tool: str = "mbos_governance.gateway") -> str:
        return self.store.record_provenance(cur, {"actor_type": "system", "basis": "FACT", "tool_name": tool,
                                                  "tool_version": __version__, "config_version": config_version})

    @staticmethod
    def _receipt(cur, store, rtype: str, ar: dict, intent: str, prov_ids: list[str], *,
                 actor: dict = GATEWAY_ACTOR, key: str | None = None, **extra) -> dict:
        """A receipt WITHOUT a status change (refusals, tripwires). Status changes use set_status."""
        return store.append_receipt(cur, {
            "type": rtype, "actor": actor, "intent": intent, "item_id": ar["item_id"],
            "action_request_id": ar["action_request_id"], "capability": ar["capability"],
            "payload_hash": ar["payload_hash"], "provenance_ids": prov_ids,
            "idempotency_key": key or f"{ar['action_request_id']}:{rtype}:{new_ulid()}",
            "details": {"kind": "generic"}, **extra})

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
        contracts.require_valid("provenance", prov)
        with self.store.tx("gateway") as cur:
            return self.store.record_provenance(cur, prov)

    # ------------------------------------------------------------------ propose
    def _proposal_problems(self, ar: dict, caller: str, policy: Policy | None) -> list[str]:
        p: list[str] = []
        now = self.clock()
        if ar["proposed_by"] != caller:
            p.append(f"CALLER_MISMATCH:{caller} cannot propose as {ar['proposed_by']}")
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

    def _content_rules(self):
        try:
            return self.content_rules.current(), None
        except ContentRulesUnavailable as exc:
            return None, f"CONTENT_RULES_UNREADABLE:{exc}"

    def _tripwire_receipt(self, cur, ar: dict, intent: str, details: dict, config_version: str) -> dict:
        """INJECTION_SUSPECTED. Findings carry rule ids + JSON paths only, never matched values."""
        prov = self._tool_provenance(cur, config_version, tool="mbos_governance.content_guard")
        stored = details.get("stored", True)
        link = ({"action_request_id": ar["action_request_id"]} if stored   # FK: only a stored request can be linked
                else {})
        return self.store.append_receipt(cur, {
            "type": "INJECTION_SUSPECTED", "actor": GATEWAY_ACTOR, "intent": intent,
            "item_id": ar["item_id"], **link, "capability": ar["capability"],
            "payload_hash": ar["payload_hash"], "effect": "none", "provenance_ids": [prov] + ar["provenance_ids"],
            "idempotency_key": f"{ar['action_request_id']}:INJECTION_SUSPECTED:{new_ulid()}",
            "details": {"kind": "generic", "proposed_action_request_id": ar["action_request_id"], **details},
        })

    def propose(self, ar: dict, caller: str, untrusted_texts: list[dict] | None = None,
                campaign: dict | None = None) -> Result:
        """An agent submits a proposed side-effect. Never executes anything.

        `untrusted_texts`: the attacker-controllable inputs that fed this proposal (listing body,
        inbound message), as [{"ref": ..., "text": ...}]. Supplying any marks the request tainted
        (tier 0, step-up on YES); injection markers in them or in the payload fire the tripwire.

        `campaign` (E-17): the wanted-campaign document this request was drafted for. A campaign-sourced request is
        decided against policy `campaigns` (WATCH_ONLY/RECOMMEND request nothing; ASSISTED_DEAL drafts offer.*/comms.*
        only; BOUNDED_AUTOPILOT -> AUTOPILOT_NOT_AUTHORIZED; unknown level -> deny), is tainted (tier 0 + step-up
        forced), and can never skip approval: the guard still requires an approved YES on the exact payload."""
        contracts.require_valid("action-request", ar)
        try:
            recomputed = payload_hash(ar["payload"])
        except (ValueError, TypeError) as exc:
            # Not canonical JSON (NaN/Infinity/non-JSON type): it cannot be stored or receipted faithfully.
            raise GatewayRefused(f"PAYLOAD_NOT_HASHABLE:{exc}") from exc
        if recomputed != ar["payload_hash"]:
            raise GatewayRefused("PAYLOAD_HASH_MISMATCH")  # lane D refuses it too (MB007): never stored
        if untrusted_texts is not None and not (isinstance(untrusted_texts, list) and all(
                isinstance(t, dict) and isinstance(t.get("text"), str) and isinstance(t.get("ref"), str)
                for t in untrusted_texts)):
            raise GatewayRefused("UNTRUSTED_TEXTS_MALFORMED: expected [{'ref': str, 'text': str}]")
        rules, rules_err = self._content_rules()
        if rules is None:
            raise GatewayRefused(rules_err)  # fail closed: cannot scan => cannot propose
        secrets_found = secret_findings(rules, ar["payload"])
        if secrets_found:
            # Refused at the door: the payload (and the secret) is never stored. Receipt has paths only.
            with self.store.tx("gateway") as cur:
                self._tripwire_receipt(cur, ar, "secret-shaped content in an outbound payload; proposal refused, not stored",
                                       {"finding": "secret_in_outbound_payload", "rules_version": rules.version,
                                        "findings": [f.as_dict() for f in secrets_found], "stored": False},
                                       rules.version)
            raise GatewayRefused("SECRET_IN_PAYLOAD:" + ",".join(f"{f.rule}@{f.path}" for f in secrets_found))
        injections = injection_findings(rules, untrusted=untrusted_texts or [], payload=ar["payload"])
        if untrusted_texts or injections or campaign is not None:
            ar = {**ar, "untrusted_inputs_present": True, "tier": 0}  # taint: schema then pins tier 0
        policy, policy_err = self._policy()
        panic_state = self.panic.read()
        areq = ar["action_request_id"]
        with self.store.tx("gateway") as cur:
            existing = self.store.find_by_idempotency_key(cur, ar["idempotency_key"])
            if existing is not None:
                return Result("duplicate", existing["action_request_id"], existing["status"],
                              ["IDEMPOTENCY_KEY_ALREADY_PROPOSED"])
            if self.store.get_action_request(cur, areq) is not None:
                raise GatewayRefused(f"{areq} already exists")
            missing = self.store.missing_provenance(cur, ar["provenance_ids"])
            if missing:
                raise GatewayRefused(f"no action without provenance: {missing} not recorded")
            if ar.get("derived_from") and self.store.get_action_request(cur, ar["derived_from"]) is None:
                raise GatewayRefused(f"derived_from {ar['derived_from']} unknown")

            reasons = self._proposal_problems(ar, caller, policy)
            reasons += panic_state.blocks(ar["proposed_by"], ar["capability"], ar["category"])
            if policy_err:
                reasons.append(policy_err)
            camp = None
            if campaign is not None:
                if policy is None:
                    reasons.append("CAMPAIGN_POLICY_UNREADABLE")
                else:
                    cost = (ar.get("max_cost") or ar.get("estimated_cost") or {}).get("amount")
                    camp = decide_campaign(campaign, policy, capability=ar["capability"],
                                           cost_usd=cost, now=self.clock())
                    if camp.decision != REQUIRE_APPROVAL:
                        reasons += camp.reasons or ["CAMPAIGN_DENIED"]
            decision = None
            if policy is not None and not reasons:
                decision = decide(ar, policy)
                if decision.decision != REQUIRE_APPROVAL:
                    reasons += decision.reasons or [f"PDP_{decision.decision.upper()}"]
            config_version = policy.version if policy else "UNAVAILABLE"
            gw = self._tool_provenance(cur, config_version)
            pdp_ref = decision.policy_decision_ref if decision else f"pdp_{new_ulid()}"
            prov = [gw] + ar["provenance_ids"]

            doc = {k: v for k, v in ar.items() if k not in ("status", "policy_decision_ref")}
            self.store.propose_action(cur, doc, {"type": "agent", "id": ar["proposed_by"]},
                                      f"{ar['proposed_by']} proposed {ar['capability']}", f"{areq}:PROPOSED")
            if injections:
                self._tripwire_receipt(cur, ar, "prompt-injection markers in inputs feeding this proposal; "
                                       "forced tier 0, needs review, step-up required",
                                       {"finding": "injection_suspected", "rules_version": rules.version,
                                        "findings": [f.as_dict() for f in injections], "needs_review": True,
                                        "untrusted_refs": [t["ref"] for t in (untrusted_texts or [])]},
                                       rules.version)
            verdict = DENY if reasons else REQUIRE_APPROVAL
            details = {"kind": "generic", "decision": verdict, "tier": 0, "reasons": reasons, "policy_version": config_version}
            if campaign is not None:
                details["campaign"] = {"campaign_id": (campaign or {}).get("campaign_id") if isinstance(campaign, dict) else None,
                                       **(camp.as_dict() if camp else {"decision": "deny"})}
            rids = [self.store.set_status(cur, areq, "classified", "POLICY_DECIDED", GATEWAY_ACTOR, f"PDP: {verdict}",
                                          prov, f"{areq}:CLASSIFIED",
                                          {"policy_decision_ref": pdp_ref, "effect": "none", "details": details},
                                          tier=decision.tier if decision and not reasons else 0)]
            if reasons:
                final = "rejected"
                rids.append(self.store.set_status(cur, areq, "rejected", "POLICY_DECIDED", GATEWAY_ACTOR,
                                                  "PDP: deny — " + "; ".join(reasons)[:300], prov, f"{areq}:REJECTED",
                                                  {"effect": "none", "details": details}))
            else:
                final = "pending_approval"
                rids.append(self.store.set_status(
                    cur, areq, "pending_approval", "APPROVAL_REQUESTED", GATEWAY_ACTOR,
                    "Michael's YES/NO/MODIFY/HOLD required (tier 0)" + (" — NEEDS REVIEW: injection tripwire fired" if injections else ""),
                    prov, f"{areq}:APPROVAL_REQUESTED",
                    {"effect": "none", "details": {"kind": "generic", "needs_review": bool(injections),
                                                   "tainted": bool(ar.get("untrusted_inputs_present"))}}))
            return Result(final, areq, final, reasons, rids)

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
        if step_up_required(ar, policy) and not (approval.get("auth_context") or {}).get("step_up"):
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
        """Record Michael's decision (append-only, role approver). Called by the Operator UI / CLI
        approval surface, never by an agent. A YES that fails validation is not recorded as an
        approval (lane D's trigger would refuse it as well); a POLICY_DECIDED receipt notes the attempt.
        Validity is re-checked at execution time (G1–G3)."""
        contracts.require_valid("approval", approval)
        d = approval["decision"]
        if d == "MODIFY" and not {"new_action_request_id", "new_payload_hash"} <= set(approval["modifications"]):
            raise GatewayRefused("MODIFY needs modifications.new_action_request_id and new_payload_hash")
        policy, policy_err = self._policy()
        areq = approval["action_request_id"]
        with self.store.tx("approver") as cur:
            ar = self.store.get_action_request(cur, areq, lock=True)
            if ar is None:
                raise GatewayRefused(f"unknown action request {areq}")
            if ar["status"] not in ("pending_approval", "held"):
                raise GatewayRefused(f"{areq} is {ar['status']}; not awaiting a decision")
            problems = [policy_err] if policy_err else (
                self._approval_problems(approval, ar, policy) + self._expiry_problems(approval, ar, policy))
            if d == "YES" and problems:
                prov = self._tool_provenance(cur, policy.version if policy else "UNAVAILABLE")
                r = self._receipt(cur, self.store, "POLICY_DECIDED", ar, "YES refused at the door; not recorded as an approval",
                                  [prov] + ar["provenance_ids"], effect="none",
                                  before_state={"status": ar["status"]}, after_state={"status": ar["status"]},
                                  details={"kind": "generic", "refused_approval": {
                                      "approval_id": approval["approval_id"], "decision": d, "decider": approval["decider"],
                                      "channel": approval["channel"], "problems": problems}})
                return Result("refused", areq, ar["status"], problems, [r["receipt_id"]])
            try:
                with cur.connection.transaction():  # savepoint
                    self.store.record_approval(cur, approval, {"type": "human", "id": approval["decider"]},
                                               f"Michael decided {d}", f"{approval['approval_id']}:DECIDED")
            except psycopg.Error as exc:
                if not (exc.sqlstate or "").startswith("MB"):
                    raise
                raise GatewayRefused(f"lane D refused the decision: {exc.diag.message_primary or exc}") from exc
            status = self.store.get_action_request(cur, areq)["status"]
        reasons: list[str] = []
        if d == "YES":
            with self.store.tx("gateway") as cur:
                ar = self.store.get_action_request(cur, areq, lock=True)
                reasons, _ = self._reserve(cur, ar, policy, approval["approval_id"])
                if reasons:  # a refused reservation is receipted too (E-09 alerts read it); G5 re-tries at execute
                    gw = self._tool_provenance(cur, policy.version)
                    self._receipt(cur, self.store, "POLICY_DECIDED", ar, "budget reservation refused at approval",
                                  [gw] + ar["provenance_ids"], effect="none",
                                  before_state={"status": ar["status"]}, after_state={"status": ar["status"]},
                                  details={"kind": "money", "budget_refused": reasons, "stage": "approval"})
        return Result("recorded", areq, status, reasons)

    # ------------------------------------------------------------------ budget (G5)
    def _required(self, ar: dict) -> Decimal:
        est = to_amount(ar["estimated_cost"]["amount"]) if "estimated_cost" in ar else Decimal(0)
        mx = to_amount(ar["max_cost"]["amount"]) if "max_cost" in ar else Decimal(0)
        return max(est, mx)

    @staticmethod
    def _bucket(policy: Policy, category: str) -> tuple[str, list[str]]:
        bucket = policy.bucket_for(category)
        return bucket, sorted(c for c, spec in policy.data["categories"].items() if spec["budget_bucket"] == bucket)

    def _reserve(self, cur, ar: dict, policy: Policy, approval_id: str | None) -> tuple[list[str], str | None]:
        """Reserve under lane D's single budget lock: bucket per-action / daily / global caps and the money
        ACTION-COUNT velocity (0013) all inside mbos.budget_reserve_caps."""
        mode = "dry_run" if self._dry_run_forced(policy) else "live"
        if "estimated_cost" in ar and "max_cost" in ar and ar["estimated_cost"]["amount"] > ar["max_cost"]["amount"]:
            return ["ESTIMATE_EXCEEDS_MAX_COST"], None
        bucket, cats = self._bucket(policy, ar["category"])
        caps = policy.data["budgets"][mode]
        bcaps = caps["buckets"][bucket]
        need = self._required(ar)
        if (ar["category"] in policy.data["recommendation_actions"]["binding_namespaces"].values()
                and need <= to_amount(bcaps["per_action_hard_cap"])):   # an over-per-action request is refused by lane D first
            self.store.budget_lock(cur, CURRENCY)   # re-entrant: serialises cash-at-risk with the reservation
            car = policy.data["recommendation_actions"]["cash_at_risk"]
            binding_cats = list(policy.data["recommendation_actions"]["binding_namespaces"].values())
            item_now, total_now = self.store.cash_at_risk(cur, ar["item_id"], binding_cats, CURRENCY, mode)
            if item_now + need > to_amount(car["max_per_flip_usd"]):
                return [f"CASH_AT_RISK_PER_FLIP:{ar['item_id']}"], None
            if total_now + need > to_amount(car["max_total_active_usd"]):
                return ["CASH_AT_RISK_TOTAL"], None
        # Lane D 0013 (D-11): the money ACTION-count cap is enforced inside budget_reserve_caps under the
        # per-currency lock (count of unreleased bucket reservations in the last hour, zero-amount included).
        velocity = policy.data["budgets"]["velocity"]["money_bucket_actions_per_hour"] if bucket == "money" else None
        cap_doc = {"per_action": bcaps["per_action_hard_cap"], "daily": bcaps["daily_hard_cap"],
                   "global_daily": caps["global_daily_hard_cap"], "velocity_per_hour": None,
                   "velocity_actions_per_hour": velocity,
                   "tz": policy.data["quiet_hours"]["timezone"], "categories": cats}
        prov = [self._tool_provenance(cur, policy.version)] + ar["provenance_ids"]
        try:
            with cur.connection.transaction():  # savepoint: a cap refusal must not abort the guard txn
                rid = self.store.reserve_caps(cur, ar["action_request_id"], need, CURRENCY, cap_doc, mode, GATEWAY_ACTOR,
                                              f"reserve {need} {CURRENCY} ({mode}, bucket {bucket})", prov,
                                              f"{ar['action_request_id']}:BUDGET_RESERVED")
        except psycopg.Error as exc:
            if exc.sqlstate != "MB006":
                raise
            msg = str(exc)
            code = ("BUDGET_PER_ACTION_CAP" if "per_action" in msg else "BUDGET_GLOBAL_DAILY_CAP" if "global daily" in msg
                    else "BUDGET_VELOCITY_CAP" if "velocity" in msg
                    else "BUDGET_DAILY_CAP" if "daily cap" in msg else "BUDGET_DENIED")
            return [f"{code}:{bucket}:{mode}"], None
        return [], rid

    def _release(self, cur, ar: dict, prov: list[str], why: str) -> None:
        res = self.store.open_reservation(cur, ar["action_request_id"])
        if res is not None:
            self.store.settle(cur, res["reservation_id"], "release", None, GATEWAY_ACTOR, f"release reservation: {why}",
                              prov + ar["provenance_ids"], f"{res['reservation_id']}:RELEASE")

    # ------------------------------------------------------------------ execution guard
    def _guard(self, cur, ar: dict, policy: Policy | None, policy_err: str | None) -> tuple[dict[str, list[str]], dict | None, bool]:
        """Run all 8 checks. Returns ({check: [failures]}, approval, dry_run)."""
        f: dict[str, list[str]] = {f"G{i}": [] for i in range(1, 9)}
        # G7 first: kill switch (fail closed on unreadable).
        f["G7"] += self.panic.read().blocks(ar["proposed_by"], ar["capability"], ar["category"])
        approval = self.store.latest_approval(cur, ar["action_request_id"])
        if policy is None:
            for k in f:
                f[k].append(policy_err or "POLICY_UNREADABLE")
            return f, approval, True
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
        except (ValueError, TypeError) as exc:
            recomputed = f"unhashable:{exc}"
        if recomputed != ar["payload_hash"]:
            f["G3"].append("PAYLOAD_MUTATED_AFTER_PROPOSAL")
        if approval is not None and approval["payload_hash_seen"] != ar["payload_hash"]:
            f["G3"].append("APPROVAL_PAYLOAD_HASH_MISMATCH")
        # G4 idempotency
        if self.store.claim_state(cur, ar["action_request_id"]) is not None:
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
        rules, rules_err = self._content_rules()
        if rules is None:
            f["G6"].append(rules_err)
        else:
            f["G6"] += [f"SECRET_IN_PAYLOAD:{x.rule}@{x.path}" for x in secret_findings(rules, ar["payload"])]
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
            res = self.store.open_reservation(cur, ar["action_request_id"])
            mode = "dry_run" if dry_run else "live"
            if res is not None:
                if res["mode"] != mode or Decimal(res["reserved"]) < self._required(ar):
                    f["G5"].append("RESERVATION_DOES_NOT_COVER_ACTION")
            else:
                reasons, _ = self._reserve(cur, ar, policy, approval["approval_id"] if approval else None)
                f["G5"] += reasons
        return f, approval, dry_run

    TRANSIENT_PREFIXES = ("QUIET_HOURS", "BUDGET_", "CASH_AT_RISK", "RESERVATION_", "ESTIMATE_", "POLICY_UNREADABLE",
                          "CONTENT_RULES_UNREADABLE", "LIVE_MODE_NOT_AVAILABLE", "NO_EFFECTOR", "EFFECTOR_CANNOT_DRY_RUN")

    @classmethod
    def _terminal_refusal(cls, failures: dict[str, list[str]]) -> bool:
        """True if any refusal reason is one retrying will never fix (see the F-40 backstop)."""
        for gate, reasons in failures.items():
            if gate == "G7":
                continue      # kill-switch reasons are handled by R20; G7 non-PANIC is the unreadable-policy marker
            for r in reasons:
                if not r.startswith(cls.TRANSIENT_PREFIXES):
                    return True
        return False

    def execute(self, action_request_id: str) -> Result:
        """Run the guard; on success call the effector (DRY-RUN) and receipt the outcome."""
        policy, policy_err = self._policy()
        areq = action_request_id
        # R22: the process died AFTER the (simulated) provider durably recorded the send but BEFORE the outcome
        # receipts. The provider has the proof: settle it truthfully now (executed), never re-send.
        if policy is not None:
            with self.store.tx("gateway") as cur:
                pre_ar = self.store.get_action_request(cur, areq)
                pre_claim = self.store.claim_state(cur, areq)
            if pre_ar and pre_ar["status"] == "executing" and pre_claim and pre_claim["state"] == "executed":
                return self._reconcile_one(areq, policy)
        # ---- Phase A: guard + ACTION_EXECUTING + claim, one transaction, row locked ----
        with self.store.tx("gateway") as cur:
            ar = self.store.get_action_request(cur, areq, lock=True)
            if ar is None:
                raise GatewayRefused(f"unknown action request {areq}")
            claim = self.store.claim_state(cur, areq)
            if claim is not None and claim["state"] == "executed":
                return Result("duplicate", areq, ar["status"], ["ALREADY_EXECUTED"], effector_response=claim["response"])
            if claim is not None and claim["state"] == "executing":
                return Result("refused", areq, ar["status"],
                              ["IN_FLIGHT_OR_CRASHED: reconciliation required, never blind-retry"])
            if claim is not None:
                return Result("refused", areq, ar["status"], [f"CLAIM_{claim['state'].upper()}"])
            failures, approval, dry_run = self._guard(cur, ar, policy, policy_err)
            gw = self._tool_provenance(cur, policy.version if policy else "UNAVAILABLE")
            prov = [gw] + ar["provenance_ids"]
            flat = [f"{k}:{r}" for k, rs in failures.items() for r in rs]
            if flat:
                before = ar["status"]
                new_status = before
                # Only the SPECIFIC reasons change status: an unreadable policy fails every check generically
                # (POLICY_UNREADABLE) and must leave the approval intact, not expire or fail it.
                if (any(r.startswith(("APPROVAL_EXPIRED", "ACTION_REQUEST_EXPIRED")) for r in failures["G2"])
                        and before in ("approved", "held", "pending_approval")):
                    new_status = "expired"
                elif any(r.startswith(("PAYLOAD_MUTATED", "APPROVAL_PAYLOAD_HASH")) for r in failures["G3"]) and before == "approved":
                    new_status = "failed"
                elif before == "approved" and any(r.startswith("PANIC_") for r in failures["G7"]):
                    # R20 (06 P-06-11): an approval refused by a freeze must not stay reusable after an unrelated
                    # PANIC release. The request is cancelled_by_freeze (reservation released); Michael re-approves
                    # via a new proposal.
                    new_status = "cancelled_by_freeze"
                elif before == "approved" and self._terminal_refusal(failures):
                    # F-40 backstop (E-15): an approval refused for a NON-freeze reason that retrying cannot fix
                    # (no step-up, bad approver/channel/scope/auth, payload or grant problem, ...) must not stay
                    # `approved`: it settles `failed` (approved -> failed) with ACTION_FAILED in the same transaction,
                    # so Michael's approval is never silently lost and never half-alive. Transient conditions
                    # (quiet hours, budget caps, unreadable policy/rules, G8 system state) keep the approval.
                    new_status = "failed"
                details = {"kind": "generic", "guard": "refused", "failed_checks": failures}
                if approval is not None:
                    rtype, extra = "ACTION_FAILED", {"approval_id": approval["approval_id"], "effect": "none",
                                                     "effector_response": {"provider": "none", "status": "guard_refused",
                                                                           "dry_run": True}}
                else:
                    rtype, extra = "POLICY_DECIDED", {"effect": "none"}
                    details["decision"] = DENY
                intent = "execution guard refused; effector NOT called"
                if new_status != before:
                    rid = self.store.set_status(cur, areq, new_status, rtype, GATEWAY_ACTOR, intent, prov,
                                                f"{areq}:GUARD:{new_ulid()}", {**extra, "details": details})
                    self._release(cur, ar, [gw], new_status)
                else:
                    rid = self._receipt(cur, self.store, rtype, ar, intent, prov, before_state={"status": before},
                                        after_state={"status": before}, details=details, **extra)["receipt_id"]
                return Result("refused", areq, new_status, flat, [rid])
            r_exec = self.store.set_status(cur, areq, "executing", "ACTION_EXECUTING", GATEWAY_ACTOR,
                                           f"guard passed (8/8); calling effector dry_run={dry_run}", prov,
                                           f"{ar['idempotency_key']}:EXECUTING",
                                           {"approval_id": approval["approval_id"], "effect": "none",
                                            "policy_decision_ref": ar.get("policy_decision_ref"),
                                            "details": {"kind": "generic", "guard": "passed", "dry_run": dry_run}})
            self.store.effector_claim(cur, areq, {"capability": ar["capability"], "payload_hash": ar["payload_hash"],
                                                  "dry_run": dry_run})
        approval_id = approval["approval_id"]

        # ---- Phase B: last-instant kill-switch read, then the effector ------------
        late = self.panic.read().blocks(ar["proposed_by"], ar["capability"], ar["category"])
        response, error = None, None
        if late:
            error = "FROZE_BEFORE_EFFECTOR:" + ",".join(late)
        else:
            effector = self._effectors[policy.capability(ar["capability"])["effector"]]
            token = self._minter.mint(areq, ar["payload_hash"], ar["idempotency_key"], dry_run)
            try:
                response = effector.execute(token, ar)
            except Exception as exc:  # noqa: BLE001 - any effector failure is receipted
                error = f"EFFECTOR_ERROR:{type(exc).__name__}:{exc}"
            if response is not None and dry_run and response.get("dry_run") is not True:
                error = "DRY_RUN_INVARIANT_VIOLATED: effector did not confirm dry_run"
                self.engage_panic("L3", None, actor="action-gateway", reason=error)

        # ---- Phase C: outcome receipts + claim finish + budget settle, one transaction ----
        with self.store.tx("gateway") as cur:
            if error:
                status = "cancelled_by_freeze" if error.startswith("FROZE_BEFORE") else "failed"
                # Lane D CHECKs dry_run=true on every stored response (A7). What the effector actually
                # reported is kept verbatim under `effector_reported` so a violation stays visible.
                reported = {"effector_reported": response} if response is not None else {}
                resp = {"provider": (response or {}).get("provider", "none"), "status": "not_called" if response is None
                        else "invariant_violation" if "INVARIANT" in error else "error", "dry_run": True, "error": error}
                self.store.effector_finish(cur, areq, "failed", resp["provider"], None, {**resp, **reported})
                self._release(cur, ar, [gw], status)
                rid = self.store.set_status(cur, areq, status, "ACTION_FAILED", GATEWAY_ACTOR, error[:300], prov,
                                            f"{ar['idempotency_key']}:FAILED",
                                            {"approval_id": approval_id, "effect": "none", "effector_response": resp,
                                             "details": {"kind": "generic", "error": error, **reported}})
                return Result("failed", areq, status, [error], [r_exec, rid], response)
            self.store.effector_finish(cur, areq, "executed", response.get("provider"), response.get("provider_msg_id"),
                                       response)
            rids = [r_exec]
            res = self.store.open_reservation(cur, areq)
            if res is not None:
                rids.append(self.store.settle(cur, res["reservation_id"], "commit", None, GATEWAY_ACTOR,
                                              "commit (dry_run; no real money moved)" if dry_run else "commit",
                                              prov, f"{res['reservation_id']}:COMMIT"))
            rids.append(self.store.set_status(
                cur, areq, "executed", "ACTION_EXECUTED", GATEWAY_ACTOR,
                f"{ar['capability']} executed (DRY-RUN)" if dry_run else f"{ar['capability']} executed",
                prov, f"{ar['idempotency_key']}:EXECUTED",
                {"approval_id": approval_id, "effect": EFFECT_BY_CATEGORY[ar["category"]],
                 "tool_name": f"effector:{response['provider']}", "effector_response": response,
                 "details": {"kind": "generic", "dry_run": dry_run}}))
            return Result("executed", areq, "executed", [], rids, response)

    # ------------------------------------------------------------------ E-05 reconciliation
    def reconcile(self, older_than_seconds: int | None = None) -> list[Result]:
        """Reconcile execution claims stuck in `executing` (crash between the effector call and its
        receipt). Provider-query-before-retry: ask the effector, by idempotency key, whether the call
        landed — NEVER re-send.
          found      -> finish `executed` with the provider's record, commit budget, ACTION_EXECUTED
          not found  -> finish `failed`, release budget, ACTION_FAILED (no auto-retry: a new proposal + YES)
          no answer  -> leave the claim untouched, report NEEDS_HUMAN
        Exactly once: the request row is locked and the claim re-checked inside the transaction.
        Allowed under PANIC: reconciliation records what already happened; it never acts."""
        policy, err = self._policy()
        if policy is None:
            return [Result("refused", None, None, [err or "POLICY_UNREADABLE"])]
        ttl = policy.data["execution"]["claim_ttl_seconds"] if older_than_seconds is None else older_than_seconds
        with self.store.tx("gateway") as cur:
            candidates = self.store.stuck_claims(cur, ttl)
        return [self._reconcile_one(areq, policy) for areq in candidates]

    def _reconcile_one(self, areq: str, policy: Policy) -> Result:
        """Settle ONE request left `executing` (crash). R22 / A5 = never duplicate the effect, settle truthfully:
          provider has a durable record  -> executed (+ budget commit); the Item then reaches ACTED
          provider has none, or cannot prove one -> failed (+ release); NEVER re-sent; Michael re-approves."""
        with self.store.tx("gateway") as cur:
            ar = self.store.get_action_request(cur, areq, lock=True)
            claim = self.store.claim_state(cur, areq)
            if claim is None or ar["status"] != "executing":
                return Result("duplicate", areq, ar["status"] if ar else None, ["ALREADY_RECONCILED"])
            approval = self.store.latest_approval(cur, areq)
            cap = policy.capability(ar["capability"])
            effector = self._effectors.get(cap["effector"]) if cap else None
            if effector is None:
                return Result("refused", areq, ar["status"], ["NEEDS_HUMAN:NO_EFFECTOR_FOR_LOOKUP"])
            token = self._minter.mint(areq, ar["payload_hash"], ar["idempotency_key"], self._dry_run_forced(policy))
            try:
                record, lookup_error = effector.lookup(token, ar), None   # read-only provider query
            except Exception as exc:  # noqa: BLE001 - a provider that cannot answer cannot prove a send
                record, lookup_error = None, f"{type(exc).__name__}: {exc}"
            gw = self._tool_provenance(cur, policy.version, tool="mbos_governance.reconcile")
            prov = [gw] + ar["provenance_ids"]
            approval_id = approval["approval_id"] if approval else None
            if record is not None and record.get("dry_run") is True:
                if claim["state"] == "executing":     # (durable providers already finished the claim at send time)
                    self.store.effector_finish(cur, areq, "executed", record.get("provider"), record.get("provider_msg_id"), record)
                res = self.store.open_reservation(cur, areq)
                if res is not None:
                    self.store.settle(cur, res["reservation_id"], "commit", None, GATEWAY_ACTOR,
                                      "commit (reconciled; dry_run)", prov, f"{res['reservation_id']}:COMMIT")
                rid = self.store.set_status(
                    cur, areq, "executed", "ACTION_EXECUTED", GATEWAY_ACTOR,
                    f"{ar['capability']} RECONCILED: provider has the durable record of the send (DRY-RUN); not re-sent", prov,
                    f"{ar['idempotency_key']}:EXECUTED",
                    {"approval_id": approval_id, "effect": EFFECT_BY_CATEGORY[ar["category"]],
                     "tool_name": f"effector:{record.get('provider')}", "effector_response": record,
                     "details": {"kind": "generic", "reconciled": True, "provider_found": True}})
                return Result("executed", areq, "executed", ["RECONCILED:PROVIDER_FOUND"], [rid], record)
            if record is not None:
                reason, status = "RECONCILED:PROVIDER_RECORD_NOT_DRY_RUN", "invariant_violation"
            elif lookup_error is not None:
                reason, status = "RECONCILED:PROVIDER_UNPROVEN", "unproven"
            else:
                reason, status = "RECONCILED:PROVIDER_NOT_FOUND", "not_delivered"
            resp = {"provider": (record or {}).get("provider", cap["effector"]), "status": status, "dry_run": True, "error": reason}
            reported = {"effector_reported": record} if record is not None else {}
            self.store.effector_finish(cur, areq, "failed", resp["provider"], None, {**resp, **reported})
            self._release(cur, ar, [gw], f"reconciled: {status}")
            note = ("provider could not prove a send; settled failed, NOT retried. If this were a live provider, verify with it "
                    "before Michael re-approves" if status == "unproven" else
                    "provider has no record of the send; settled failed, NOT retried; Michael re-approves")
            rid = self.store.set_status(cur, areq, "failed", "ACTION_FAILED", GATEWAY_ACTOR,
                                        f"{ar['capability']} RECONCILED: {note} ({reason})"[:500], prov,
                                        f"{ar['idempotency_key']}:FAILED",
                                        {"approval_id": approval_id, "effect": "none", "effector_response": resp,
                                         "details": {"kind": "generic", "reconciled": True, "provider_found": record is not None,
                                                     "proof": status, **({"lookup_error": lookup_error} if lookup_error else {}),
                                                     **reported}})
        if record is not None:  # a provider claiming a live effect is the dry-run invariant breaking
            self.engage_panic("L3", None, actor="action-gateway", reason=f"reconcile {areq}: {reason}")
        return Result("failed", areq, "failed", [reason], [rid])

    # ------------------------------------------------------------------ PANIC (lane D mbos.panic_set)
    def _state_summary(self) -> dict:
        st = self.panic.read()
        return {"revision": st.revision, "global": {"state": st.global_state}, "readable": st.readable,
                "agents": sorted(st.frozen_agents), "capabilities": sorted(st.frozen_capabilities)}

    def _hooks_receipt(self, level: str, target: str | None, engage: bool, actor: str, reason: str, results: dict,
                       config_version: str) -> None:
        with self.store.tx("gateway") as cur:
            prov = self._tool_provenance(cur, config_version, tool="mbos_governance.hooks")
            self.store.append_receipt(cur, {
                "type": "KILL_SWITCH_CHANGED", "actor": actor_json(actor), "effect": "update",
                "intent": f"PANIC side effects applied: {level} {'ENGAGE' if engage else 'RELEASE'} {target or 'global'}: {reason}"[:500],
                "entity_type": "panic_hooks", "entity_id": f"{level}:{target or 'global'}",
                "provenance_ids": [prov], "idempotency_key": f"panic-hooks:{new_ulid()}",
                "details": {"kind": "generic", "level": level, "engage": engage, "hooks": results}})

    def engage_panic(self, level: str, target: str | None, actor: str, reason: str) -> dict:
        """Freeze (role gateway). Anyone may engage: the gateway, an approver, or a discovery freeze
        request applied on an agent's behalf. State + KILL_SWITCH_CHANGED commit atomically in
        mbos.panic_set, which also cancels approved-but-unstarted requests on L3. If the database is
        unreachable the freeze cannot be written — but then PANIC also cannot be READ, which is FROZEN
        for every reader (fail closed); the attempt is journaled locally."""
        policy, _ = self._policy()
        cv = policy.version if policy else "UNAVAILABLE"
        cancelled: list[str] = []
        try:
            with self.store.tx("gateway") as cur:
                if level == "L3":
                    cancelled = [r["action_request_id"] for r in cur.execute(
                        "SELECT action_request_id FROM mbos.action_requests WHERE status IN ('approved','auto_approved')")]
                prov = self._tool_provenance(cur, cv, tool="mbos_governance.panic")
                self.store.panic_set(cur, level, target, True, actor_json(actor), reason, [prov], f"panic:engage:{new_ulid()}")
                for areq in cancelled:
                    ar = self.store.get_action_request(cur, areq)
                    self._release(cur, ar, [prov], "cancelled_by_freeze")
        except Exception as exc:  # noqa: BLE001
            with open(self._journal, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"ts": fmt_ts(self.clock()), "event": "KILL_SWITCH_ENGAGE_FAILED", "level": level,
                                     "target": target, "actor": actor, "reason": reason,
                                     "error": f"{type(exc).__name__}: {exc}"}) + "\n")
            print(f"WARNING: freeze could not be written ({exc}); PANIC reads fail closed; journaled to {self._journal}",
                  file=sys.stderr)
            return {"state": self._state_summary(), "cancelled": [], "hooks": {}, "error": str(exc)}
        # Side effects (cancel unstarted workflows, deny-all egress, zero LLM budgets) after the freeze is durable.
        hook_results = run_hooks(self.panic_hooks, level, target, True, self.panic.read())
        if self.panic_hooks:
            self._hooks_receipt(level, target, True, actor, reason, hook_results, cv)
        return {"state": self._state_summary(), "cancelled": cancelled, "hooks": hook_results}

    def release_panic(self, level: str, target: str | None, actor: str, reason: str) -> dict:
        """Unfreeze (role approver). Only a policy approver may release, the policy must be readable,
        and the release is atomic with its receipt in mbos.panic_set."""
        policy, err = self._policy()
        if policy is None:
            raise GatewayRefused(f"cannot release PANIC while policy is unreadable: {err}")
        if actor not in policy.data["approval"]["approvers"]:
            raise GatewayRefused(f"{actor} may not release PANIC")
        if not reason.strip():
            raise GatewayRefused("release requires a reason")
        with self.store.tx("approver") as cur:
            prov = self._tool_provenance(cur, policy.version, tool="mbos_governance.panic")
            self.store.panic_set(cur, level, target, False, actor_json(actor), reason, [prov], f"panic:release:{new_ulid()}")
        # Loosening side effects only after the release itself is committed with its receipt.
        hook_results = run_hooks(self.panic_hooks, level, target, False, self.panic.read())
        if self.panic_hooks:
            self._hooks_receipt(level, target, False, actor, reason, hook_results, policy.version)
        return {"state": self._state_summary(), "hooks": hook_results}
