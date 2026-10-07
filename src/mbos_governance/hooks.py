"""PANIC side-effect hooks and config generators (E-03; ADR-0005 §5 L3, A8/A9 hardening). DRY.

Nothing here opens a network connection. Hooks write LOCAL files or call an injected
workflow engine; applying the generated configs to a proxy / LiteLLM is a separate,
operator-run step (not wired in wave one).

  DbosCancelHook     L3 engage: cancel workflows that have NOT started (ENQUEUED, DELAYED) via
                     DBOS.cancel_workflows; workflows already running (PENDING) are reported as
                     "in-flight at freeze" and are stopped by the gateway's late PANIC read.
  EgressPolicyHook   renders the egress policy file. Default deny; per-agent allow-lists come from
                     policy data (wave one: all empty). Any freeze affecting egress => deny-all.
  LiteLLMBudgetHook  renders per-agent LiteLLM virtual-key budget specs from policy `llm_spend`.
                     L3 => every max_budget 0; L1 => that agent's max_budget 0.

Generators are pure functions of (policy, panic state). An UNREADABLE panic state or policy
renders the frozen form (deny-all egress, zero budgets): fail closed.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Protocol

from .ids import canonical_json, fmt_ts_us, sha256_tagged, utcnow
from .panic import PanicState

EGRESS_SCHEMA = "mbos.egress/1"
LITELLM_SCHEMA = "mbos.litellm.keys/1"
UNSTARTED = ["ENQUEUED", "DELAYED"]  # dbos 3.2.0 WorkflowStatusString
RUNNING = ["PENDING"]


class PanicHook(Protocol):
    name: str

    def on_change(self, level: str, target: str | None, engage: bool, state: PanicState) -> dict: ...


def _seal(body: dict) -> dict:
    body = {k: v for k, v in body.items() if k != "checksum"}
    return {**body, "checksum": sha256_tagged(canonical_json(body))}


def verify_sealed(doc: Any) -> bool:
    return isinstance(doc, dict) and doc.get("checksum") == _seal(doc)["checksum"]


def _atomic_write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(doc, indent=2, sort_keys=True))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


# ------------------------------------------------------------------ generators (pure)
def render_egress(policy_data: dict | None, panic: PanicState) -> dict:
    """Egress policy for the (future) default-deny proxy. Consumers MUST treat a missing file,
    a bad checksum or `default != "deny"` as deny-all."""
    reasons = []
    if policy_data is None:
        reasons.append("POLICY_UNREADABLE")
    if not panic.readable:
        reasons.append(f"PANIC_STATE_UNREADABLE:{panic.error}")
    elif panic.global_state != "RUNNING":
        reasons.append("PANIC_L3_FROZEN")
    allow: dict[str, list[str]] = {}
    if not reasons:
        for agent, hosts in policy_data.get("egress", {}).get("allow", {}).items():
            if agent in panic.frozen_agents:
                continue  # L1: agent loses egress
            allow[agent] = sorted(hosts)
    return _seal({
        "schema": EGRESS_SCHEMA,
        "default": "deny",
        "deny_all": bool(reasons),
        "reasons": reasons,
        "allow": allow,
        "policy_version": (policy_data or {}).get("version", "UNAVAILABLE"),
        "panic_revision": panic.revision,
        "generated_at": fmt_ts_us(utcnow()),
    })


def render_litellm_keys(policy_data: dict | None, panic: PanicState) -> dict:
    """Request bodies for LiteLLM `POST /key/generate` or `/key/update`, one per agent.
    INFERENCE: field names (key_alias, max_budget, budget_duration, metadata) follow the LiteLLM
    proxy key API; re-check against the LiteLLM version that gets pinned (UNKNOWN today)."""
    frozen_reasons = []
    if policy_data is None:
        frozen_reasons.append("POLICY_UNREADABLE")
    if not panic.readable:
        frozen_reasons.append(f"PANIC_STATE_UNREADABLE:{panic.error}")
    elif panic.global_state != "RUNNING":
        frozen_reasons.append("PANIC_L3_FROZEN")
    spend = (policy_data or {}).get("llm_spend", {})
    agents = sorted((policy_data or {}).get("agent_grants", {}))
    keys = []
    for agent in agents:
        budget = float(spend.get("per_agent_daily_usd", {}).get(agent, spend.get("default_agent_daily_usd", 0)))
        why = list(frozen_reasons)
        if agent in panic.frozen_agents:
            why.append(f"PANIC_L1_AGENT:{agent}")
        keys.append({
            "key_alias": f"mbos-{agent}",
            "max_budget": 0.0 if why else budget,
            "budget_duration": "1d",
            "metadata": {"agent_id": agent, "max_tokens_per_call": spend.get("max_tokens_per_call"),
                         "zeroed_by": why, "policy_daily_usd": budget},
        })
    return _seal({
        "schema": LITELLM_SCHEMA,
        "apply_via": "operator: LiteLLM proxy key API (/key/generate, /key/update). Not called by this code.",
        "frozen": bool(frozen_reasons),
        "keys": keys,
        "policy_version": (policy_data or {}).get("version", "UNAVAILABLE"),
        "panic_revision": panic.revision,
        "generated_at": fmt_ts_us(utcnow()),
    })


# ------------------------------------------------------------------ hooks
class _PolicyReader:
    def __init__(self, policy_store):
        self._ps = policy_store

    def data(self) -> dict | None:
        try:
            return self._ps.current().data
        except Exception:  # noqa: BLE001 - any failure renders the frozen form
            return None


class EgressPolicyHook(_PolicyReader):
    name = "egress_policy"

    def __init__(self, path: str | os.PathLike, policy_store):
        super().__init__(policy_store)
        self.path = Path(path)

    def on_change(self, level, target, engage, state):
        doc = render_egress(self.data(), state)
        _atomic_write(self.path, doc)
        return {"path": str(self.path), "deny_all": doc["deny_all"], "allow_agents": sorted(doc["allow"])}


class LiteLLMBudgetHook(_PolicyReader):
    name = "litellm_budgets"

    def __init__(self, path: str | os.PathLike, policy_store):
        super().__init__(policy_store)
        self.path = Path(path)

    def on_change(self, level, target, engage, state):
        doc = render_litellm_keys(self.data(), state)
        _atomic_write(self.path, doc)
        return {"path": str(self.path), "frozen": doc["frozen"],
                "zeroed": sorted(k["metadata"]["agent_id"] for k in doc["keys"] if k["max_budget"] == 0)}


class DbosCancelHook:
    """`dbos` is the DBOS class (or any object with the same two classmethods):
    list_workflows(status=[...]) -> [obj with .workflow_id/.status]; cancel_workflows(workflow_ids)."""

    name = "dbos_cancel"

    def __init__(self, dbos):
        self.dbos = dbos

    def on_change(self, level, target, engage, state):
        if level != "L3" or not engage:
            return {"skipped": "only L3 engage cancels workflows"}
        unstarted = [w.workflow_id for w in self.dbos.list_workflows(status=UNSTARTED)]
        if unstarted:
            self.dbos.cancel_workflows(unstarted)
        in_flight = [w.workflow_id for w in self.dbos.list_workflows(status=RUNNING)]
        return {"cancelled": unstarted, "in_flight_at_freeze": in_flight}


def run_hooks(hooks, level: str, target: str | None, engage: bool, state: PanicState) -> dict:
    """Run every hook; one failing hook never stops the others or the freeze."""
    out = {}
    for h in hooks:
        try:
            out[h.name] = {"ok": True, **h.on_change(level, target, engage, state)}
        except Exception as exc:  # noqa: BLE001
            out[h.name] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    return out
