"""E-07: egress allow-list per adapter/effector as policy data (ADR-0005 §7) + a fail-closed checker.

`policy.egress.catalog` names every outbound destination an adapter or effector may ever need. The
EFFECTIVE allow-list (what the default-deny proxy permits) is only the ENABLED entries of agents not
frozen — and in wave one the schema pins every entry `enabled: false`, so it is empty. Enabling a
source (e.g. lane B's GSA adapter) is a reviewed schema + data change, then `mbos-gov render egress`.

check_catalog() runs inside the policy loader: any problem => the policy is unavailable => deny all.
"""
from __future__ import annotations

import ipaddress
import re

from .panic import PanicState

_LABEL = r"(?!-)[a-z0-9-]{1,63}(?<!-)"
FQDN = re.compile(rf"^(?:{_LABEL}\.)+[a-z]{{2,63}}$")
FORBIDDEN_SUFFIXES = (".local", ".internal", ".localhost", ".lan", ".home", ".corp", ".test", ".invalid", ".example")
READ_ONLY = {"GET", "HEAD"}


def check_catalog(data: dict) -> list[str]:
    egress = data.get("egress") or {}
    problems: list[str] = []
    seen_ids: set[str] = set()
    agents = set(data.get("agent_grants", {}))
    for e in egress.get("catalog", []):
        eid = e.get("id", "?")
        if eid in seen_ids:
            problems.append(f"egress {eid}: duplicate id")
        seen_ids.add(eid)
        if e.get("owner") not in agents:
            problems.append(f"egress {eid}: owner {e.get('owner')!r} is not a known agent")
        kind = e.get("kind")
        if (kind == "source_adapter") != eid.startswith("adapter:"):
            problems.append(f"egress {eid}: id prefix does not match kind {kind}")
        if kind == "source_adapter" and not set(e.get("methods", [])) <= READ_ONLY:
            problems.append(f"egress {eid}: source adapters are read-only (GET/HEAD)")
        for h in e.get("hosts", []):
            if h != h.lower() or h.endswith("."):
                problems.append(f"egress {eid}: host {h!r} must be lowercase without trailing dot")
                continue
            try:
                ipaddress.ip_address(h)
                problems.append(f"egress {eid}: IP literal {h!r} not allowed (name the service)")
                continue
            except ValueError:
                pass
            if "*" in h or not FQDN.match(h):
                problems.append(f"egress {eid}: {h!r} is not an exact FQDN (no wildcards)")
            elif h == "localhost" or h.endswith(FORBIDDEN_SUFFIXES):
                problems.append(f"egress {eid}: {h!r} is a local/internal/reserved name")
    return problems


def effective_allow(data: dict | None, panic: PanicState) -> dict[str, list[str]]:
    """Hosts the proxy may allow per agent: enabled catalog entries + legacy `allow`, minus L1-frozen agents.
    Nothing at all when the policy or PANIC is unreadable or L3 is engaged."""
    if data is None or not panic.readable or panic.global_state != "RUNNING":
        return {}
    egress = data.get("egress") or {}
    out: dict[str, set[str]] = {}
    for agent, hosts in egress.get("allow", {}).items():
        out.setdefault(agent, set()).update(hosts)
    for e in egress.get("catalog", []):
        if e.get("enabled") is True:
            out.setdefault(e["owner"], set()).update(e["hosts"])
    return {a: sorted(h) for a, h in out.items() if a not in panic.frozen_agents and h}
