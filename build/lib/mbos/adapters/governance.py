"""Lane E (Agent 05) governance behind the spine (task A-03; R4/R5/R6/R7).

Agent 05's `mbos_governance.spine_adapter.build()` returns objects that satisfy `mbos.interfaces`
Gateway / KillSwitch / PolicyDecisionPoint. Install the package from 05's branch as a clean archive (RUNBOOK §6).
With `Settings.gateway_mode="lane_e"`, the gateway owns every ActionRequest status edge after approval and
its receipts (ACTION_EXECUTING / EXECUTED / FAILED, BUDGET_*); the spine moves only the Item.
"""

from __future__ import annotations

from typing import Any


def lane_e_components(dsns: str | dict[str, str], policy_path: str | None, *, panic_hooks: list | None = None,
                      dbos: Any = None, egress_file: str | None = None, litellm_file: str | None = None,
                      **component_kw: Any):
    """Return (Components, Governance) wired to lane E. `policy_path=None` reads the policy from lane D
    (`mbos.policy_current`). With `dbos`/`egress_file`/`litellm_file`, lane E wires its three L3/L1/L2 hooks
    (DBOS cancel, egress deny-all, LiteLLM budgets to zero) so a PANIC engage runs them (A-18)."""
    from mbos_governance.spine_adapter import build

    from mbos.runtime import Components

    kw: dict[str, Any] = {k: v for k, v in (("dbos", dbos), ("egress_file", egress_file), ("litellm_file", litellm_file)) if v}
    if panic_hooks:
        kw["panic_hooks"] = panic_hooks
    gov = build(dsns, policy_path, **kw)
    comps = Components(gateway=gov.gateway, kill_switch=gov.kill_switch, pdp=gov.pdp, governance=gov, **component_kw)
    return comps, gov


def reconcile_stuck_claims(gov) -> list[dict]:
    """E-05: settle claims left `executing` past the policy TTL by provider lookup; never re-sends."""
    from mbos_governance.spine_adapter import reconcile

    return reconcile(gov.action_gateway)
