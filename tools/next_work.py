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


def mine(row: dict) -> bool:
    a = (row.get("agent") or "").lower()
    return a.startswith("01") or "side-worktree" in a


def new_items(inbox_ids: list[str], queue_text: str, seen: dict) -> tuple[list[str], dict]:
    """Pure. -> (lines to print, new seen). An inbox id is reported once; a READY row is reported once per time it becomes READY (leaving READY forgets it)."""
    rows = foreman.parse_queue(queue_text)
    ready = {r["id"]: r for r in rows if re.match(r"READY", r["status"]) and mine(r) and foreman.deps_met(r, rows, set())}
    lines = [f"NEW INSTRUCTION {i}" for i in inbox_ids if i not in set(seen.get("inbox", []))]
    lines += [f"READY ROW {i} (P{ready[i]['pri'][-1:] or '?'}): {ready[i]['title'][:70]}" for i in sorted(ready) if i not in set(seen.get("rows", []))]
    return lines, {"inbox": sorted(set(seen.get("inbox", [])) | set(inbox_ids)), "rows": sorted(ready)}


def read_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def current() -> tuple[list[str], str]:
    subprocess.run(["git", "fetch", "-q", "origin"], cwd=ROOT, capture_output=True, timeout=120)
    ls = subprocess.run(["git", "ls-tree", "--name-only", INBOX, "docs/messages/inbox/"], cwd=ROOT, capture_output=True, text=True)
    ids = sorted(Path(x).stem for x in ls.stdout.split() if x.endswith(".md")) if ls.returncode == 0 else []
    return ids, foreman.show(ROOT, foreman.COORD, "docs/status/READY_QUEUE.md") or ""


def cycle(baseline: bool = False) -> list[str]:
    ids, q = current()
    if not ids and not q:
        return []                                  # fetch/read failed: report nothing, keep the old state
    lines, seen = new_items(ids, q, read_state())
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(seen))
    return [] if baseline else lines


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
