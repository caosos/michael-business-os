"""REFERENCE governance on lane D's tables, used until A-03 wires Agent 05's real ActionGateway.

Same 8 guard checks as `ReferenceGateway`, read from lane D's document views; the kill switch is lane D's
PANIC (`mbos.panic_blocks`, FROZEN by default, fail closed); the dry-run effector claims exactly once through
`mbos.record_effector_call` (A5).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from mbos.clock import parse, utcnow
from mbos.config import settings
from mbos.hashing import canonical_json, sha256_of
from mbos.interfaces import GuardResult
from mbos.reference.governance import classify_capability


class PanicKillSwitch:
    def is_clear(self, conn: sa.Connection, *, capability: str, agent_id: str) -> tuple[bool, str]:
        try:
            category, _ = classify_capability(capability)
            reasons = conn.execute(sa.text("SELECT mbos.panic_blocks(:a, :c, :g)"),
                                   {"a": agent_id, "c": capability, "g": category}).scalar_one()
        except Exception as e:  # noqa: BLE001 — unreadable means frozen
            return False, f"PANIC state unreadable ({type(e).__name__}); failing closed"
        return (not reasons, "; ".join(reasons) if reasons else "clear")


class LaneDDryRunEffector:
    name = "dry-run"
    dry_run = True

    def execute(self, engine: sa.Engine, action_request: dict[str, Any]) -> dict[str, Any]:
        response = {"provider": f"dry-run:{action_request['capability']}",
                    "provider_msg_id": "dry_" + sha256_of(action_request["idempotency_key"])[7:33],
                    "status": "simulated", "dry_run": True}
        with engine.begin() as conn:
            row = conn.execute(sa.text("SELECT response, replayed FROM mbos.record_effector_call(:a, :p, :m, "
                                       "CAST(:req AS jsonb), CAST(:resp AS jsonb))"),
                               {"a": action_request["action_request_id"], "p": response["provider"],
                                "m": response["provider_msg_id"], "req": canonical_json(action_request["payload"]).decode(),
                                "resp": canonical_json(response).decode()}).one()
        return row.response


class LaneDReferenceGateway:
    def __init__(self, effector: Any, kill_switch: PanicKillSwitch):
        self.effector, self.kill_switch = effector, kill_switch

    def execute(self, engine: sa.Engine, action_request_id: str, approval_id: str) -> GuardResult:
        checks: dict[str, bool] = {}
        reasons: list[str] = []
        with engine.begin() as conn:
            areq = conn.execute(sa.text("SELECT doc FROM mbos.v_action_request_documents WHERE action_request_id = :a"),
                                {"a": action_request_id}).scalar_one_or_none()
            appr = conn.execute(sa.text("SELECT doc FROM mbos.v_approval_documents WHERE approval_id = :p"),
                                {"p": approval_id}).scalar_one_or_none()
            prior = conn.execute(sa.text("SELECT response FROM mbos.effector_calls WHERE idempotency_key = :k"),
                                 {"k": (areq or {}).get("idempotency_key", "")}).scalar_one_or_none()
            checks["approval_valid"] = bool(areq and appr and appr["decision"] == "YES"
                                            and appr["action_request_id"] == action_request_id
                                            and areq["status"] in ("approved", "executing"))
            now = utcnow()
            checks["not_expired"] = bool(areq and parse(areq["expires_at"]) > now
                                         and (not appr or "expires_at" not in appr or parse(appr["expires_at"]) > now))
            checks["payload_hash_match"] = bool(areq and appr and sha256_of(areq["payload"]) == areq["payload_hash"]
                                                == appr["payload_hash_seen"])
            checks["idempotency_unused"] = prior is None
            cost = (areq or {}).get("max_cost") or (areq or {}).get("estimated_cost") or {"amount": 0}
            checks["budget_reserved"] = float(cost.get("amount", 0)) == 0.0
            checks["grant_ok"] = bool(areq and areq["tier"] == 0 and checks["approval_valid"])
            clear, why = self.kill_switch.is_clear(conn, capability=(areq or {}).get("capability", "?"),
                                                   agent_id=(areq or {}).get("proposed_by", "?"))
            checks["kill_switch_clear"] = clear
            if not clear:
                reasons.append(why)
            checks["dry_run_mode"] = bool(settings().dry_run and self.effector.dry_run)
        if prior is not None and all(v for k, v in checks.items() if k != "idempotency_unused"):
            return GuardResult(ok=True, checks=checks, effector_response=prior,
                               reason="idempotent replay: effector already ran for this key; not re-executed")
        failed = [k for k, v in checks.items() if not v]
        if failed:
            reasons.insert(0, "guard denied: " + ", ".join(failed))
            return GuardResult(ok=False, checks=checks, reason="; ".join(reasons), frozen=not clear,
                               effector_response={"provider": "gateway", "status": "denied", "dry_run": True})
        return GuardResult(ok=True, checks=checks, reason="all 8 guard checks passed",
                           effector_response=self.effector.execute(engine, areq))
