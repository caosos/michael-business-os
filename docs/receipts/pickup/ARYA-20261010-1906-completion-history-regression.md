# Pickup receipt: ARYA-20261010-1906-completion-history-regression

Docs-only, dry-run. No code, restart, live reload, fetch, bid, spend or contact.

## Findings (FACT)
- `origin/research/agent-06-communications` lane06 `docs/status/AGENT_STATUS.md` Done line currently reads only `F-61 @ e54e27a ...; F-138 @ 22bb3ab`. The historical entries present at `eda3eee` (F-137 @ d537b27, F-136 @ 48d27b9, F-60 @ 64b152b, F-59 ... F-01, P-06-12) are missing. Cause: 22bb3ab overwrote the whole line.
- SHAs e54e27a, 48d27b9, d537b27, 22bb3ab, eda3eee, 0e30a92 are all ancestors of the lane06 branch (verified with `git merge-base --is-ancestor`).
- Coordinator `docs/status/READY_QUEUE.md` had F-61, F-136, F-137, F-138 as READY (the re-dispatch risk). F-60 was already DONE; A-57 is READY (owner 01).
- Process check: no lane-06 worker or dispatcher process found on this host (`ps`); only `mbos-foreman-watch` is running. No duplicate launch found, so there is nothing to dispose of and no process was killed.

## Done here (data reconciliation)
- READY_QUEUE.md rows F-61 (e54e27a), F-136 (48d27b9), F-137 (d537b27), F-138 (22bb3ab) changed READY -> DONE. Row text, owner dependencies, F-60 DONE and the A-57 READY row are untouched (4 lines changed).
- Check after the edit: the status column of every row among F-60/61/136/137/138 is DONE, and only A-57 is READY. (Not a live foreman run; I did not run the foreman.)

## Remaining (owner decisions / other lanes)
1. **Lane 06 status restore (owning lane, not this pickup):** restore the Done line from `eda3eee` plus F-138 @ 22bb3ab, keeping newer unrelated status. Until then, the queue DONE rows are what stops re-execution. I did not edit the lane worktree.
2. **A-57 (code, owning engineering session, NOT done):** extend its scope with this regression, "a status writer must merge into the Done line, not replace it", with a test using 22bb3ab vs eda3eee. This is a new READY_QUEUE note request; the A-57 row is unchanged here to preserve latest owner text.
3. After lane 06 restores its Done line, a foreman eligibility run (read-only listing) should confirm no completed ID is eligible. I could not verify that live.

No tests run (docs-only).
