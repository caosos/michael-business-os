"""Read-only foreman / idle-agent detector (A-22, Aria 1905).

    .venv/bin/python -I tools/foreman.py [--no-fetch] [--wake-text] [--repo PATH]

Reads each lane's AGENT_STATUS.md and the coordinator READY_QUEUE.md straight from git refs.
Exit 0: nobody idle with work.  Exit 2: at least one agent is idle/WAITING while READY work exists for it.
It sends nothing and starts nothing; scheduling it (cron/systemd) and waking sessions is an owner action
(docs/status/OWNER_ACTIONS.md D2). The only network call is `git fetch` (disable with --no-fetch).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COORD = "research/agent-01-coordinator"
LANES = {"02": "research/agent-02-opportunity", "03": "research/agent-03-economics", "04": "research/agent-04-state",
         "05": "research/agent-05-governance", "06": "research/agent-06-communications", "07": "research/agent-07-marketing"}
IDLE_STATES = {"WAITING", "IDLE", "COMPLETE", "CLOSED", ""}  # CLOSED = lane handed off; a fresh worker is due when READY work exists


def git(repo: Path, *args: str) -> str | None:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def show(repo: Path, branch: str, path: str) -> str | None:
    return git(repo, "show", f"origin/{branch}:{path}")


def parse_status(text: str | None) -> dict:
    out = {"state": "", "claimed": "", "done": set(), "blocked": ""}
    for line in (text or "").splitlines():
        m = re.match(r"^(State|Claimed|Blocked):\s*(.*)$", line)
        if m:
            key = m.group(1).lower()
            out["state" if key == "state" else key] = m.group(2).strip()
        elif line.startswith("Done:"):
            out["done"].update(re.findall(r"\b([A-GX]-\d+)\b(?=\s*[@(])", line))   # every "ID @ sha" / "ID (note)" on the line
    out["state"] = (re.match(r"[A-Z]+", out["state"]) or [""])[0] if out["state"] else ""
    c = out["claimed"]
    out["claimed"] = "" if c.startswith("(none") or c.lower() in ("none", "") else c
    return out


def parse_queue(text: str | None) -> list[dict]:
    """Rows of the queue. Status, agent and deps are read from the RIGHT-hand end of the row (a row with a missing or extra column, or a pipe inside the
    title, must not make a READY task invisible: found when an executor wrote F-56 one column short)."""
    rows = []
    for line in (text or "").splitlines():
        c = [x.strip() for x in line.split("|")]
        if len(c) >= 8 and re.fullmatch(r"[A-GX]-\d+", c[1]):
            pri = re.search(r"P\d", c[2])
            rows.append({"id": c[1], "pri": pri.group(0) if pri else "P9", "status": re.sub(r"[*`]", "", c[-4]).strip(),
                         "agent": re.sub(r"[*]", "", c[-3]).strip(), "deps": c[-5], "title": (c[3] if len(c) >= 9 else c[2])[:90]})
    return rows


STATUS_WORDS = ("READY", "CLAIMED", "BLOCKED", "DONE", "HOLD", "PARKED", "RESUMING", "RESUMED", "NEEDS", "PAUSED", "SUPERSEDED", "OWNER", "SPLIT", "PARTIAL")


def schema_problems(text: str | None) -> list[str]:
    """Rows that look like tasks (`| X-nn |`) but break the 7-column schema (ID | Pri | Task | Deps | Status | Agent | Acceptance): reported, never silently skipped."""
    out = []
    for line in (text or "").splitlines():
        if not re.match(r"\|\s*[A-GX]-\d+\s*\|", line):
            continue
        c = [x.strip() for x in line.split("|")]
        tid = c[1]
        status = re.sub(r"[*`]", "", c[-4]).strip()
        if len(c) < 9:
            out.append(f"{tid}: {len(c) - 2} columns, expected 7 (a cell is missing or fused; status may be read from the wrong cell)")
        elif not re.search(r"P\d", c[2]):
            out.append(f"{tid}: priority cell {c[2][:20]!r} has no P0..P3")
        elif not any(status.upper().startswith(w) for w in STATUS_WORDS):
            out.append(f"{tid}: status cell {status[:30]!r} is not a known status")
    return out


def deps_met(row: dict, rows: list[dict], done: set[str]) -> bool:
    """Every task id named in the row's deps must be DONE (lane's word or the queue row). Ids not in the queue at all count as met; text without ids ('none') too."""
    status = {r["id"]: r["status"] for r in rows}
    for d in re.findall(r"[A-GX]-\d+", row.get("deps") or ""):
        if d in status and d not in done and not status[d].upper().startswith("DONE"):
            return False
    return True


def ready_for(rows: list[dict], lane: str, done: set[str]) -> list[dict]:
    mine = [r for r in rows if lane in re.findall(r"\d\d", r["agent"]) and re.match(r"READY", r["status"]) and r["id"] not in done and deps_met(r, rows, done)]
    return sorted(mine, key=lambda r: (not r["pri"].startswith("P0"), r["pri"], r["id"]))


def done_by_lane(repo: Path) -> dict[str, set[str]]:
    """Task ids each lane's own AGENT_STATUS lists as Done (the lane's word, pushed)."""
    out = {}
    for lane, branch in LANES.items():
        out[lane] = parse_status(show(repo, branch, "docs/status/AGENT_STATUS.md"))["done"]
    return out


def reconcile(queue_text: str, done: dict[str, set[str]], heads: dict[str, str]) -> tuple[str, list[str]]:
    """Mark queue rows DONE when the owning lane lists the id under Done, and refresh the recorded heads line. Never edits a row
    that is not READY/CLAIMED/BLOCKED, and never marks DONE on anyone's word but the owning lane's. Returns (new_text, changes)."""
    changes, out = [], []
    for line in queue_text.splitlines():
        c = line.split("|")
        if len(c) >= 8 and re.fullmatch(r"\s*[A-GX]-\d+\s*", c[1]):
            tid, status = c[1].strip(), re.sub(r"[*`]", "", c[5]).strip()
            lanes = re.findall(r"\d\d", re.sub(r"\*", "", c[6]))
            if re.match(r"(READY|CLAIMED|BLOCKED)", status) and lanes and all(tid in done.get(l, set()) for l in lanes if l in done) \
                    and any(l in done for l in lanes):
                c[5] = f" **DONE** (reconciled from lane {','.join(lanes)} AGENT_STATUS Done) "
                changes.append(f"{tid}: {status[:30]} -> DONE")
                line = "|".join(c)
        out.append(line)
    text = "\n".join(out) + ("\n" if queue_text.endswith("\n") else "")
    hs = " · ".join(f"{l} `{h}`" for l, h in heads.items())
    text = re.sub(r"- \*\*Last synced:\*\*.*", f"- **Last synced:** reconciled by tools/foreman.py against heads {hs}.", text, count=1)
    return text, changes


def survey(repo: Path) -> tuple[list[dict], list[str]]:
    queue_text = show(repo, COORD, "docs/status/READY_QUEUE.md")
    rows = parse_queue(queue_text)
    warnings = [f"queue schema: {p}" for p in schema_problems(queue_text)]
    if queue_text is None:
        warnings.append("cannot read READY_QUEUE from origin/" + COORD)
    m = re.search(r"Last synced:.*", queue_text or "")
    report = []
    for lane, branch in LANES.items():
        st = parse_status(show(repo, branch, "docs/status/AGENT_STATUS.md"))
        head = (git(repo, "log", "-1", "--format=%h", f"origin/{branch}") or "?").strip()
        if m and head != "?" and head not in m.group(0):
            warnings.append(f"queue stale for {lane}: recorded heads do not include origin {head}")
        ready = ready_for(rows, lane, st["done"])
        busy = bool(st["claimed"]) and st["state"] == "WORKING"
        idle = (not busy) and st["state"] in IDLE_STATES or (st["state"] == "WORKING" and not st["claimed"] and bool(ready))
        report.append({"lane": lane, "state": st["state"] or "?", "claimed": st["claimed"], "head": head, "ready": ready,
                       "idle_with_work": bool(idle and ready), "blocked": st["blocked"]})
    return report, warnings


def launch_commands(idle: list[dict]) -> list[list[str]]:
    """`tools/worker.py` commands for idle lanes (never lane 01: the persistent coordinator picks its own work). The worker itself
    refuses a lane that still has a live session or a dirty worktree."""
    return [[sys.executable, "-I", "tools/worker.py", r["ready"][0]["id"], "--lane", r["lane"]] for r in idle if r["lane"] != "01"]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(ROOT))
    ap.add_argument("--no-fetch", action="store_true")
    ap.add_argument("--wake-text", action="store_true")
    ap.add_argument("--reconcile", action="store_true", help="rewrite READY_QUEUE.md rows to DONE per each lane's own Done lines and refresh heads")
    ap.add_argument("--launch", action="store_true", help="print the exact tools/worker.py command for each idle lane's top READY task")
    ap.add_argument("--exec", type=int, default=0, metavar="N", help="with --launch: actually run at most N workers (max 2) sequentially")
    a = ap.parse_args(argv)
    repo = Path(a.repo)
    if not a.no_fetch:
        git(repo, "fetch", "-q", "origin")
    if a.reconcile:
        qp = repo / "docs" / "status" / "READY_QUEUE.md"
        heads = {l: (git(repo, "log", "-1", "--format=%h", f"origin/{b}") or "?").strip() for l, b in LANES.items()}
        new, changes = reconcile(qp.read_text(), done_by_lane(repo), heads)
        qp.write_text(new)
        print(f"reconciled {len(changes)} row(s)" + ("".join("\n  " + c for c in changes)))
        return 0
    report, warnings = survey(repo)
    for r in report:
        nxt = ", ".join(f"{t['id']}({t['pri']})" for t in r["ready"][:3]) or "-"
        flag = "  <-- IDLE WITH READY WORK" if r["idle_with_work"] else ""
        print(f"{r['lane']}  {r['state']:<8} {r['head']:<8} claimed={r['claimed'][:40] or '-':<40} ready={nxt}{flag}")
    for w in warnings:
        print("WARN", w)
    idle = [r for r in report if r["idle_with_work"]]
    if a.wake_text:
        for r in idle:
            t = r["ready"][0]
            print(f"WAKE {r['lane']}: Fetch origin, read docs/status/READY_QUEUE.md on research/agent-01-coordinator, claim {t['id']} "
                  f"({t['title']}), push the claim, work it DRY-RUN only, push, then claim the next READY task.")
    if a.launch:
        cmds = launch_commands(idle)
        for c in cmds:
            print("LAUNCH", " ".join(c))
        if a.exec:
            if warnings:
                print("REFUSING --exec: the queue is stale (see WARN); refresh READY_QUEUE first")
                return 3
            for c in cmds[:min(a.exec, 2)]:
                subprocess.run(c, cwd=repo)
    return 2 if idle else 0


if __name__ == "__main__":
    sys.exit(main())
