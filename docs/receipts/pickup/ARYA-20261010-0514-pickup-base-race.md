# Pickup receipt: ARYA-20261010-0514-pickup-base-race

- Stage: COMPLETED as coordination (the fix was already delivered by the owner code path in `03d0e1e`; this run verified it, reconciled F-53, and changed no code, restart, spend, contact or other projects)
- Source: `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARYA-20261010-0514-pickup-base-race.md`

## Provenance finding (read-only, confirmed)
- `git diff --stat ecd9638 c7ca90b -- . ':!docs'` is empty. The 0512 pickup child `c7ca90b` changed only three docs files (ACK, receipt, READY_QUEUE F-53 row) versus its parent `ecd9638`. The child never touched code.
- The coordinator advanced concurrently with A-52 code (`4ca13ac`, `e693ae`, `afc8fed`). The old `pickup_git.changed_files` diffed against the moving `origin/research/agent-01-coordinator`, so upstream code showed up as the executor's change. The race hypothesis is confirmed.

## Fix (already on the coordinator branch, `03d0e1e`, owner code path)
- `tools/pickup_git.changed_files` now diffs against `git merge-base HEAD origin/<coordinator>` (the fork point), plus uncommitted and untracked files. Upstream pushes made after the run started are not counted. The docs-only policy is unchanged and strict. The guard was not relaxed or bypassed.
- `publish` rebases with its own identity and reports git's actual reason when the rebase fails.

## Tests
- `tests/unit/test_inbox_pickup.py`: 12 passed in 5.16s (run with `../agent-01-coordinator/.venv`).
- `test_docs_guard_ignores_code_pushed_by_others_after_the_run_started`: another clone pushes `tools/new_code.py` mid-run. The run still reaches COMPLETED, the upstream code survives the rebase, and the docs land.
- `test_inbox_pickup.py:145-157`: a child that writes `tools/evil.py` is BLOCKED with a "non-docs" reason and the file never reaches the coordinator branch. Real child code still blocks.

## Reconciliation
- F-53 is now on the authoritative `origin/research/agent-01-coordinator` READY_QUEUE.md (row 373, status READY, lane 06, code lane). It is queued, not scheduled or started. It is not claimed done.
- 0512 publication: it was published as `c7ca90b` (receipt present at `docs/receipts/pickup/ARYA-20261010-0512-f52-acceptance-gaps.md`). No duplicate executor or task was started.
- F-52 acceptance and the live gate are unchanged.

## Remaining
- None for this task. No code, owner decision or new queue row needed.
