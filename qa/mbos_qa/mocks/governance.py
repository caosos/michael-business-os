"""MOCK — lane E (Governance, Agent 05). Conforms to ADR-0005 and frozen contracts v1.0.0.

Kill switch (3-level PANIC, fail-closed), thin PDP policy table (everything tier 0 / require approval,
per MICHAEL_DECISIONS #5), real-world budget ledger (reserve → commit/release, default hard cap $0),
LLM spend cap (stand-in for LiteLLM virtual keys), and the Action Gateway with the 8-check
execution guard. REPLACE WITH: Agent 05's gateway/PDP/ledger behind the same interfaces.
Known mock limitations: L3 cannot cut real egress or revoke OpenBao leases (none exist yet);
the LLM cap is enforced in-process, not by a LiteLLM proxy.
"""
from __future__ import annotations

import json
import os
import pathlib
import threading
from dataclasses import dataclass

from ..core import Clock, parse_iso, sha256_ref
from .store import ReferenceStore

IMPLEMENTATION = "MOCK governance (kill switch / PDP / ledgers / gateway) — stands in for Agent 05"

SYSTEM_ACTOR = {"type": "system", "id": "gateway"}
DRY_RUN_MODES = {"round_one", "mvp"}


class GuardDenied(Exception):
    def __init__(self, check: str, reason: str):
        super().__init__(f"guard check '{check}' denied: {reason}")
        self.check, self.reason = check, reason


# --------------------------------------------------------------------------- PANIC
class KillSwitch:
    """File-backed PANIC state. ANY read failure is treated as FROZEN (fail closed, A9)."""

    CLEAR = {"global": "CLEAR", "agents_frozen": [], "capabilities_frozen": [], "version": 1}

    def __init__(self, path: str | pathlib.Path):
        self.path = pathlib.Path(path)

    def initialise(self) -> None:
        if not self.path.exists():
            self._write(dict(self.CLEAR))

    def _write(self, state: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state))
        os.replace(tmp, self.path)

    def read(self) -> dict:
        state = json.loads(self.path.read_text())
        if state.get("global") not in ("CLEAR", "FROZEN") or not isinstance(state.get("agents_frozen"), list) \
                or not isinstance(state.get("capabilities_frozen"), list):
            raise ValueError("kill switch state malformed")
        return state

    def blocked(self, agent: str, capability: str) -> str | None:
        """Return a reason string if blocked, None if clear."""
        try:
            s = self.read()
        except Exception as e:  # noqa: BLE001 — fail closed on anything
            return f"kill switch unreadable ({type(e).__name__}) — fail closed"
        if s["global"] != "CLEAR":
            return "L3 global freeze"
        if agent in s["agents_frozen"]:
            return f"L1 agent freeze: {agent}"
        for cap in s["capabilities_frozen"]:
            if capability == cap or capability.startswith(cap + "."):
                return f"L2 capability freeze: {cap}"
        return None

    def set(self, *, level: str, target: str | None, frozen: bool) -> dict:
        try:
            s = self.read()
        except Exception:  # noqa: BLE001
            s = dict(self.CLEAR, **{"global": "FROZEN"})
        if level == "L3":
            s["global"] = "FROZEN" if frozen else "CLEAR"
        else:
            key = "agents_frozen" if level == "L1" else "capabilities_frozen"
            vals = set(s[key])
            (vals.add if frozen else vals.discard)(target)
            s[key] = sorted(vals)
        s["version"] = s.get("version", 0) + 1
        self._write(s)
        return s


# --------------------------------------------------------------------------- PDP
DEFAULT_POLICY = {
    # MICHAEL_DECISIONS #5 default: no delegation in the MVP → every category is tier 0, approval required.
    "version": "qa-mock-2026.10.0",
    "categories": {c: {"decision": "require_approval", "tier": 0} for c in (
        "message", "offer", "money", "purchase", "publishing", "scheduling", "price_change",
        "phone_call", "sms", "email", "external_commitment")},
}


class PDP:
    def __init__(self, policy: dict = DEFAULT_POLICY):
        self.policy = policy

    def decide(self, areq: dict) -> dict:
        rule = self.policy["categories"].get(areq["category"])
        if rule is None:
            return {"decision": "deny", "tier": 0, "policy_decision_ref": f"{self.policy['version']}:no-rule"}
        return {"decision": rule["decision"], "tier": rule["tier"],
                "policy_decision_ref": f"{self.policy['version']}:{areq['category']}"}


# --------------------------------------------------------------------------- spend ledgers
class BudgetExceeded(Exception):
    pass


class BudgetLedger:
    """Real-world spend. Reserve on approval/execution, then commit or release. Atomic; fail closed."""

    def __init__(self, hard_cap_usd: float = 0.0):
        self.hard_cap = hard_cap_usd
        self._lock = threading.Lock()
        self.reserved: dict[str, float] = {}
        self.committed: dict[str, float] = {}

    def reserve(self, key: str, amount: float) -> None:
        if amount < 0:
            raise BudgetExceeded("negative reservation refused")
        with self._lock:
            if key in self.reserved or key in self.committed:
                return
            total = sum(self.reserved.values()) + sum(self.committed.values()) + amount
            if total > self.hard_cap + 1e-9:
                raise BudgetExceeded(f"hard cap ${self.hard_cap:.2f} would be exceeded (${total:.2f})")
            self.reserved[key] = amount

    def commit(self, key: str, amount: float = 0.0) -> None:
        """Commit a reservation. If it was lost (mock ledger is in-memory; a crash drops it) it is re-reserved
        under the cap first, so recovery still fails closed. Real ledger must persist reservations (finding F-7)."""
        if key not in self.reserved and key not in self.committed:
            self.reserve(key, amount)
        with self._lock:
            if key in self.reserved:
                self.committed[key] = self.reserved.pop(key)

    def release(self, key: str) -> None:
        with self._lock:
            self.reserved.pop(key, None)

    def outstanding(self) -> float:
        with self._lock:
            return sum(self.reserved.values()) + sum(self.committed.values())


class LLMBudgetExceeded(Exception):
    pass


class LLMBudget:
    """Stand-in for LiteLLM per-agent virtual keys with a hard daily cap (A8).

    The agent never reports its own cost: the gateway pre-reserves the worst case from
    `max_tokens` and then charges from the token counts the provider returned.
    """

    def __init__(self, caps_usd: dict[str, float], price_per_1k_tokens: float = 0.01):
        self.caps = dict(caps_usd)
        self.price = price_per_1k_tokens
        self.spent: dict[str, float] = {}
        self.inflight: dict[str, float] = {}
        self._lock = threading.Lock()
        self.calls_made = 0
        self.calls_blocked = 0

    def _cost(self, tokens: int) -> float:
        return max(0, tokens) / 1000 * self.price

    def call(self, agent: str, *, prompt_tokens: int, max_tokens: int, provider_fn) -> dict:
        worst = self._cost(prompt_tokens + max_tokens)
        with self._lock:
            cap = self.caps.get(agent)
            used = self.spent.get(agent, 0.0) + self.inflight.get(agent, 0.0)
            if cap is None or self.spent.get(agent, 0.0) >= cap or used + worst > cap + 1e-12:
                self.calls_blocked += 1
                raise LLMBudgetExceeded(f"{agent}: cap {cap} reached (used {used:.4f}, next worst {worst:.4f})")
            self.inflight[agent] = self.inflight.get(agent, 0.0) + worst
        try:
            resp = provider_fn(max_tokens)
        finally:
            with self._lock:
                self.inflight[agent] -= worst
        # charge from provider-reported token counts, never from anything the agent claims;
        # a malformed or negative count is charged at the reserved worst case
        try:
            completion = int(resp.get("completion_tokens"))
            charge = self._cost(prompt_tokens + completion) if completion >= 0 else worst
        except (TypeError, ValueError):
            charge = worst
        with self._lock:
            self.spent[agent] = self.spent.get(agent, 0.0) + max(charge, 0.0)
            self.calls_made += 1
        return resp


# --------------------------------------------------------------------------- gateway
@dataclass
class ExecResult:
    status: str  # executed | already_executed | reconciled
    receipt: dict
    effector_calls: int


class Gateway:
    """The only path to effectors. 8-check execution guard (ADR-0005 §2)."""

    def __init__(self, store: ReferenceStore, kill: KillSwitch, pdp: PDP, budget: BudgetLedger,
                 effectors: dict, clock: Clock, mode: str = "mvp", prov_id: str | None = None):
        self.store, self.kill, self.pdp, self.budget = store, kill, pdp, budget
        self.effectors, self.clock, self.mode = effectors, clock, mode
        self.prov_id = prov_id  # tool provenance for gateway-authored receipts
        self.faults: dict[str, callable] = {}

    def _fault(self, name: str) -> None:
        if name in self.faults:
            self.faults[name]()

    def effector_for(self, capability: str):
        for prefix, eff in self.effectors.items():
            if capability == prefix or capability.startswith(prefix + "."):
                return eff
        return None

    def _deny(self, areq: dict, approval_id: str | None, check: str, reason: str):
        with self.store.tx() as t:
            t.receipt(type="POLICY_DECIDED", actor=SYSTEM_ACTOR, intent=f"execution guard denied ({check})",
                      provenance_ids=[self.prov_id], idempotency_key=f"guard-deny:{self.store.ids.new('rcpt')[5:]}",
                      item_id=areq["item_id"], action_request_id=areq["action_request_id"],
                      capability=areq["capability"], payload_hash=areq["payload_hash"], effect="none",
                      policy_decision_ref=f"guard:{check}",
                      after_state={"guard": "deny", "check": check, "reason": reason},
                      **({"approval_id": approval_id} if approval_id else {}))
        raise GuardDenied(check, reason)

    def guard(self, areq: dict, approval: dict | None) -> None:
        now = self.clock.now()
        aid = approval["approval_id"] if approval else None
        # 1 approval valid
        latest = self.store.approvals_for(areq["action_request_id"])
        if approval is None or not latest or latest[-1]["approval_id"] != approval["approval_id"]:
            self._deny(areq, aid, "1-approval-valid", "no approval, or not the latest decision on this request")
        if approval["decision"] != "YES":
            self._deny(areq, aid, "1-approval-valid", f"latest decision is {approval['decision']}, not YES")
        if approval["payload_hash_seen"] != areq["payload_hash"]:
            self._deny(areq, aid, "1-approval-valid", "approval was for a different payload")
        if areq["status"] != "approved":
            self._deny(areq, aid, "1-approval-valid", f"request status is {areq['status']}")
        # 2 not expired
        if now >= parse_iso(areq["expires_at"]) or (approval.get("expires_at") and now >= parse_iso(approval["expires_at"])):
            self._deny(areq, aid, "2-not-expired", "approval or request expired")
        # 3 payload hash still matches
        if sha256_ref(areq["payload"]) != areq["payload_hash"]:
            self._deny(areq, aid, "3-payload-hash", "payload changed after it was frozen")
        # 4 idempotency handled by caller; 5 budget is reserved last (below) so a later denial never leaks a reservation
        # 6 grant constraints
        if approval["scope"] == "standing_rule":
            self._deny(areq, aid, "6-grant", "standing rules disabled (MICHAEL_DECISIONS #5: no delegation)")
        needs_step_up = areq["reversibility"] == "irreversible" or areq["category"] in ("money", "purchase", "external_commitment")
        if needs_step_up and not (approval.get("auth_context") or {}).get("step_up"):
            self._deny(areq, aid, "6-grant", "money/irreversible approval without step-up")
        if approval["decider"] != "michael":
            self._deny(areq, aid, "6-grant", "decider is not michael")
        # 7 kill switch
        reason = self.kill.blocked(areq["proposed_by"], areq["capability"])
        if reason:
            self._deny(areq, aid, "7-kill-switch", reason)
        # 8 dry-run forced
        eff = self.effector_for(areq["capability"])
        if eff is None:
            self._deny(areq, aid, "8-dry-run", f"no effector registered for {areq['capability']}")
        if self.mode in DRY_RUN_MODES and not getattr(eff, "dry_run", False):
            self._deny(areq, aid, "8-dry-run", f"SYSTEM_MODE={self.mode} requires a dry-run effector")
        # 5 budget reserved (last, after every other check passed)
        try:
            self.budget.reserve(areq["action_request_id"], float((areq.get("max_cost") or areq.get("estimated_cost") or {"amount": 0})["amount"]))
        except Exception as e:  # noqa: BLE001 — fail closed
            self._deny(areq, aid, "5-budget", str(e))

    def execute(self, action_request_id: str, approval_id: str) -> ExecResult:
        areq = self.store.get("action-request", action_request_id)
        approval = self.store.get("approval", approval_id)
        done = self.store.receipt_by_key(f"{areq['idempotency_key']}:executed")
        if done:  # check 4: idempotency key already used → no-op
            return ExecResult("already_executed", done, 0)
        if areq["status"] == "executing":  # someone else holds the claim; only recover() may finish it
            return ExecResult("in_flight", self.store.receipt_by_key(f"{areq['idempotency_key']}:executing"), 0)
        self.guard(areq, approval)
        common = self._common(areq, approval_id)
        with self.store.tx() as t:
            # compare-and-set claim: exactly one caller moves approved → executing
            cur = self.store._load(t.cur, "action_requests", "action_request_id", action_request_id)
            if cur["status"] != "approved":
                claimed = False
            else:
                claimed = True
                cur["status"] = "executing"
                t.replace_action_request(cur)
                t.receipt(type="ACTION_EXECUTING", actor=SYSTEM_ACTOR, intent=f"execute {areq['capability']} (dry-run)",
                          provenance_ids=[self.prov_id] + areq["provenance_ids"],
                          idempotency_key=f"{areq['idempotency_key']}:executing", effect="none",
                          before_state={"status": "approved"}, after_state={"status": "executing"}, **common)
                item = self.store._load(t.cur, "items", "item_id", areq["item_id"])
                if item["state"] == "APPROVED":
                    t.transition_item(areq["item_id"], "ACTING", actor=SYSTEM_ACTOR, intent="action execution started",
                                      provenance_ids=[self.prov_id])
        if not claimed:
            return ExecResult("in_flight", None, 0)
        self._fault("after_executing_before_effector")
        return self._complete(areq, approval)

    def recover(self) -> list[ExecResult]:
        """Run once at process start (DBOS resumes the step). Finishes requests left `executing` by a crash:
        asks the provider whether the idempotency key already went out before any retry (05 §13)."""
        out = []
        for areq in self.store.action_requests(status="executing"):
            approval = [a for a in self.store.approvals_for(areq["action_request_id"]) if a["decision"] == "YES"][-1]
            eff = self.effector_for(areq["capability"])
            if eff.lookup(areq["idempotency_key"]) is None and self.kill.blocked(areq["proposed_by"], areq["capability"]):
                out.append(ExecResult("left_in_flight_by_freeze", None, 0))  # in-flight at freeze: not retried
                continue
            out.append(self._complete(areq, approval))
        return out

    def _common(self, areq: dict, approval_id: str) -> dict:
        return dict(item_id=areq["item_id"], action_request_id=areq["action_request_id"], capability=areq["capability"],
                    payload_hash=areq["payload_hash"], approval_id=approval_id)

    def _complete(self, areq: dict, approval: dict) -> ExecResult:
        eff = self.effector_for(areq["capability"])
        common = self._common(areq, approval["approval_id"])
        calls_before = eff.call_count()
        prior = eff.lookup(areq["idempotency_key"])  # 05: query the provider before any retry
        response = prior or eff.execute(areq, approval, areq["idempotency_key"])
        self._fault("after_effector_before_executed")
        live = self.mode in DRY_RUN_MODES and response.get("dry_run") is not True
        with self.store.tx() as t:
            cur = self.store._load(t.cur, "action_requests", "action_request_id", areq["action_request_id"])
            cur["status"] = "failed" if live else "executed"
            t.replace_action_request(cur)
            if live:
                self.budget.release(areq["action_request_id"])
            else:
                self.budget.commit(areq["action_request_id"],
                                   float((areq.get("max_cost") or areq.get("estimated_cost") or {"amount": 0})["amount"]))
            r = t.receipt(type="ACTION_FAILED" if live else "ACTION_EXECUTED", actor=SYSTEM_ACTOR,
                          intent=("VIOLATION: effector returned a non-dry-run response in " + self.mode) if live else
                                 f"{areq['capability']} executed in DRY-RUN — nothing left the system",
                          provenance_ids=[self.prov_id] + areq["provenance_ids"],
                          idempotency_key=f"{areq['idempotency_key']}:executed", effect=eff.effect, tool_name=eff.tool_name,
                          effector_response={k: response.get(k) for k in ("provider", "provider_msg_id", "status", "dry_run")},
                          artifact_hashes=response.get("artifact_hashes", []),
                          before_state={"status": "executing"}, after_state={"status": cur["status"]},
                          details=response.get("details", {"kind": "generic"}), **common)
            pending = [a for a in self.store.action_requests(item_id=areq["item_id"])
                       if a["status"] in ("approved", "executing") and a["action_request_id"] != areq["action_request_id"]]
            item = self.store._load(t.cur, "items", "item_id", areq["item_id"])
            if item["state"] == "ACTING" and not pending:
                t.transition_item(areq["item_id"], "FAILED" if live else "ACTED", actor=SYSTEM_ACTOR,
                                  intent="all approved actions executed (dry-run)" if not live else "dry-run violation",
                                  provenance_ids=[self.prov_id])
        if live:
            raise GuardDenied("8-dry-run", "effector returned a non-dry-run response")
        return ExecResult("reconciled" if prior else "executed", r, eff.call_count() - calls_before)

    # L3 PANIC side-effects on the queue
    def panic_l3(self, actor: dict, reason: str) -> int:
        self.kill.set(level="L3", target=None, frozen=True)
        cancelled = 0
        with self.store.tx() as t:
            t.receipt(type="KILL_SWITCH_CHANGED", actor=actor, intent=f"L3 PANIC: {reason}",
                      provenance_ids=[self.prov_id], idempotency_key=f"panic:{self.store.ids.new('rcpt')[5:]}",
                      effect="update", after_state={"global": "FROZEN"})
            for areq in self.store.action_requests():
                if areq["status"] in ("pending_approval", "approved", "held", "classified", "drafted"):
                    before = areq["status"]
                    areq["status"] = "cancelled_by_freeze"
                    t.replace_action_request(areq)
                    t.receipt(type="POLICY_DECIDED", actor=actor,
                              intent="unstarted action cancelled by L3 freeze", provenance_ids=[self.prov_id],
                              idempotency_key=f"{areq['idempotency_key']}:cancelled_by_freeze",
                              item_id=areq["item_id"], action_request_id=areq["action_request_id"],
                              capability=areq["capability"], payload_hash=areq["payload_hash"], effect="none",
                              policy_decision_ref="panic:L3", before_state={"status": before},
                              after_state={"status": "cancelled_by_freeze"})
                    cancelled += 1
        return cancelled
