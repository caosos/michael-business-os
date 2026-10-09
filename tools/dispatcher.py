"""Automatic dispatcher (Aria 2145 / ADR-0014): keeps bounded workers running while useful READY work exists.

    .venv/bin/python -I tools/dispatcher.py [--once] [--max-parallel 2] [--interval 90] [--dry]

Loop: fetch origin -> read each specialist lane's READY tasks (tools/foreman.survey) -> launch `tools/worker.py` for the highest-priority
dependency-ready task of every idle lane, within these limits: at most N heavy workers at once (default 2), the supported-quota guard
(`mbos.telemetry.quota_guard`), at most 3 attempts per task, at most 12 launches per hour. It never launches lane 01 (the persistent coordinator
owns merges), never an owner-gated row, and never anything but DRY-RUN workers. It stops itself when nothing is READY. Every decision is logged to
var/dispatcher.jsonl (append-only). It sends nothing and contacts no one.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import foreman  # noqa: E402
from mbos import router, telemetry  # noqa: E402

LOG = ROOT / "var" / "dispatcher.jsonl"
MAX_ATTEMPTS, MAX_PER_HOUR = 3, 12
OWNER_GATED = ("owner", "michael", "credential", "host")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(event: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps({"at": now(), **event}) + "\n")


def profile_for(task: dict) -> dict:
    """Cheapest capable defaults: Sonnet; reviews and P0/security work get more turns. The router decides the model."""
    tid, pri, title = task["id"], task.get("pri", ""), task.get("title", "").lower()
    review = tid.startswith("G-") or "qa" in title
    risky = pri.startswith("P0") or any(w in title for w in ("security", "migration", "owner_channel", "approver", "panic"))
    return {"kind": "review" if review else "implement", "risk": "high" if risky else "medium", "max_turns": 100 if (risky or review) else 80,
            "model": "sonnet" if review else None}


def plan_launches(report: list[dict], running_lanes: set[str], attempts: dict[str, int], launched_last_hour: int, quota_ok: bool,
                  max_parallel: int, gated_ids: set[str] = frozenset()) -> tuple[list[tuple[str, dict]], str]:
    """Pure decision: which (lane, task) to launch now, and why not otherwise."""
    if not quota_ok:
        return [], "quota guard"
    slots = max_parallel - len(running_lanes)
    if slots <= 0:
        return [], "parallelism limit"
    budget = MAX_PER_HOUR - launched_last_hour
    if budget <= 0:
        return [], "hourly launch limit"
    out: list[tuple[str, dict]] = []
    for r in report:
        if r["lane"] in running_lanes or r["lane"] == "01" or r["state"] == "WORKING" and r["claimed"]:
            continue
        for t in r["ready"]:
            if t["id"] in gated_ids or attempts.get(t["id"], 0) >= MAX_ATTEMPTS:
                continue
            if any(w in (t.get("title") or "").lower() for w in OWNER_GATED) and not t["id"].startswith(("G-", "F-", "C-", "D-", "E-", "B-")):
                continue
            out.append((r["lane"], t))
            break
        if len(out) >= min(slots, budget):
            break
    return out, ("ok" if out else "nothing ready for an idle lane")


def lanes_running_in_os(ps_text: str | None = None) -> set[str]:
    """Lanes that already have a `tools/worker.py` process (started by anyone: this daemon or Agent 01 by hand). Prevents duplicate workers."""
    if ps_text is None:
        ps_text = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True).stdout
    lanes: set[str] = set()
    for ln in ps_text.splitlines():
        if "tools/worker.py" in ln and "--lane" in ln and "dispatcher.py" not in ln and "grep" not in ln:
            parts = ln.split()
            try:
                lanes.add(parts[parts.index("--lane") + 1])
            except (ValueError, IndexError):
                pass
    return lanes


def launched_recent() -> int:
    if not LOG.exists():
        return 0
    cutoff = time.time() - 3600
    n = 0
    for ln in LOG.read_text().splitlines():
        try:
            e = json.loads(ln)
            if e.get("event") == "launch" and datetime.fromisoformat(e["at"].replace("Z", "+00:00")).timestamp() >= cutoff:
                n += 1
        except (ValueError, KeyError):
            pass
    return n


def attempts_so_far() -> dict[str, int]:
    out: dict[str, int] = {}
    if LOG.exists():
        for ln in LOG.read_text().splitlines():
            try:
                e = json.loads(ln)
                if e.get("event") == "launch":
                    out[e["task"]] = out.get(e["task"], 0) + 1
            except (ValueError, KeyError):
                pass
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--max-parallel", type=int, default=2)
    ap.add_argument("--interval", type=int, default=90)
    ap.add_argument("--dry", action="store_true", help="decide and log, launch nothing")
    a = ap.parse_args(argv)
    procs: dict[str, tuple[subprocess.Popen, str]] = {}   # lane -> (process, task)
    idle_rounds = 0
    while True:
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=ROOT)
        for lane, (p, task) in list(procs.items()):
            if p.poll() is not None:
                log({"event": "exit", "lane": lane, "task": task, "rc": p.returncode})
                del procs[lane]
        report, warnings = foreman.survey(ROOT)
        guard = telemetry.quota_guard(router.load_policy())
        plan, why = plan_launches(report, set(procs) | lanes_running_in_os(), attempts_so_far(), launched_recent(), guard["allow"], a.max_parallel)
        for lane, t in plan:
            prof = profile_for(t)
            cmd = [sys.executable, "-I", "tools/worker.py", t["id"], "--lane", lane, "--kind", prof["kind"], "--risk", prof["risk"],
                   "--max-turns", str(prof["max_turns"]), "--timeout", "3500"] + (["--model", prof["model"]] if prof["model"] else [])
            log({"event": "launch", "lane": lane, "task": t["id"], "cmd": " ".join(cmd[2:]), "dry": a.dry})
            if not a.dry:
                out = open(ROOT / "var" / f"worker-{t['id']}.out", "w")
                procs[lane] = (subprocess.Popen(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT), t["id"])
        if not plan:
            log({"event": "idle", "why": why, "quota": guard["reason"], "running": sorted(set(procs) | lanes_running_in_os())})
        idle_rounds = idle_rounds + 1 if (not plan and not procs and not lanes_running_in_os() and why == "nothing ready for an idle lane") else 0
        if a.once or (idle_rounds >= 3):
            log({"event": "stop", "reason": "once" if a.once else "no READY work for any idle lane (3 rounds)"})
            return 0
        time.sleep(a.interval)


if __name__ == "__main__":
    sys.exit(main())
