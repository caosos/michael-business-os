"""Fail-closed guard for docs/status/READY_QUEUE.md merges (A-57).

Root cause it prevents (9435d68): a stale-side merge resolved the whole queue file to one side, silently dropping newer rows (F-60/F-61) and moving
F-60 from DONE back to READY. check() compares a merge RESULT with each PARENT row by row and returns the problems; an empty list means safe.

A row may only disappear, leave DONE, or lose its deps/owner with an attributable marker: a dict with task, actor, reason, message and action
('cancel' drops/closes a row, 'reopen' moves DONE back, 'edit' changes deps/owner). A marker missing any field is ignored.

    python tools/queue_guard.py RESULT_FILE PARENT_FILE [PARENT_FILE ...]      exit 0 safe, 1 unsafe (problems printed)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    from tools.foreman import parse_queue
except ImportError:  # run as a script
    from foreman import parse_queue

FIELDS = ("task", "actor", "reason", "message", "action")
EMPTY = {"", "none", "-", "n/a"}
_ID = re.compile(r"[A-GX]-\d+")


def _dep_ids(v: str) -> set[str]:
    return set(_ID.findall(v or ""))


def _owner_tokens(v: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", (v or "").lower())) - {"none", "n", "a"}


def _rows(text: str | None) -> dict[str, dict]:
    return {r["id"]: r for r in parse_queue(text)}


def _allowed(markers, task: str, *actions: str) -> bool:
    return any(all(str(m.get(f, "")).strip() for f in FIELDS) and m["task"] == task and m["action"] in actions for m in (markers or []))


def check(result: str | None, parents: list[str | None], markers: list[dict] | None = None) -> list[str]:
    res, problems = _rows(result), []
    for n, parent in enumerate(parents, 1):
        for tid, old in _rows(parent).items():
            new = res.get(tid)
            if new is None:
                if not _allowed(markers, tid, "cancel"):
                    problems.append(f"{tid}: present in parent {n} but dropped by the merge result")
                continue
            if old["status"].upper().startswith("DONE") and not new["status"].upper().startswith("DONE") and not _allowed(markers, tid, "reopen", "cancel"):
                problems.append(f"{tid}: DONE in parent {n} but {new['status'][:20]!r} in the result (no reopen/cancel marker)")
            if _allowed(markers, tid, "edit"):
                continue
            for key, label in (("deps", "dependencies"), ("agent", "owner")):
                if old[key].lower() not in EMPTY and new[key].lower() in EMPTY:
                    problems.append(f"{tid}: {label} {old[key][:30]!r} in parent {n} lost in the result (no edit marker)")
            lost = _dep_ids(old["deps"]) - _dep_ids(new["deps"])
            if lost and new["deps"].lower() not in EMPTY:                      # one of several dependencies dropped (formatting-only changes keep the same IDs)
                problems.append(f"{tid}: dependency {', '.join(sorted(lost))} in parent {n} dropped by the result (no edit marker)")
            ot, nt = _owner_tokens(old["agent"]), _owner_tokens(new["agent"])
            if ot and nt and not ot & nt:                                      # owner replaced by a different one ('01' -> '01 engineering' is fine)
                problems.append(f"{tid}: owner {old['agent'][:30]!r} in parent {n} replaced by {new['agent'][:30]!r} (no edit marker)")
    return sorted(set(problems))


def done_line_problems(parent: str | None, result: str | None) -> list[str]:
    """AGENT_STATUS `Done:` history (22bb3ab regression): every task ID the parent lists as Done must still be listed by the result; a status writer
    merges into the line, it never replaces it with the latest task only."""
    try:
        from tools.foreman import parse_status
    except ImportError:
        from foreman import parse_status
    lost = parse_status(parent)["done"] - parse_status(result)["done"]
    return [f"Done history lost: {', '.join(sorted(lost))}"] if lost else []


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    problems = check(Path(argv[0]).read_text(), [Path(p).read_text() for p in argv[1:]])
    for p in problems:
        print("QUEUE GUARD:", p)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
