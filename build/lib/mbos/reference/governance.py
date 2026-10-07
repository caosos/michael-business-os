"""REFERENCE governance stubs — owner: Lane E Governance (Agent 05). Replace, don't extend.

These implement ADR-0005's minimum for the dry-run MVP so A5/A7/A8/A9 can run:
- DenyByDefaultPDP: every action is tier 0 and requires Michael (MICHAEL_DECISIONS #5: no delegation).
- TableKillSwitch: reads `mbos.governance_flags`; fails CLOSED on any error or missing/malformed flag.
- ReferenceGateway: the 8 execution-guard checks, then the Effector.
- DryRunEffector: records the would-be call in `mbos.effector_calls`; never touches the outside world.
- LedgerLLMBudget: per-agent daily cap over `mbos.llm_spend` (LiteLLM virtual keys come from lane E).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

import sqlalchemy as sa

from mbos import __version__
from mbos.clock import parse, utcnow
from mbos.config import settings
from mbos.hashing import canonical_json, sha256_of
from mbos.interfaces import BudgetExceeded, Effector, GuardResult, KillSwitch, PolicyDecision

POLICY_VERSION = "mvp-tier0-2026.10.0"

# capability prefix → (Agent 05 category, Receipt.effect). Unknown capabilities fall to the most
# restrictive bucket.
_CAPABILITY_MAP: list[tuple[str, str, str]] = [
    ("comms.email.", "email", "send"),
    ("comms.sms.", "sms", "send"),
    ("comms.voice.", "phone_call", "send"),
    ("comms.phone.", "phone_call", "send"),
    ("comms.", "message", "send"),
    ("message.", "message", "send"),
    ("offer.", "offer", "commit"),
    ("money.", "money", "pay"),
    ("purchase.", "purchase", "pay"),
    ("publish.", "publishing", "publish"),
    ("schedule.", "scheduling", "schedule"),
    ("price.", "price_change", "update"),
]


def classify_capability(capability: str) -> tuple[str, str]:
    for prefix, category, effect in _CAPABILITY_MAP:
        if capability.startswith(prefix):
            return category, effect
    return "external_commitment", "commit"


class DenyByDefaultPDP:
    def decide(self, action_request: dict[str, Any]) -> PolicyDecision:
        category, _ = classify_capability(action_request["capability"])
        return PolicyDecision(
            decision="require_approval", tier=0, category=category, policy_version=POLICY_VERSION,
            reason="MVP: every external action is tier 0 and needs Michael's explicit approval "
                   "(MICHAEL_DECISIONS #5: no delegation)",
        )


class TableKillSwitch:
    """L3 global / L2 capability / L1 agent freeze flags. Fail closed."""

    def is_clear(self, conn: sa.Connection, *, capability: str, agent_id: str) -> tuple[bool, str]:
        try:
            rows = dict(conn.execute(
                sa.text("SELECT key, value FROM mbos.governance_flags WHERE key = ANY(:k)"),
                {"k": ["global_freeze", f"capability_freeze:{capability}", f"agent_freeze:{agent_id}"]},
            ).all())
        except Exception as e:  # noqa: BLE001 — any failure to read the switch means frozen
            return False, f"kill switch unreadable ({type(e).__name__}); failing closed"
        g = rows.get("global_freeze")
        if not isinstance(g, dict) or g.get("frozen") is not False:
            return False, "L3 global freeze is set, or the flag is missing/malformed (fail closed)"
        for key in (f"capability_freeze:{capability}", f"agent_freeze:{agent_id}"):
            v = rows.get(key)
            if v is not None and (not isinstance(v, dict) or v.get("frozen") is not False):
                return False, f"{key} is frozen"
        return True, "clear"


class DryRunEffector:
    """Simulates any capability. Exactly-once per idempotency key (A5); dry_run is always true (A7)."""

    name = "dry-run"
    dry_run = True

    def execute(self, engine: sa.Engine, action_request: dict[str, Any]) -> dict[str, Any]:
        key = action_request["idempotency_key"]
        response = {
            "provider": f"dry-run:{action_request['capability']}",
            "provider_msg_id": "dry_" + sha256_of(key)[7:33],
            "status": "simulated",
            "dry_run": True,
        }
        with engine.begin() as conn:
            row = conn.execute(sa.text(
                "INSERT INTO mbos.effector_calls (idempotency_key, action_request_id, capability, provider, "
                " provider_msg_id, dry_run, request, response) "
                "VALUES (:k, :a, :c, :p, :m, true, CAST(:req AS jsonb), CAST(:resp AS jsonb)) "
                "ON CONFLICT (idempotency_key) DO NOTHING RETURNING response"),
                {"k": key, "a": action_request["action_request_id"], "c": action_request["capability"],
                 "p": response["provider"], "m": response["provider_msg_id"],
                 "req": canonical_json(action_request["payload"]).decode(), "resp": canonical_json(response).decode()},
            ).one_or_none()
            if row is None:  # already executed under this key: return the original, do not act again
                row = conn.execute(sa.text("SELECT response FROM mbos.effector_calls WHERE idempotency_key = :k"),
                                   {"k": key}).one()
            return row.response


class ReferenceGateway:
    """ADR-0005 execution guard. All 8 checks must pass before the Effector is called."""

    def __init__(self, effector: Effector, kill_switch: KillSwitch):
        self.effector = effector
        self.kill_switch = kill_switch

    def execute(self, engine: sa.Engine, action_request_id: str, approval_id: str) -> GuardResult:
        checks: dict[str, bool] = {}
        reasons: list[str] = []
        frozen = False
        with engine.begin() as conn:
            areq_row = conn.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a"),
                                    {"a": action_request_id}).one_or_none()
            appr_row = conn.execute(sa.text("SELECT body FROM mbos.approvals WHERE approval_id = :p"),
                                    {"p": approval_id}).one_or_none()
            areq: Optional[dict] = areq_row.body if areq_row else None
            appr: Optional[dict] = appr_row.body if appr_row else None
            prior = conn.execute(sa.text("SELECT response FROM mbos.effector_calls WHERE idempotency_key = :k"),
                                 {"k": areq["idempotency_key"] if areq else ""}).one_or_none()

            # 1. approval valid: an explicit YES by Michael for exactly this request
            checks["approval_valid"] = bool(
                areq and appr and appr["decision"] == "YES" and appr["action_request_id"] == action_request_id
                and areq["status"] in ("approved", "executing"))
            # 2. not expired
            now = utcnow()
            checks["not_expired"] = bool(
                areq and parse(areq["expires_at"]) > now
                and (appr is None or "expires_at" not in appr or parse(appr["expires_at"]) > now))
            # 3. payload hash: recomputed == frozen == what Michael saw
            checks["payload_hash_match"] = bool(
                areq and appr and sha256_of(areq["payload"]) == areq["payload_hash"] == appr["payload_hash_seen"])
            # 4. idempotency key unused (a prior call means: replay its response, never act twice)
            checks["idempotency_unused"] = prior is None
            # 5. budget reserved: MVP real-world spend is deny-all, so only zero-cost actions pass
            cost = (areq or {}).get("max_cost") or (areq or {}).get("estimated_cost") or {"amount": 0}
            checks["budget_reserved"] = float(cost.get("amount", 0)) == 0.0
            # 6. grant: tier 0 needs an explicit approval; no delegation grants exist in the MVP
            checks["grant_ok"] = bool(areq and areq["tier"] == 0 and checks["approval_valid"])
            # 7. kill switch clear (fail closed)
            clear, why = self.kill_switch.is_clear(conn, capability=(areq or {}).get("capability", "?"),
                                                   agent_id=(areq or {}).get("proposed_by", "?"))
            checks["kill_switch_clear"] = clear
            if not clear:
                frozen = True
                reasons.append(why)
            # 8. dry-run mode forced
            checks["dry_run_mode"] = bool(settings().dry_run and self.effector.dry_run)

        if prior is not None and all(v for k, v in checks.items() if k != "idempotency_unused"):
            return GuardResult(ok=True, checks=checks, effector_response=prior.response,
                               reason="idempotent replay: effector already ran for this key; not re-executed")
        failed = [k for k, v in checks.items() if not v]
        if failed:
            reasons.insert(0, "guard denied: " + ", ".join(failed))
            return GuardResult(ok=False, checks=checks, reason="; ".join(reasons), frozen=frozen,
                               effector_response={"provider": "gateway", "status": "denied", "dry_run": True})
        response = self.effector.execute(engine, areq)  # type: ignore[arg-type]
        return GuardResult(ok=True, checks=checks, reason="all 8 guard checks passed", effector_response=response)


class LedgerLLMBudget:
    """Per-agent daily LLM spend cap. Default cap is $0 (no LLM use in the dry-run MVP)."""

    def __init__(self, caps: Optional[dict[str, float]] = None):
        self.caps = caps

    def _cap(self, agent_id: str) -> float:
        caps = self.caps if self.caps is not None else settings().llm_daily_cap_usd
        return float(caps.get(agent_id, caps.get("*", 0.0)))

    def spent_today(self, conn: sa.Connection, agent_id: str) -> float:
        return float(conn.execute(sa.text(
            "SELECT coalesce(sum(usd), 0) FROM mbos.llm_spend WHERE agent_id = :a AND day = :d"),
            {"a": agent_id, "d": date.today()}).scalar_one())

    def authorize(self, conn: sa.Connection, agent_id: str, est_usd: float) -> None:
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext(:k))"), {"k": f"llm:{agent_id}"})
        spent = self.spent_today(conn, agent_id)
        if spent + est_usd > self._cap(agent_id):
            raise BudgetExceeded(f"{agent_id}: LLM spend {spent:.4f} + {est_usd:.4f} exceeds daily cap {self._cap(agent_id):.4f}")

    def record(self, conn: sa.Connection, agent_id: str, usd: float, trace_id: Optional[str] = None) -> None:
        conn.execute(sa.text("INSERT INTO mbos.llm_spend (agent_id, day, usd, trace_id) VALUES (:a, :d, :u, :t)"),
                     {"a": agent_id, "d": date.today(), "u": usd, "t": trace_id})


GATEWAY_TOOL = f"mbos.reference.governance.ReferenceGateway@{__version__}"
