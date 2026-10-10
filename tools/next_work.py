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
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import foreman  # noqa: E402

INBOX = "origin/liaison/aria-to-agent-01"
STATE = ROOT / "var" / "next_work_seen.json"
RETRY_S = 600                                   # an unclaimed, still-eligible item is announced again after this long (A-65); polling stays 120 s
AWAITING = "AWAITING the interactive engineering session"


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
    for mid, ack in inbox.items():                # actionable: no ack yet, or pickup acked it as waiting for the engineering session
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
            out.append(f"REMINDER #{rec['count']} (unclaimed since {int(now - rec['first'])}s) " + text)
        keep[key] = rec
    return out, keep


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


def cycle(baseline: bool = False, now: float | None = None) -> list[str]:
    inbox, q = current()
    if not inbox and not q:
        return []                                  # fetch/read failed: report nothing, keep the old state
    t = now if now is not None else time.time()
    if baseline:                                   # what exists now is history: never announced, never reminded
        write_state({k: {"first": t, "last": t, "count": 0, "closed": True} for k in list(inbox) + [r["id"] for r in foreman.parse_queue(q)] if k in inbox})
        return []
    lines, seen = new_items(inbox, q, read_state(), engineering_state(), t)
    write_state(seen)
    return lines


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--baseline", action="store_true")
    ap.add_argument("--watch", type=int, metavar="SECONDS")
    a = ap.parse_args(argv)
    if a.watch:
        while True:
            for line in cycle():
                print(line, flush=True)
            time.sleep(max(60, a.watch))
    for line in cycle(a.baseline):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
