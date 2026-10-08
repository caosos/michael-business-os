"""Worker telemetry (ADR-0014): an append-only, hash-chained JSONL of bounded worker runs.

Only SUPPORTED Claude Code output is used: the JSON result object from `claude -p --output-format json` (or the final `result` event
of `stream-json`). Any field the CLI did not return is None = UNKNOWN; nothing is estimated. `total_cost_usd` is Claude Code's own
computed estimate; under a Max subscription it is NOT a separate bill, and is stored as `cost_estimate_usd` to say so.
Max-plan quota percentages are not read here (manual snapshots only: see `quota_snapshot`).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from .hashing import sha256_of

GENESIS = "sha256:" + "0" * 64


def default_path() -> Path:
    env = os.environ.get("MBOS_TELEMETRY_DIR")
    base = Path(env) if env else Path(__file__).resolve().parents[2] / "var" / "telemetry"
    base.mkdir(parents=True, exist_ok=True)
    return base / "worker_runs.jsonl"


def _num(v: Any) -> Optional[float]:
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def parse_result(raw: Any) -> dict[str, Any]:
    """Normalise a Claude Code JSON result (a dict, or a list of stream events containing one `result`)."""
    if isinstance(raw, list):
        raw = next((e for e in reversed(raw) if isinstance(e, dict) and e.get("type") == "result"), {})
    d = raw if isinstance(raw, dict) else {}
    u = d.get("usage") if isinstance(d.get("usage"), dict) else {}
    mu = d.get("modelUsage") if isinstance(d.get("modelUsage"), dict) else {}
    models = sorted(mu) if mu else []
    return {
        "session_id": d.get("session_id") if isinstance(d.get("session_id"), str) else None,
        "models_used": models or None,
        "duration_ms": _num(d.get("duration_ms")),
        "duration_api_ms": _num(d.get("duration_api_ms")),
        "num_turns": int(d["num_turns"]) if isinstance(d.get("num_turns"), int) and not isinstance(d.get("num_turns"), bool) else None,
        "cost_estimate_usd": _num(d.get("total_cost_usd")),
        "input_tokens": _num(u.get("input_tokens")), "output_tokens": _num(u.get("output_tokens")),
        "cache_read_tokens": _num(u.get("cache_read_input_tokens")), "cache_creation_tokens": _num(u.get("cache_creation_input_tokens")),
        "is_error": bool(d.get("is_error")) if "is_error" in d else None,
        "subtype": d.get("subtype") if isinstance(d.get("subtype"), str) else None,
    }


def parse_stream(text: str) -> tuple[dict[str, Any], Optional[dict[str, Any]]]:
    """Parse `--output-format stream-json --verbose` output (JSON lines). Returns (result_event, last rate_limit_info or None).
    Non-JSON lines are ignored. A single JSON object (plain `--output-format json`) is also accepted."""
    result: dict[str, Any] = {}
    rl: Optional[dict[str, Any]] = None
    lines = [x for x in (text or "").splitlines() if x.strip()]
    if len(lines) == 1:
        try:
            one = json.loads(lines[0])
            if isinstance(one, dict) and one.get("type") == "result":
                return one, None
        except ValueError:
            pass
    for ln in lines:
        try:
            e = json.loads(ln)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("type") == "result":
            result = e
        elif e.get("type") == "rate_limit_event" and isinstance(e.get("rate_limit_info"), dict):
            rl = e["rate_limit_info"]
    return result, rl


def quota_from_rate_limit(info: Optional[dict[str, Any]], *, path: Optional[Path] = None) -> Optional[dict[str, Any]]:
    """Record the five-hour and seven-day utilization Claude Code reports in its documented `rate_limit_event`. Per-model (Fable)
    weekly % is NOT exposed by any supported interface, so it stays None = UNKNOWN (manual entry only)."""
    if not isinstance(info, dict):
        return None
    w = info.get("unifiedWindows") if isinstance(info.get("unifiedWindows"), dict) else {}

    def pct(name: str) -> Optional[float]:
        u = (w.get(name) or {}).get("utilization") if isinstance(w.get(name), dict) else None
        return round(float(u) * 100, 1) if isinstance(u, (int, float)) and not isinstance(u, bool) and 0 <= u <= 1 else None

    def reset(name: str) -> Optional[str]:
        t = (w.get(name) or {}).get("resetsAt") if isinstance(w.get(name), dict) else None
        return datetime.fromtimestamp(t, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if isinstance(t, (int, float)) else None

    s5, s7 = pct("five_hour"), pct("seven_day")
    if s5 is None and s7 is None:
        return None
    return append({"kind": "quota_snapshot", "at": _now(), "session_pct": s5, "week_all_pct": s7, "week_fable_pct": None,
                   "session_resets_at": reset("five_hour"), "week_resets_at": reset("seven_day"), "status": info.get("status"),
                   "source": "claude_code_rate_limit_event", "entered_by": "claude-code"}, path)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def last_hash(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return GENESIS
    with path.open("rb") as f:
        lines = f.read().splitlines()
    return json.loads(lines[-1])["row_hash"] if lines else GENESIS


def append(row: dict[str, Any], path: Optional[Path] = None) -> dict[str, Any]:
    path = path or default_path()
    body = {**row, "prev_hash": last_hash(path)}
    body["row_hash"] = sha256_of({k: v for k, v in body.items() if k != "row_hash"})
    with path.open("a") as f:
        f.write(json.dumps(body, sort_keys=True) + "\n")
    return body


def read(path: Optional[Path] = None) -> list[dict[str, Any]]:
    path = path or default_path()
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()] if path.exists() else []


def verify(rows: Iterable[dict[str, Any]]) -> list[str]:
    errs, prev = [], GENESIS
    for i, r in enumerate(rows):
        if r.get("prev_hash") != prev:
            errs.append(f"row {i}: prev_hash mismatch")
        if sha256_of({k: v for k, v in r.items() if k != "row_hash"}) != r.get("row_hash"):
            errs.append(f"row {i}: row_hash mismatch (edited)")
        prev = r.get("row_hash", "")
    return errs


def run_row(*, task_id: str, lane: str, route: dict, started_at: str, ended_at: str, exit_code: Optional[int], result: Any,
            retry: int = 0, escalated_from: Optional[str] = None, head_before: Optional[str] = None, head_after: Optional[str] = None,
            dry_run: bool = False, note: Optional[str] = None) -> dict[str, Any]:
    p = parse_result(result)
    ok = exit_code == 0 and p["is_error"] is False
    return {"kind": "worker_run", "task_id": task_id, "lane": lane, "model_requested": route.get("model"), "tier": route.get("tier"),
            "route_rule": route.get("rule_id"), "route_reason": route.get("reason"), "started_at": started_at, "ended_at": ended_at,
            **p, "exit_code": exit_code, "success": ok, "retry": retry, "escalated_from": escalated_from,
            "head_before": head_before, "head_after": head_after, "dry_run": dry_run, "note": note,
            "cost_is_estimate_not_a_bill": True}


def quota_snapshot(*, session_pct: Optional[float] = None, week_all_pct: Optional[float] = None, week_fable_pct: Optional[float] = None,
                   resets: Optional[str] = None, entered_by: str = "michael", path: Optional[Path] = None) -> dict[str, Any]:
    """MANUAL entry of what Michael reads on Claude's Usage screen. There is no supported programmatic source (see ADR-0014); None = UNKNOWN."""
    for name, v in (("session_pct", session_pct), ("week_all_pct", week_all_pct), ("week_fable_pct", week_fable_pct)):
        if v is not None and not (0 <= v <= 100):
            raise ValueError(f"{name} must be 0..100")
    return append({"kind": "quota_snapshot", "at": _now(), "session_pct": session_pct, "week_all_pct": week_all_pct,
                   "week_fable_pct": week_fable_pct, "resets": resets, "source": "manual", "entered_by": entered_by}, path)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    runs = [r for r in rows if r.get("kind") == "worker_run"]
    snaps = [r for r in rows if r.get("kind") == "quota_snapshot"]
    mix: dict[str, int] = {}
    for r in runs:
        mix[r.get("model_requested") or "UNKNOWN"] = mix.get(r.get("model_requested") or "UNKNOWN", 0) + 1
    dur = [r["duration_ms"] for r in runs if r.get("duration_ms") is not None]
    by_day: dict[str, int] = {}
    for r in runs:
        by_day[(r.get("ended_at") or "")[:10]] = by_day.get((r.get("ended_at") or "")[:10], 0) + 1
    return {"runs": len(runs), "succeeded": sum(1 for r in runs if r.get("success")), "failed": sum(1 for r in runs if not r.get("success")),
            "escalations": sum(1 for r in runs if r.get("escalated_from")), "retries": sum(r.get("retry") or 0 for r in runs),
            "model_mix": mix, "avg_duration_ms": (sum(dur) / len(dur)) if dur else None, "throughput_per_day": by_day,
            "turns_total": sum(r["num_turns"] for r in runs if r.get("num_turns") is not None),
            "cost_estimate_usd_total": round(sum(r["cost_estimate_usd"] for r in runs if r.get("cost_estimate_usd") is not None), 4),
            "cost_note": "Claude Code's computed estimate; not a separate bill under Max.",
            "quota": snaps[-1] if snaps else {"session_pct": None, "week_all_pct": None, "week_fable_pct": None, "source": "UNKNOWN (no supported programmatic source; enter a manual snapshot)"},
            "chain_errors": verify(rows)}
