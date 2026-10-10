# Pickup receipt: ARYA-20261010-0528-owner-pause-compute

Status: **BLOCKED** (docs side done; actual dispatch stop needs a host action). Dry-run; docs only.

## PAUSED_BY_OWNER (recorded 2026-10-10T05:29Z)
- Checkpoint SHA: `45bd2a4` (origin/research/agent-01-coordinator tip at read time; pause commit follows on this branch).
- Unfinished work: **F-53** (lane 06, 4 F-52 acceptance gaps). Uncommitted worker output may exist in the coordinator worktree; not inspected or touched.
- Queue: F-53 row set to BLOCKED/PAUSED_BY_OWNER so no relaunch; PAUSE-01 row added (host action). Code, data, receipts, queue, infrastructure preserved.

## Running dispatch (FACT, `ps` at 05:29Z; local state is NOT inferred from GitHub)
- `tools/worker.py F-53 --lane 06 --kind implement --risk high --max-turns 100 --timeout 3500`, pid 3399484, started 00:15Z, ~13 min in, running pytest. **STILL RUNNING.** Pickup cannot stop it (code/live process action, and kills must not discard uncommitted work). It ends by its 3500 s timeout (~01:14 local) at the latest.
- `tools/dispatcher.py` (tmux `mbos-dispatcher`, pid 3399447) is live and can start new workers; the queue hold is the only guard I could add.
- `tools/inbox_pickup.py` daemon (tmux `mbos-pickup`, pid 3355056) launches model executors for inbox messages (this one included); it will keep doing so until stopped.
- `mbos-foreman-watch`, `mbos-watchdog`: not inspected for model launching.

## Owner/host decision needed
1. Stop (not kill -9 mid-write) the dispatcher and the pickup daemon after F-53's worker exits or checkpoints, e.g. Ctrl-C in tmux `mbos-dispatcher` and `mbos-pickup`; or approve a code change adding a PAUSED flag checked by both (code lane, not done).
2. Let F-53's worker finish at a safe boundary; commit/keep its worktree changes.
3. Confirm foreman-watch/watchdog launch no model jobs.
4. Resume: owner message, unset the F-53 hold, restart `tools/dispatcher.py` in tmux `mbos-dispatcher` (and pickup if wanted).

## Tests
None run (docs-only; no code changed).

## Remaining blockers
Final reconciliation ("actual dispatch stopped") cannot be published until items 1-3 are done and verified by `ps`.
