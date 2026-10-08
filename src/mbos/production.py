"""Production assembly (A-36): the components `mbos worker` ACTUALLY runs.

Before this module only the test runner wired the real lane engine, gateway and enrichers; `mbos worker` ran the placeholder scorer on
the reference store. `build_components(settings)` assembles the real lanes when they are installed and returns a `report`: one line per
component saying REAL (module) or STAND-IN (why), so the operator is never left guessing what is running. Everything is DRY-RUN.
Nothing here contacts anyone, spends money or publishes.
"""

from __future__ import annotations

import importlib.util
import os
from typing import Any, Optional

from mbos.config import Settings


def _have(mod: str) -> bool:
    try:
        return importlib.util.find_spec(mod) is not None
    except (ImportError, ValueError):
        return False


def build_components(s: Settings, *, fixture: Optional[str] = None, raw_dir: Optional[str] = None, dbos: Any = None) -> tuple[Any, list[dict]]:
    """Return (Components, report). `report` rows: {component, kind: REAL|STAND-IN, detail}."""
    from mbos.runtime import Components

    report: list[dict] = []

    def say(component: str, kind: str, detail: str) -> None:
        report.append({"component": component, "kind": kind, "detail": detail})

    comps, gov = Components(), None
    say("state store", "REAL" if s.state_backend == "lane_d" else "STAND-IN",
        "lane D (Agent 04) canonical schema" if s.state_backend == "lane_d" else "reference DDL (dev only; the Operator UI reads lane D)")

    if s.gateway_mode == "lane_e":
        if not _have("mbos_governance"):
            raise RuntimeError("gateway_mode=lane_e but mbos_governance is not installed (run tools/sync_lanes.py)")
        from mbos.adapters.governance import lane_e_components, role_dsns

        # the workflow process holds the worker login only: the approver DSN stays out of it (D-26 / R14)
        comps, gov = lane_e_components(role_dsns(s.database_url, None), os.environ.get("MBOS_POLICY_PATH") or None, dbos=dbos,
                                       egress_file=os.environ.get("MBOS_EGRESS_FILE") or "var/egress_policy.json",
                                       litellm_file=os.environ.get("MBOS_LITELLM_FILE") or "var/litellm_keys.json")
        say("governance (PDP, gateway, PANIC)", "REAL", "lane E (Agent 05) ActionGateway; policy " +
            ("from file " + os.environ["MBOS_POLICY_PATH"] if os.environ.get("MBOS_POLICY_PATH") else "from lane D (fail-closed if none published)"))
    else:
        say("governance (PDP, gateway, PANIC)", "STAND-IN", "reference gateway / deny-by-default PDP (dev only)")

    ledger = None
    if os.environ.get("MBOS_SCORER", "engine") == "engine" and _have("mbos_economics"):
        from mbos.adapters.economics import EconomicsEngineScorer, EconomicsEnricher

        from mbos.adapters.ledger import LedgerContext

        ledger = LedgerContext(s.database_url) if s.state_backend == "lane_d" else None  # F-96: funded ledger -> scoring context
        comps.scorer = EconomicsEngineScorer(context_source=ledger)
        import mbos_economics

        say("scoring", "REAL", f"lane C (Agent 03) engine {getattr(mbos_economics, '__version__', '?')}, bankroll-bound class-aware gates")
        comps.enrichers.append(EconomicsEnricher())
        say("card enrichment: economics/value-add", "REAL", "lane C blocks (economics, logistics, seasonality, why, value_add)")
    else:
        say("scoring", "STAND-IN", "placeholder scorer (mbos_economics not installed or MBOS_SCORER=placeholder); its numbers are NOT advice")

    if _have("mbos_discovery"):
        from mbos.adapters.discovery import LaneBEnricher

        rd = raw_dir or os.environ.get("MBOS_RAW_DIR")
        if rd:
            from mbos_discovery.rawstore import FileRawStore  # type: ignore

            comps.enrichers.append(LaneBEnricher(FileRawStore(rd)))
            say("card enrichment: listing activity/seller", "REAL", f"lane B (Agent 02) from retained raw payloads in {rd}")
        else:
            say("card enrichment: listing activity/seller", "STAND-IN", "MBOS_RAW_DIR not set: listing age/seller stay UNKNOWN on the card")
    else:
        say("card enrichment: listing activity/seller", "STAND-IN", "mbos_discovery not installed: listing age/seller stay UNKNOWN")

    cs, inbox = os.environ.get("MBOS_COMPS_STORE") or None, os.environ.get("MBOS_COMPS_INBOX") or None
    if _have("mbos_economics") and _have("mbos_discovery") and (cs or inbox):
        from mbos.adapters.comps import ProductionCompsSource
        from mbos.adapters.economics import EconomicsResearcher

        src = ProductionCompsSource(cs, inbox)
        comps.researcher = EconomicsResearcher(src, context_source=ledger)
        say("research (comps)", "REAL", f"lane C research step; comps source: {src.describe()}")
    else:
        say("research (comps)", "STAND-IN", "none: MBOS_COMPS_STORE / MBOS_COMPS_INBOX not set (or lane B/C not installed); "
            "every listing without inline economics parks at RESEARCHING")

    try:
        from comms_spec.planner import CommsActionPlanner  # type: ignore

        comps.planner = CommsActionPlanner()
        say("action planner", "REAL", "lane F (Agent 06) CommsActionPlanner")
    except Exception:  # noqa: BLE001  (optional lane package)
        say("action planner", "STAND-IN", "reference planner: one generic first-contact draft")

    if fixture:
        from mbos.reference.fixture_adapter import FixtureSourceAdapter

        comps.adapters["fixture"] = FixtureSourceAdapter(fixture, name="fixture")
        say("sources", "STAND-IN", f"fixture file {fixture} (no live source: credentials pending, B-12)")
    else:
        say("sources", "STAND-IN", "no source adapter configured (run discovery with `mbos-discover`, or pass --fixture)")
    comps.governance = gov or comps.governance
    return comps, report


def render_report(report: list[dict]) -> str:
    w = max(len(r["component"]) for r in report)
    return "\n".join(f"  {r['kind']:<8} {r['component']:<{w}}  {r['detail']}" for r in report)
