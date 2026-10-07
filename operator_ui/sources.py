"""F-09: read-only view of lane B's per-source health (Agent 02 `mbos_discovery.health.HealthBook.to_json()`,
persisted as `<data-dir>/health.json`). The UI never writes it. Clearing a freeze stays a human CLI action
on lane B's side (`--by` required). Path: MBOS_SOURCE_HEALTH_FILE."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

FIELDS = ("source", "status", "consecutive_failures", "consecutive_blocks", "total_runs", "total_failures",
          "last_run_at", "last_success_at", "last_error", "last_items_seen", "frozen_at", "freeze_reason")
STATUS_ORDER = {"FROZEN": 0, "DEGRADED": 1, "HEALTHY": 2}


def load_health(path: Optional[str] = None) -> dict:
    """{'rows': [...], 'path', 'updated_at', 'error'}. Malformed or missing data is reported, never guessed."""
    p = path or os.environ.get("MBOS_SOURCE_HEALTH_FILE")
    if not p:
        return {"rows": [], "path": None, "updated_at": None, "error": "MBOS_SOURCE_HEALTH_FILE not set"}
    f = Path(p)
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
    except FileNotFoundError:
        return {"rows": [], "path": p, "updated_at": None, "error": "health file not found"}
    except (OSError, ValueError) as e:
        return {"rows": [], "path": p, "updated_at": None, "error": f"unreadable: {type(e).__name__}"}
    if not isinstance(data, dict):
        return {"rows": [], "path": p, "updated_at": mtime, "error": "unexpected format (expected an object)"}
    rows = []
    for name, h in data.items():
        if not isinstance(h, dict):
            continue
        row = {k: h.get(k) for k in FIELDS}
        row["source"] = row["source"] or name
        if row["status"] not in STATUS_ORDER:
            row["status"] = f"UNKNOWN({row['status']})"
        rows.append(row)
    rows.sort(key=lambda r: (STATUS_ORDER.get(r["status"], -1), r["source"]))
    return {"rows": rows, "path": p, "updated_at": mtime, "error": None}
