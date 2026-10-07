"""E-09: governance alert queries over lane D (ADR-0005 §7 observability). QUERIES ONLY — nothing is sent.

Run as a read-only login (agent_read); `collect()` returns plain dicts, `to_ntfy()` shapes them as
ntfy-ready JSON for whatever notifier is later approved (no network here).

State alerts (always evaluated):
  panic_unreadable  CRITICAL  PANIC state cannot be read (empty / tampered / no DB) => everything is FROZEN
  freeze            HIGH (L3) / MEDIUM (L1, L2)   every freeze currently in force (mbos.panic_current)
  stuck_claim       HIGH      execution claims `executing` past policy TTL (crash; E-05 not yet settled = NEEDS_HUMAN)
  chain_broken      CRITICAL  mbos.verify_chain() fails
  live_effect       CRITICAL  A7: any receipt whose effector_response is not dry_run (mbos.v_a7_live_effects)
Event alerts (receipts since `since`):
  budget_refused    MEDIUM    reservation refused (at approval or G5 at execution; lane D MB006 caps / velocity)
  injection         HIGH      INJECTION_SUSPECTED receipts (secret in payload / injection tripwire)
  dry_run_violation CRITICAL  an effector reported a live effect (details.effector_reported.dry_run != true)
  reconciled        LOW       E-05 settled a crashed claim (provider found / not found)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
from psycopg.rows import dict_row

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
NTFY_PRIORITY = {"critical": 5, "high": 4, "medium": 3, "low": 2}


def _a(severity: str, kind: str, summary: str, **ref: Any) -> dict:
    return {"severity": severity, "kind": kind, "summary": summary, "ref": ref}


def collect(dsn: str, since: datetime | None = None, claim_ttl_seconds: int = 300) -> list[dict]:
    """All governance alerts, most severe first. A failure to read is itself a CRITICAL alert (fail loud)."""
    since = since or datetime.now(timezone.utc) - timedelta(hours=24)
    out: list[dict] = []
    try:
        conn = psycopg.connect(dsn, autocommit=True, row_factory=dict_row, connect_timeout=5)
    except Exception as exc:  # noqa: BLE001
        return [_a("critical", "panic_unreadable", f"governance DB unreachable ({type(exc).__name__}): PANIC reads FROZEN")]
    with conn:
        q = conn.execute
        # ---- state
        st = q("SELECT * FROM mbos.panic_read()").fetchone()
        if not st["readable"]:
            out.append(_a("critical", "panic_unreadable", f"PANIC state unreadable ({st['error']}): system is FROZEN"))
        else:
            for r in q("SELECT level, target, reason, revision FROM mbos.panic_current ORDER BY level DESC, target"):
                sev = "high" if r["level"] == "L3" else "medium"
                what = "GLOBAL FREEZE" if r["level"] == "L3" else f"{r['level']} freeze on {r['target']}"
                out.append(_a(sev, "freeze", f"{what}: {r['reason']}", level=r["level"], target=r["target"],
                              revision=r["revision"]))
        for r in q("SELECT c.action_request_id, c.capability, c.claimed_at FROM mbos.effector_calls c "
                   "JOIN mbos.action_requests a USING (action_request_id) "
                   "WHERE a.status = 'executing' AND c.claimed_at < now() - make_interval(secs => %s) ORDER BY c.claimed_at",
                   (claim_ttl_seconds,)):
            out.append(_a("high", "stuck_claim", f"{r['capability']} stuck executing since {r['claimed_at'].isoformat()}; "
                          "run `mbos-gov reconcile` (NEEDS_HUMAN if the provider cannot answer)",
                          action_request_id=r["action_request_id"]))
        chain = q("SELECT * FROM mbos.verify_chain()").fetchone()
        if not chain["ok"]:
            out.append(_a("critical", "chain_broken", f"receipt chain broken at seq {chain['first_bad_seq']}: {chain['reason']}",
                          seq=chain["first_bad_seq"]))
        for r in q("SELECT seq, receipt_id, action_request_id FROM mbos.v_a7_live_effects"):
            out.append(_a("critical", "live_effect", "A7 violated: a receipt records a non-dry-run effect",
                          receipt_id=r["receipt_id"], action_request_id=r["action_request_id"]))
        # ---- events since `since`
        for r in q("SELECT receipt_id, action_request_id, type, ts, details FROM mbos.receipts WHERE ts >= %s AND ("
                   " details ? 'budget_refused'"
                   " OR jsonb_array_length(coalesce(details->'failed_checks'->'G5', '[]'::jsonb)) > 0) ORDER BY seq",
                   (since,)):
            why = r["details"].get("budget_refused") or r["details"]["failed_checks"]["G5"]
            out.append(_a("medium", "budget_refused", f"budget refused: {', '.join(why)}",
                          action_request_id=r["action_request_id"], receipt_id=r["receipt_id"]))
        for r in q("SELECT receipt_id, action_request_id, ts, details FROM mbos.receipts "
                   "WHERE type = 'INJECTION_SUSPECTED' AND ts >= %s ORDER BY seq", (since,)):
            d = r["details"]
            rules = sorted({f["rule"] for f in d.get("findings", [])})
            out.append(_a("high", "injection", f"{d.get('finding', 'injection_suspected')}: {', '.join(rules)}",
                          action_request_id=r["action_request_id"] or d.get("proposed_action_request_id"),
                          receipt_id=r["receipt_id"]))
        for r in q("SELECT receipt_id, action_request_id FROM mbos.receipts WHERE ts >= %s AND details ? 'effector_reported' "
                   "AND details->'effector_reported'->'dry_run' IS DISTINCT FROM 'true'::jsonb ORDER BY seq", (since,)):
            out.append(_a("critical", "dry_run_violation", "an effector reported a LIVE effect (L3 PANIC engaged)",
                          action_request_id=r["action_request_id"], receipt_id=r["receipt_id"]))
        for r in q("SELECT receipt_id, action_request_id, type, details->>'proof' AS proof FROM mbos.receipts WHERE ts >= %s "
                   "AND (details->>'reconciled')::boolean IS TRUE ORDER BY seq", (since,)):
            if r["proof"] == "unproven":
                out.append(_a("medium", "reconcile_unproven", "a provider could not prove a send; settled failed (not retried) — "
                              "verify before re-approving", action_request_id=r["action_request_id"], receipt_id=r["receipt_id"]))
            else:
                out.append(_a("low", "reconciled", f"crashed execution reconciled -> {r['type']}",
                              action_request_id=r["action_request_id"], receipt_id=r["receipt_id"]))
    return sorted(out, key=lambda a: SEVERITY_ORDER[a["severity"]])


def to_ntfy(alerts: list[dict], topic: str = "mbos-governance") -> list[dict]:
    """ntfy JSON publish bodies (https://docs.ntfy.sh/publish/#publish-as-json). Built, never sent."""
    return [{"topic": topic, "title": f"[{a['severity'].upper()}] {a['kind']}", "message": a["summary"][:4000],
             "priority": NTFY_PRIORITY[a["severity"]], "tags": ["mbos", a["kind"]]} for a in alerts]
