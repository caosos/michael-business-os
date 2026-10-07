"""Policy Decision Point (PDP): non-LLM code that AUTHORIZES; models only PROPOSE.

Interface (ADR-0005 §3):  decide(action_request) -> {allow|deny|require_approval, tier, policy_decision_ref}

Policy is DATA (policy/policy.v1.json), validated by policy/policy.schema.json plus the
cross-reference checks below. The file is re-read whenever it changes on disk. Any read,
parse, schema or cross-reference failure raises PolicyUnavailable, and callers must deny.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator

from .ids import canonical_json, new_id, sha256_tagged

ALLOW, DENY, REQUIRE_APPROVAL = "allow", "deny", "require_approval"


class PolicyUnavailable(RuntimeError):
    """Policy could not be read or is invalid. Callers MUST fail closed."""


@dataclass(frozen=True)
class Policy:
    data: dict
    version: str  # "<declared version>+<sha256 of canonical content>"
    source: str

    def category(self, name: str) -> dict | None:
        return self.data["categories"].get(name)

    def capability(self, name: str) -> dict | None:
        return self.data["capabilities"].get(name)

    def grants(self, agent_id: str) -> list[str]:
        return self.data["agent_grants"].get(agent_id, [])

    def bucket_for(self, category: str) -> str:
        return self.data["categories"][category]["budget_bucket"]


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    tier: int
    policy_decision_ref: str
    policy_version: str
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "tier": self.tier,
            "policy_decision_ref": self.policy_decision_ref,
            "policy_version": self.policy_version,
            "reasons": list(self.reasons),
        }


def _cross_check(data: dict) -> list[str]:
    problems = []
    cats = data["categories"]
    for cap, spec in data["capabilities"].items():
        if spec["category"] not in cats:
            problems.append(f"capability {cap} -> unknown category {spec['category']}")
    for agent, caps in data["agent_grants"].items():
        for cap in caps:
            if cap not in data["capabilities"]:
                problems.append(f"agent {agent} granted unknown capability {cap}")
    for mode in ("live", "dry_run"):
        buckets = data["budgets"][mode]["buckets"]
        for cat, spec in cats.items():
            if spec["budget_bucket"] not in buckets:
                problems.append(f"category {cat} bucket {spec['budget_bucket']} missing from budgets.{mode}")
    for agent in list(data["llm_spend"]["per_agent_daily_usd"]) + list(data["egress"]["allow"]):
        if agent not in data["agent_grants"]:
            problems.append(f"llm_spend/egress names unknown agent {agent}")
    for cat in data["approval"]["step_up_required"]["categories"]:
        if cat not in cats:
            problems.append(f"step_up category {cat} unknown")
    try:
        ZoneInfo(data["quiet_hours"]["timezone"])
    except Exception as exc:  # noqa: BLE001 - any tz failure is a policy failure
        problems.append(f"quiet_hours.timezone unusable: {exc}")
    return problems


def load_policy(path: str | os.PathLike, schema_path: str | os.PathLike | None = None) -> Policy:
    path = Path(path)
    schema_path = Path(schema_path) if schema_path else path.with_name("policy.schema.json")
    try:
        data = json.loads(path.read_text("utf-8"))
        schema = json.loads(schema_path.read_text("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PolicyUnavailable(f"cannot read policy: {exc}") from exc
    errs = [f"{'/'.join(map(str, e.absolute_path)) or '$'}: {e.message[:160]}"
            for e in Draft202012Validator(schema).iter_errors(data)]
    if errs:
        raise PolicyUnavailable("policy fails schema: " + "; ".join(errs[:10]))
    problems = _cross_check(data)
    if problems:
        raise PolicyUnavailable("policy cross-check failed: " + "; ".join(problems))
    digest = sha256_tagged(canonical_json(data)).split(":", 1)[1][:16]
    return Policy(data=data, version=f"{data['version']}+{digest}", source=str(path))


class PolicyStore:
    """Re-reads the policy file when its mtime/size changes. Never serves a stale policy
    after a failed reload: a broken file makes `current()` raise until it is fixed."""

    def __init__(self, path: str | os.PathLike, schema_path: str | os.PathLike | None = None):
        self.path = Path(path)
        self.schema_path = schema_path
        self._lock = threading.Lock()
        self._stamp: tuple | None = None
        self._policy: Policy | None = None

    def current(self) -> Policy:
        with self._lock:
            try:
                st = self.path.stat()
            except OSError as exc:
                self._policy = None
                raise PolicyUnavailable(f"policy file unreadable: {exc}") from exc
            stamp = (st.st_mtime_ns, st.st_size, st.st_ino)
            if self._policy is None or stamp != self._stamp:
                self._policy = None
                self._policy = load_policy(self.path, self.schema_path)
                self._stamp = stamp
            return self._policy


def decide(action_request: dict, policy: Policy) -> PolicyDecision:
    """Pure, deterministic policy classification of a (schema-valid) ActionRequest."""
    ref = new_id("pdp")
    reasons: list[str] = []

    def deny(reason: str) -> PolicyDecision:
        return PolicyDecision(DENY, 0, ref, policy.version, reasons + [reason])

    cap_name = action_request["capability"]
    cap = policy.capability(cap_name)
    if cap is None:
        return deny(f"UNKNOWN_CAPABILITY:{cap_name}")
    category = action_request["category"]
    if cap["category"] != category:
        return deny(f"CATEGORY_MISMATCH:{cap_name} is {cap['category']}, request says {category}")
    if cap_name not in policy.grants(action_request["proposed_by"]):
        return deny(f"CAPABILITY_NOT_HELD:{action_request['proposed_by']} lacks {cap_name}")
    cat = policy.category(category)
    if cat is None:
        return deny(f"UNKNOWN_CATEGORY:{category}")
    if cat["decision"] == DENY:
        return deny(f"CATEGORY_DENIED:{category}")
    currency = policy.data["budgets"]["currency"]
    for field_name in ("estimated_cost", "max_cost"):
        money = action_request.get(field_name)
        if money is not None:
            if money["currency"] != currency:
                return deny(f"CURRENCY_NOT_ALLOWED:{field_name}={money['currency']}")
            if money["amount"] < 0:
                return deny(f"NEGATIVE_COST:{field_name}")
    if cat["require_cost_estimate"] and "estimated_cost" not in action_request and "max_cost" not in action_request:
        return deny(f"COST_ESTIMATE_REQUIRED:{category}")

    # Effective tier is the MOST restrictive of: requested, category tier, category max_tier.
    tier = min(action_request["tier"], cat["tier"], cat["max_tier"])
    if action_request["tier"] != tier:
        reasons.append(f"TIER_FORCED:{action_request['tier']}->{tier}")
    if tier == 0 or not policy.data["delegation_enabled"]:
        return PolicyDecision(REQUIRE_APPROVAL, 0, ref, policy.version, reasons + [f"GATED:{category}:tier0"])
    # Unreachable in wave one (schema pins delegation_enabled=false and tier=0).
    return deny("DELEGATION_NOT_IMPLEMENTED")
