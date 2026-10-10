# Receipt: ARYA-20261010-0514-pickup-base-race

Executor: Agent 01 automatic pickup, docs-only, dry-run. No code changed, no restart, no spend or contact.

## Finding (verified by reading the repo)
- The false positive was real. `tools/pickup_git.py::changed_files` diffed the worktree against the moving `origin/research/agent-01-coordinator`. Code the coordinator took during the run (A-52: 4ca13ac, e693ae, afc8fed) showed up as "changed by the executor", so the docs-only guard in `tools/inbox_pickup.py:168` blocked 0512.
- The fix is already on the coordinator branch as 03d0e1e, pushed before this instruction was picked up. `changed_files` now diffs against `git merge-base HEAD origin/<coord>`, the fork point, plus uncommitted and untracked files. Commits others push meanwhile are not counted.
- The strict policy is unchanged: any non-`docs/` path in the child's own changes still blocks (`inbox_pickup.py:168-170`, test at `tests/unit/test_inbox_pickup.py:156`).
- 03d0e1e also made the rebase use the executor's own identity and report git's reason on failure.
- The regression test is `test_docs_guard_ignores_code_pushed_by_others_after_the_run_started`. It pushes code to the coordinator branch while the executor runs. The task still ends COMPLETED, and the other agent's `tools/new_code.py` survives the rebase.

## Caveat on "immutable captured base"
The merge-base is recomputed on each call, not captured once at start. It stays correct because the worktree's own commits sit above the fork point, and a rebase only moves the fork point past commits that are already upstream. I did not change this, because that needs code. If Arya wants a literal captured base SHA, that is a code change for Agent 01's lane.

## 0512 resumption and F-53
- 0512 already published through the verified route (b8cad80). No duplicate executor or task was started.
- F-53 is now in the authoritative queue. `origin/research/agent-01-coordinator:docs/status/READY_QUEUE.md` line 373 has F-53 as a P0 row for lane 06, "NOT done by pickup", in the same file as F-52 and A-52. Its status is READY (not claimed or started), and it is scheduled only as a queue row.
- Product acceptance and the live gate are unchanged.

## Tests
- Not run. This worktree's Python has no pytest, and no other interpreter on the host has it, so I could not execute `tests/unit/test_inbox_pickup.py`. The evidence above comes from reading the diff and the tests. UNK: current pass count.

## Remaining
- Someone should run `tests/unit/test_inbox_pickup.py` where pytest is available, to confirm the fix and the regression test pass.
- Optional code task for Agent 01 if a literal captured-base SHA is wanted.
