#!/usr/bin/env python3
"""Plain-English view of DealSniffer's background workers: what is running now and what finished recently.
Read-only: looks at running processes and var/telemetry/worker_runs.jsonl; starts, stops and changes nothing.
    python3 tools/workers_now.py            once
    watch -n 30 python3 tools/workers_now.py   refresh every 30 s (Ctrl+C to quit)
"""
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "var" / "telemetry" / "worker_runs.jsonl"
LANES = {"01": "coordinator", "02": "sources", "03": "economics", "04": "database", "05": "governance", "06": "Marketplace page", "07": "research"}


def running():
    out = subprocess.run(["ps", "-eo", "pid,etimes,args"], capture_output=True, text=True).stdout.splitlines()[1:]
    rows = []
    for line in out:
        pid, secs, args = line.strip().split(None, 2)
        argv = args.split()
        if len(argv) > 3 and argv[0].endswith("python") and "tools/worker.py" in argv[2:4]:
            i = argv.index(next(a for a in argv if a.endswith("tools/worker.py")))
            task = argv[i + 1] if i + 1 < len(argv) else "?"
            lane = argv[argv.index("--lane") + 1] if "--lane" in argv else "?"
            rows.append((task, lane, int(secs) // 60, pid))
    return rows


def recent(n=6):
    if not RUNS.exists():
        return []
    rows = []
    for line in RUNS.read_text().splitlines()[-200:]:
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("dry_run") or not d.get("task_id"):
            continue
        rep = d.get("worker_report") or {}
        ok = d.get("task_completed") or rep.get("status") == "DONE"
        rows.append((d.get("ended_at") or "", d.get("task_id") or "?", d.get("lane") or "?", "finished" if ok else f"stopped ({d.get('subtype') or 'error'})",
                     rep.get("tests") or "", (d.get("head_after") or "")[:7]))
    return rows[-n:]


def local(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%a %I:%M %p")
    except ValueError:
        return ts


print(f"DealSniffer workers — {time.strftime('%a %b %d %I:%M %p %Z')}\n")
now = running()
print("RUNNING NOW" if now else "RUNNING NOW: none")
for task, lane, mins, pid in now:
    print(f"  {task:<8} lane {lane} ({LANES.get(lane, '?')})  running {mins} min  [pid {pid}]")
print("\nRECENTLY ENDED (Agent 01 still reviews each one before it counts)")
for ended, task, lane, status, tests, sha in reversed(recent()):
    print(f"  {local(ended):<14} {task:<8} lane {lane}  {status}" + (f"  tests {tests}" if tests else "") + (f"  @{sha}" if sha else ""))
