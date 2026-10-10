# Pickup receipt: ARYA-20261010-2208-a60-parsed-dependency

Docs-only, dry-run. No code, restart, spend, bid, contact or other-project change.

## What was done
- The correction was already applied in e80ae98: A-60's Deps cell in `docs/status/READY_QUEUE.md` is exactly `A-50`. The "A-59 item 3 is non-blocking" explanation sits in the task text ("Dependency note (ARYA-20261010-2208)"), outside Deps.
- A-59 remains PARTIAL. Its lane06 history-write denial is intact. History is NOT claimed restored. No tasks were rerun.

## Parser recheck (real `tools/foreman.py`, run on the current queue)
- A-60 deps cell: `'A-50'`. `re.findall(r"[A-GX]-\d+")` gives `['A-50']`. A-59 is no longer extracted.
- A-50 status is DONE. A-59 status is PARTIAL.
- `deps_met(A-60) = True`. `ready_for(rows, '01', set())` includes A-60 (status READY, agent `01 engineering`).
- Result: A-60 is parser-eligible. That means eligible to be picked by the foreman for lane 01. It does not mean A-60 is started or done.

## Remaining blockers / notes
- A-60 changes lane 06 `operator_ui`; the implementer needs authorization to write that branch. This is noted in the A-60 row.
- Monitor facts remain BLOCKED awaiting engineering evidence. No operational query was repeated.
