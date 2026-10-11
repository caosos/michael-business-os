"""Completion-to-next-task path for the interactive Agent 01 session (A-63 delivery gap). READ-ONLY: `git fetch`, then prints ONE line per NEW
item: an instruction in the liaison inbox, or a READY queue row that is Agent 01's with its dependencies met. It sends, installs and starts nothing.

    .venv/bin/python -I tools/next_work.py --once [--baseline]     print new items and exit (--baseline: record what exists, print nothing)
    .venv/bin/python -I tools/next_work.py --watch 120             loop; each stdout line wakes a session that watches it with the Monitor tool

Why: GitHub pickup ACKs and queues docs rows, but an interactive Claude session only runs when something enters its prompt. The session registry shows
this session as cwd=/home/michaelos, entrypoint=cli, tmux=None, so the watchdog's registry match (cwd under the worktree) finds no session and its tmux
wake has no pane to type into (and is owner-disabled). A session-local Monitor on this script is the supported in-session wake: the line comes back
to the same session as a notification, with no new watchdog, credential, permission or tmux typing.
"""

from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import foreman  # noqa: E402
import pause  # noqa: E402

INBOX = "origin/liaison/aria-to-agent-01"
STATE = ROOT / "var" / "next_work_seen.json"
SLA_S = 300                                     # A-68: an eligible item must reach the session (or a worker) within this many seconds
RETRY_S = 300                                   # an unclaimed, still-eligible item is announced again after this long (A-65, tightened by A-68)
POLL_S, POLL_MAX_S = 120, 240                   # default poll; never above POLL_MAX_S, so first announcement latency stays under SLA_S with margin for the fetch
LOG = ROOT / "var" / "next_work_log.jsonl"
ARM_LOG = ROOT / "var" / "next_work_arm.jsonl"   # A-69: one ARM line when a watch starts, one EXIT line when it ends (Monitor expiry sends SIGTERM)
WATCH_LOCK = ROOT / "var" / "next_work_watch.pid"
MAX_GAP_S = 300                                  # A-69: the feed may never be dark longer than this between an EXIT and the next ARM
AWAITING = "AWAITING the interactive engineering session"
ID_RE = re.compile(r"^(ARIA|ARYA|DA)-(\d{8})-(\d{4})-")
CUTOFF = "20261010-0000"                         # same history cutoff as pickup: older or oddly named ids are never announced


def mine(row: dict) -> bool:
    a = (row.get("agent") or "").lower()
    return a.startswith("01") or "side-worktree" in a


def claimed(eng: dict, key: str) -> bool:
    """Claimed = the engineering session recorded a START (or DONE) for it. Observed/notified is NOT claimed."""
    return (eng.get(key) or {}).get("state") in ("STARTED", "DONE")


def new_items(inbox: dict, queue_text: str, seen: dict, eng: dict, now: float, retry_s: float = RETRY_S) -> tuple[list[str], dict]:
    """Pure. `inbox` = {message_id: ack_stage_text or None}. An item is announced when it was never announced, or (still unclaimed and still eligible) again after
    `retry_s`, as a REMINDER. A claimed (STARTED/DONE) item is never announced; an item that stops being eligible is forgotten; a `closed` baseline entry never
    comes back. Returns (lines, new seen) where seen = {key: {"first","last","count","closed"}}."""
    rows = foreman.parse_queue(queue_text)
    ready = {r["id"]: r for r in rows if re.match(r"READY", r["status"]) and mine(r) and foreman.deps_met(r, rows, set())}
    want = {}
    for mid, ack in inbox.items():
        m = ID_RE.match(mid)
        if not m or f"{m.group(2)}-{m.group(3)}" < CUTOFF:
            continue                              # history, never actionable (the first A-65 run announced 26 of these: fixed)
        # actionable: no ack yet, or pickup acked it as waiting for the engineering session
        if ack is None or AWAITING in ack:
            want[mid] = f"INSTRUCTION {mid}"
    for tid, r in ready.items():
        want[tid] = f"READY ROW {tid} ({r['pri']}): {r['title'][:70]}"
    out, keep = [], {}
    for key, text in sorted(want.items()):
        rec = dict(seen.get(key) or {})
        if rec.get("closed") or claimed(eng, key):
            if rec.get("closed"):
                keep[key] = rec
            continue
        if not rec:
            out.append("NEW " + text)
            rec = {"first": now, "last": now, "count": 1}
        elif now - rec.get("last", 0) >= retry_s:
            rec["count"] = rec.get("count", 1) + 1
            rec["last"] = now
            out.append(f"REMINDER #{rec['count']} (unclaimed since {int(now - rec['first'])}s" + (f"; SLA {SLA_S}s exceeded" if now - rec["first"] >= SLA_S else "") + ") " + text)
        keep[key] = rec
    return out, keep


def log_events(lines: list[str], old: dict, seen: dict, now: float) -> None:
    """Append one JSON line per announcement with its eligibility-to-announcement latency (live proof material for the 300 s SLA). Never raises."""
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, "a") as fh:
            for line in lines:
                key = next((k for k in seen if k in line), None)
                first = (seen.get(key) or {}).get("first", now)
                fh.write(json.dumps({"at": now, "key": key, "kind": line.split()[0], "since_first_seen_s": round(now - first, 1), "within_sla": (now - first) < SLA_S or line.startswith("NEW")}) + "\n")
    except OSError:
        pass


def renotify(key: str) -> None:
    """Called by a completion: the next eligible item becomes announceable on the very next cycle (retry on completion)."""
    d = read_state()
    d.pop(key, None)
    write_state(d)


def read_state() -> dict:
    try:
        d = json.loads(STATE.read_text())
        return d if isinstance(d, dict) and "inbox" not in d else {}          # the earlier one-shot format is discarded
    except (OSError, ValueError):
        return {}


def write_state(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(d))


def current() -> tuple[dict, str]:
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=ROOT, capture_output=True, timeout=120)
    ls = subprocess.run(["git", "ls-tree", "--name-only", INBOX, "docs/messages/inbox/"], cwd=ROOT, capture_output=True, text=True)
    ids = sorted(Path(x).stem for x in ls.stdout.split() if x.endswith(".md")) if ls.returncode == 0 else []
    inbox = {}
    for i in ids:
        r = subprocess.run(["git", "show", f"origin/{foreman.COORD}:docs/messages/acks/{i}.md"], cwd=ROOT, capture_output=True, text=True)
        m = re.search(r"\*\*Stage:\*\*\s*([^\n]*)", r.stdout) if r.returncode == 0 else None
        inbox[i] = m.group(1) if m else None
    return inbox, foreman.show(ROOT, foreman.COORD, "docs/status/READY_QUEUE.md") or ""


def engineering_state() -> dict:
    try:
        return json.loads((ROOT / "var" / "engineering_state.json").read_text())
    except (OSError, ValueError):
        return {}


def blocked_reason() -> str | None:
    """Eligibility also needs no owner pause and no quota block (A-68). None = clear. Unknown quota reading counts as clear (as the watchdog does)."""
    why = pause.reason()
    if why:
        return "owner pause: " + why[:80]
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from mbos import router, telemetry
        g = telemetry.quota_guard(router.load_policy())
        return None if g["allow"] else "quota guard: " + str(g.get("reason", "blocked"))[:80]
    except Exception:  # noqa: BLE001
        return None


def cycle(baseline: bool = False, now: float | None = None, blocked: str | None = None) -> list[str]:
    inbox, q = current()
    if not inbox and not q:
        return []                                  # fetch/read failed: report nothing, keep the old state
    t = now if now is not None else time.time()
    why = blocked if blocked is not None else (None if baseline else blocked_reason())
    if why and not baseline:
        return []                                  # paused / quota-blocked: not eligible, no timer runs, nothing is announced
    if baseline:                                   # what exists now is history: never announced, never reminded
        write_state({k: {"first": t, "last": t, "count": 0, "closed": True} for k in list(inbox) + [r["id"] for r in foreman.parse_queue(q)] if k in inbox})
        return []
    old = read_state()
    lines, seen = new_items(inbox, q, old, engineering_state(), t)
    write_state(seen)
    log_events(lines, old, seen, t)
    return lines


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            return b"next_work" in f.read()                      # a recycled pid that is not this tool is not a watcher
    except OSError:
        return False


def arm_log(kind: str, now: float | None = None, path: Path | None = None, **extra) -> None:
    t = now if now is not None else time.time()
    rec = {"at": t, "host_time": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(t)), "kind": kind, "pid": os.getpid(), **extra}
    p = path or ARM_LOG
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def acquire_watch(lock: Path | None = None, pid: int | None = None) -> int | None:
    """None = this process now holds the single watch lock; otherwise the pid of the live watcher that already holds it (duplicate suppressed)."""
    lock = lock or WATCH_LOCK
    me = pid or os.getpid()
    try:
        other = int(lock.read_text().strip())
        if other != me and _alive(other):
            return other
    except (OSError, ValueError):
        pass                                                     # no lock, unreadable lock, or a stale one: take it
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(str(me))
    return None


def release_watch(lock: Path | None = None, pid: int | None = None) -> None:
    lock = lock or WATCH_LOCK
    try:
        if int(lock.read_text().strip()) == (pid or os.getpid()):
            lock.unlink()
    except (OSError, ValueError):
        pass


def max_gap(entries: list[dict]) -> float:
    """Longest dark period: from an EXIT to the next ARM. 0 when there is no gap to measure."""
    gap, last_end = 0.0, None
    for e in sorted(entries, key=lambda x: x["at"]):
        if e["kind"] == "ARM":
            if last_end is not None:
                gap = max(gap, e["at"] - last_end)
            last_end = None
        elif e["kind"] == "EXIT":
            last_end = e["at"]
    return gap


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--watch", type=int, metavar="SECONDS")
    a = ap.parse_args(argv)
    if a.watch:
        other = acquire_watch()
        if other is not None:                                    # A-69: one feed only; a second arm exits quietly instead of double-announcing
            arm_log("DUPLICATE_SUPPRESSED", holder=other)
            print(f"next_work watch already running (pid {other}); this duplicate exits", file=sys.stderr)
            return 0
        arm_log("ARM", interval=a.watch)
        atexit.register(lambda: (arm_log("EXIT"), release_watch()))
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))    # Monitor expiry / TaskStop ends us: run the atexit EXIT line
        while True:
            for line in cycle():
                print(line, flush=True)
            time.sleep(max(60, min(a.watch, POLL_MAX_S)))
    for line in cycle(a.baseline):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
