"""Heartbeat for the pickup watcher (A-52): what it is doing right now, never staler than it says.

Published to `status/agent-01-pickup:PICKUP_HEALTH.json` (and var/pickup/heartbeat.json). A background thread keeps beating while a long synchronous
delivery is running, so `currently_running` carries the task id and start time DURING the delivery and is cleared only after the completion beat.
`session.status` is busy | idle | UNKNOWN; a reader treats a null or stale `observed_at` (older than `ttl_sec`) as UNKNOWN with its age, never idle.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pickup_git as pg  # noqa: E402
from pickup_state import Store, now, summary  # noqa: E402

ROOT = pg.ROOT
BUSY_PUBLISH_S, IDLE_PUBLISH_S, BEAT_S = 120, 600, 30
TTL_BUSY, TTL_IDLE = 300, 1200                 # ttl is always >= 2x the publish cadence it describes


def session_status(hb: dict, at: Optional[datetime] = None) -> dict[str, Any]:
    """Reader-side rule: null or stale -> UNKNOWN with age. Pure."""
    s = (hb or {}).get("session") or {}
    try:
        obs = datetime.fromisoformat(str(s.get("observed_at")).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return {"status": "UNKNOWN", "reason": "no observed_at", "age_s": None}
    age = ((at or datetime.now(timezone.utc)) - obs).total_seconds()
    ttl = s.get("ttl_sec") or TTL_BUSY
    if s.get("status") not in ("busy", "idle") or age > ttl:
        return {"status": "UNKNOWN", "reason": "stale reading" if age > ttl else "status missing", "age_s": round(age)}
    return {"status": s["status"], "age_s": round(age)}


def build(store: Store, git_ok: bool, interval: int, started: str, running: Optional[dict], cycle_ok: bool = True) -> dict[str, Any]:
    data = store.all()
    try:
        wd = json.loads((ROOT / "var" / "watchdog" / "status.json").read_text())["projects"]["michael_business_os"]
    except (OSError, ValueError, KeyError):
        wd = {}
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from mbos import router, telemetry
        g = telemetry.quota_guard(router.load_policy())
    except Exception as e:  # noqa: BLE001
        g = {"allow": None, "reason": f"quota reading unavailable: {e}"}
    blockers = [{"id": k, "reason": v.get("blocked"), "attempts": v.get("attempts"), "since": v.get("blocked_at"), "needs": v.get("needs")}
                for k, v in data.items() if v.get("state") == "BLOCKED"]
    if not git_ok:
        blockers.append({"id": "-", "reason": "git fetch failed: no network or no GitHub access for this account", "since": now()})
    status = "UNKNOWN" if not (git_ok and cycle_ok) else ("busy" if running else "idle")
    return {"schema": "mbos.pickup_health/1", "generated_at": now(), "host": socket.gethostname(), "account": os.environ.get("USER", "?"), "pid": os.getpid(),
            "watcher": {"status": "running" if git_ok else "DEGRADED", "interval_s": interval, "started_at": started, "inbox_ref": pg.INBOX_REF, "ack_branch": pg.COORD},
            "session": {"name": "mbos-pickup", "status": status, "pid": os.getpid(), "observed_at": now(), "source": "inbox_pickup process",
                        "ttl_sec": TTL_BUSY if running else TTL_IDLE},
            "interactive_coordinator": {"state": wd.get("state", "UNKNOWN"), "decision": wd.get("decision"), "note": "pickup does not need the interactive session"},
            "delivery_interface": {"claude_cli": bool(shutil.which("claude")), "quota_allows_a_run": g.get("allow"), "quota": g.get("reason"), "side_worktree": str(pg.SIDE)},
            "counts": summary(data), "blockers": blockers, "currently_running": running, "coordinator_head": pg.head(),
            "receipts": "var/pickup/receipts.jsonl (hash-chained, local) and docs/receipts/pickup/<id>.md on the coordinator branch"}


class Beat:
    """Owns the heartbeat. `running` is set BEFORE a delivery starts (and beaten at once) and cleared only after the completion beat."""

    def __init__(self, store: Store, directory: Path, interval: int, started: str):
        self.store, self.dir, self.interval, self.started = store, directory, interval, started
        self.running: Optional[dict] = None
        self.git_ok, self.cycle_ok = True, True
        self.key, self.last_pub = None, 0.0
        self.lock = threading.Lock()

    def beat(self, force: bool = False) -> dict[str, Any]:
        with self.lock:
            hb = build(self.store, self.git_ok, self.interval, self.started, self.running, self.cycle_ok)
            text = json.dumps(hb, indent=1, sort_keys=True)
            (self.dir / "heartbeat.json").write_text(text)
            key = json.dumps({k: hb[k] for k in ("counts", "blockers", "currently_running")}, sort_keys=True)
            cadence = BUSY_PUBLISH_S if self.running else IDLE_PUBLISH_S
            if self.git_ok and (force or key != self.key or time.time() - self.last_pub >= cadence):
                ok, detail = pg.publish_heartbeat(text)
                self.key, self.last_pub = key, time.time()
                self.store.receipt("heartbeat", "publish heartbeat", "ok" if ok else "failed: " + detail, evidence=[f"origin/{pg.STATUS_BRANCH}:PICKUP_HEALTH.json"],
                                   branch=pg.STATUS_BRANCH, sha=detail if ok else None)
            return hb

    def start_delivery(self, mid: str) -> None:
        self.running = {"id": mid, "started_at": now()}
        self.beat(force=True)

    def end_delivery(self) -> None:
        self.beat(force=True)                    # completion state published first ...
        self.running = None                      # ... and only then is the task cleared
        self.beat(force=True)

    def thread(self) -> threading.Thread:
        def loop():
            while True:
                time.sleep(BEAT_S)
                try:
                    self.beat()
                except Exception:  # noqa: BLE001  (a failed beat is retried; the main loop records errors)
                    pass
        t = threading.Thread(target=loop, daemon=True, name="pickup-beat")
        t.start()
        return t
