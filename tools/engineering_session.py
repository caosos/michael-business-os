"""Engineering-session side of the delivery route (A-63): idempotent START / DONE for an instruction, with the next eligible task advanced once.

    .venv/bin/python -I tools/engineering_session.py begin  MESSAGE_OR_TASK_ID     RUN | RESUME | DUPLICATE_IGNORED, writes the START receipt
    .venv/bin/python -I tools/engineering_session.py finish MESSAGE_OR_TASK_ID --note TEXT   DONE + the next eligible approved task (once)
    .venv/bin/python -I tools/engineering_session.py status

State: var/engineering_state.json (local, atomic). Receipts: docs/receipts/engineering/<ID>.md (docs only; pushing is the caller's explicit step). The
receipt records WHO ran it (the interactive Claude session pid/entrypoint from ~/.claude/sessions, never pickup), so a docs-only pickup completion cannot
pass for engineering execution. Read-only otherwise: starts nothing, sends nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import foreman  # noqa: E402

STATE = Path(os.environ.get("MBOS_ENGINEERING_STATE") or ROOT / "var" / "engineering_state.json")
RECEIPTS = Path(os.environ.get("MBOS_ENGINEERING_RECEIPTS") or ROOT / "docs" / "receipts" / "engineering")
SESSIONS = Path(os.environ.get("MBOS_CLAUDE_SESSIONS") or Path.home() / ".claude" / "sessions")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (OSError, ValueError):
        return {}


def save(d: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=STATE.parent)
    with os.fdopen(fd, "w") as fh:
        json.dump(d, fh, indent=1, sort_keys=True)
    os.replace(tmp, STATE)


def ancestors(pid: int) -> list[int]:
    out = []
    while pid > 1:
        out.append(pid)
        try:
            pid = int(Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
    return out


def session_identity() -> dict:
    """The interactive Claude session this process runs under (registry entry whose pid is an ancestor), else an honest 'unknown'."""
    chain = set(ancestors(os.getpid()))
    for p in SESSIONS.glob("*.json"):
        try:
            d = json.loads(p.read_text())
        except (OSError, ValueError):
            continue
        if d.get("pid") in chain:
            return {"pid": d["pid"], "entrypoint": d.get("entrypoint"), "kind": d.get("kind"), "cwd": d.get("cwd"), "tmux": d.get("tmux")}
    return {"pid": None, "entrypoint": "unknown", "kind": "not under a registered Claude session"}


def receipt_path(tid: str) -> Path:
    return RECEIPTS / (re.sub(r"[^A-Za-z0-9_.-]", "_", tid) + ".md")


def begin(tid: str, ident: dict | None = None) -> str:
    d = load()
    rec = d.get(tid)
    if rec and rec["state"] == "DONE":
        return "DUPLICATE_IGNORED"                         # a second delivery of a finished instruction executes nothing
    ident = ident or session_identity()
    if rec and rec["state"] == "STARTED":
        holder = (rec.get("session") or {}).get("pid")
        if holder and holder != ident.get("pid") and pid_alive(holder):
            return "ACTIVE_CLAIM"                          # another LIVE session holds it: never run it twice or interrupt it
        # re-entry / restart while unfinished (same session, or the holder is gone): resume the same record, never a second START
        rec["session"] = ident
        rec["resumes"] = rec.get("resumes", 0) + 1
        rec["last_resume_at"] = now()
        save(d)
        return "RESUME"
    d[tid] = {"state": "STARTED", "started_at": now(), "session": ident, "resumes": 0}
    save(d)
    p = receipt_path(tid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"# Engineering receipt: {tid}\n\n## START {d[tid]['started_at']}\n- Executed by the interactive engineering session: pid {ident.get('pid')}, entrypoint {ident.get('entrypoint')}, "
                 f"kind {ident.get('kind')}. This is not the pickup watcher.\n")
    return "RUN"


def pid_alive(pid) -> bool:
    try:
        os.kill(int(pid), 0)
        return True
    except (TypeError, ValueError, OSError):
        return False


def next_eligible(queue_text: str, extra_done: set[str] = frozenset()) -> dict | None:
    rows = foreman.parse_queue(queue_text)
    done = {r["id"] for r in rows if r["status"].upper().startswith("DONE")} | set(extra_done)
    mine = [r for r in rows if re.match(r"READY", r["status"]) and r["id"] not in done and foreman.deps_met(r, rows, done)
            and (r["agent"].lower().startswith("01") or "side-worktree" in r["agent"].lower())]
    mine.sort(key=lambda r: (not r["pri"].startswith("P0"), r["pri"], r["id"]))
    return mine[0] if mine else None


def finish(tid: str, queue_text: str, note: str = "") -> dict:
    d = load()
    rec = d.get(tid)
    if not rec:
        raise SystemExit(f"{tid} was never started: run `begin` first")
    if rec["state"] == "DONE":                              # completion is idempotent: the same next task is reported, nothing advances twice
        return {"state": "DONE", "already_done": True, "next": rec.get("next")}
    nxt = next_eligible(queue_text, {tid})
    rec.update(state="DONE", done_at=now(), note=note, next=({"id": nxt["id"], "pri": nxt["pri"], "title": nxt["title"]} if nxt else None))
    save(d)
    if nxt:                                                  # completion hands control back to the session loop: the next item is announced on the next cycle
        try:
            import next_work
            next_work.renotify(nxt["id"])
        except Exception:  # noqa: BLE001  (the receipt and state above are the truth; a missing feed must not fail a completion)
            pass
    with open(receipt_path(tid), "a") as fh:
        fh.write(f"\n## DONE {rec['done_at']}\n- Result: {note or '(no note)'}\n- Next eligible approved task (deps met, Done history honoured): "
                 f"{(nxt['id'] + ' ' + nxt['title']) if nxt else 'none'}\n")
    return {"state": "DONE", "already_done": False, "next": rec["next"]}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=("begin", "finish", "status"))
    ap.add_argument("task_id", nargs="?")
    ap.add_argument("--note", default="")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps(load(), indent=1))
    elif a.cmd == "begin":
        print(begin(a.task_id))
    else:
        out = finish(a.task_id, foreman.show(ROOT, foreman.COORD, "docs/status/READY_QUEUE.md") or "", a.note)
        print(json.dumps(out))
        n = out.get("next")
        print(f"CONTROL RETURNS TO THE SESSION LOOP: next eligible approved task is {n['id']}: run `begin {n['id']}` (the feed announces it on its next cycle)" if n
              else "CONTROL RETURNS TO THE SESSION LOOP: no eligible approved task (every READY row is blocked, owned by another lane, or waiting on a dependency)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
