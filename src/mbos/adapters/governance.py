"""Lane E (Agent 05) governance behind the spine (task A-03; R4/R5/R6/R7).

Agent 05's `mbos_governance.spine_adapter.build()` returns objects that satisfy `mbos.interfaces`
Gateway / KillSwitch / PolicyDecisionPoint. Install the package from 05's branch as a clean archive (RUNBOOK §6).
With `Settings.gateway_mode="lane_e"`, the gateway owns every ActionRequest status edge after approval and
its receipts (ACTION_EXECUTING / EXECUTED / FAILED, BUDGET_*); the spine moves only the Item.
"""

from __future__ import annotations

from typing import Any


def lane_e_components(dsns: str | dict[str, str], policy_path: str, *, panic_hooks: list | None = None,
                      **component_kw: Any):
    """Return (Components, Governance) wired to lane E. Hooks (DBOS cancel, egress, LiteLLM) are optional."""
    from mbos_governance.spine_adapter import build

    from mbos.runtime import Components

    gov = build(dsns, policy_path, panic_hooks=panic_hooks or [])
    comps = Components(gateway=gov.gateway, kill_switch=gov.kill_switch, pdp=gov.pdp, **component_kw)
    return comps, gov


def reconcile_stuck_claims(gov) -> list[dict]:
    """E-05: settle claims left `executing` past the policy TTL by provider lookup; never re-sends."""
    from mbos_governance.spine_adapter import reconcile

    return reconcile(gov.action_gateway)
