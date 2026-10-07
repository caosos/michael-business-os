"""E-08: sandbox policy (ADR-0005 §7) — spec as data (policy/sandbox.v1.json) + checker. Doc + checker only:
nothing is deployed or installed. `host_readiness()` only REPORTS which runtimes exist on this host.

Invariants (each violation is reported; `check()` == [] means the spec is acceptable):
  I1  every component runs under gvisor or e2b — never the bare host
  I2  model_generated_code: e2b only, network none, no secrets, no DB login
  I3  only the gateway holds effector secrets (`effector:*`); only the gateway holds the `gateway` DB role
  I4  untrusted-input components (source_adapter, llm_agent, model_generated_code) hold no effector/approval
      rights: DB roles ⊆ {agent_read, agent_write}, no `effector:` or `ui:` secrets
  I5  `approver` DB role only for operator_ui / orchestrator; `policy_admin` for nobody (human CLI only)
  I6  hardening: drop_all_capabilities, not privileged, no host_network, no container-socket mount,
      read-only rootfs (except e2b scratch), resource limits set
  I7  one uid per component; network ∈ {none, none_except_db, loopback_only, egress_proxy}
  I8  ids unique; owners are known agents (when a policy is given)
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

SCHEMA = "mbos.governance.sandbox/1"
RUNTIMES = {"gvisor", "e2b"}
NETWORKS = {"none", "none_except_db", "loopback_only", "egress_proxy"}
UNTRUSTED_KINDS = {"source_adapter", "llm_agent", "model_generated_code"}
KINDS = {"gateway", "orchestrator", "operator_ui", "source_adapter", "llm_agent", "model_generated_code"}
REQUIRED = ("id", "kind", "owner", "runtime", "network", "uid", "db_login", "db_roles", "secrets", "untrusted_input",
            "rootfs_readonly", "writable_paths", "drop_all_capabilities", "privileged", "host_network",
            "mounts_container_socket", "limits")


def load(path: str | Path) -> dict:
    return json.loads(Path(path).read_text("utf-8"))


def check(spec: Any, policy_data: dict | None = None) -> list[str]:
    if not isinstance(spec, dict) or spec.get("sandbox_schema") != SCHEMA or not isinstance(spec.get("components"), list):
        return ["spec: wrong schema or no components"]
    p: list[str] = []
    ids, uids = set(), {}
    agents = set((policy_data or {}).get("agent_grants", {}))
    for c in spec["components"]:
        cid = c.get("id", "?") if isinstance(c, dict) else "?"
        missing = [k for k in REQUIRED if not isinstance(c, dict) or k not in c]
        if missing:
            p.append(f"{cid}: missing {missing}")
            continue
        kind, roles, secrets = c["kind"], set(c["db_roles"]), list(c["secrets"])
        if kind not in KINDS:
            p.append(f"{cid}: unknown kind {kind!r}")
        if cid in ids:
            p.append(f"{cid}: duplicate id (I8)")
        ids.add(cid)
        if agents and c["owner"] not in agents:
            p.append(f"{cid}: owner {c['owner']!r} is not a known agent (I8)")
        if c["uid"] in uids:
            p.append(f"{cid}: uid {c['uid']!r} shared with {uids[c['uid']]} (I7)")
        uids[c["uid"]] = cid
        if c["network"] not in NETWORKS:
            p.append(f"{cid}: network {c['network']!r} not allowed (I7)")
        # I1
        if c["runtime"] not in RUNTIMES:
            p.append(f"{cid}: runtime {c['runtime']!r} — must be gvisor or e2b (I1)")
        # I2
        if kind == "model_generated_code":
            if c["runtime"] != "e2b" or c["network"] != "none" or secrets or c["db_login"] or roles:
                p.append(f"{cid}: model-generated code must be e2b, network none, no secrets, no DB (I2)")
        elif c["runtime"] == "e2b":
            p.append(f"{cid}: e2b is reserved for model-generated code (I2)")
        # I3
        if any(s.startswith("effector:") for s in secrets) and kind != "gateway":
            p.append(f"{cid}: only the gateway may hold effector secrets (I3)")
        if "gateway" in roles and kind != "gateway":
            p.append(f"{cid}: only the gateway may hold the `gateway` DB role (I3)")
        # I4
        if c["untrusted_input"] or kind in UNTRUSTED_KINDS:
            if not roles <= {"agent_read", "agent_write"}:
                p.append(f"{cid}: untrusted-input component holds DB roles {sorted(roles - {'agent_read', 'agent_write'})} (I4)")
            if any(s.startswith(("effector:", "ui:")) for s in secrets):
                p.append(f"{cid}: untrusted-input component holds effector/approval secrets (I4)")
            if kind in UNTRUSTED_KINDS and not c["untrusted_input"]:
                p.append(f"{cid}: kind {kind} must declare untrusted_input=true (I4)")
        # I5
        if "approver" in roles and kind not in ("operator_ui", "orchestrator"):
            p.append(f"{cid}: `approver` role only for the Operator UI / orchestrator (I5)")
        if "policy_admin" in roles:
            p.append(f"{cid}: `policy_admin` is a human CLI act, never a running component (I5)")
        # I6
        if not c["drop_all_capabilities"] or c["privileged"] or c["host_network"] or c["mounts_container_socket"]:
            p.append(f"{cid}: hardening violated (drop caps / unprivileged / no host net / no container socket) (I6)")
        if not c["rootfs_readonly"] and c["runtime"] != "e2b":
            p.append(f"{cid}: root filesystem must be read-only (I6)")
        if not all(k in (c["limits"] or {}) for k in ("memory_mb", "cpus", "pids")):
            p.append(f"{cid}: resource limits memory_mb/cpus/pids required (I6)")
    return p


def host_readiness() -> dict[str, Any]:
    """What this host can run today. Report only — installs nothing (host changes are Michael's call)."""
    found = {t: shutil.which(t) for t in ("runsc", "podman", "docker", "e2b")}
    ready = bool(found["runsc"] and (found["podman"] or found["docker"]))
    return {"tools": found, "gvisor_ready": ready,
            "note": "spec only until runsc + a container runtime exist on the host" if not ready else "runtimes present"}
