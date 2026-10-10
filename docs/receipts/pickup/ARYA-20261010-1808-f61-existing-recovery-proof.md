# Receipt: ARYA-20261010-1808-f61-existing-recovery-proof (docs-only pickup, dry-run)

## Runtime finding (read-only; FACT)
- F-61 is ALREADY RUNNING. Preserved; no launch, restart or interruption by this pickup.
  - Dispatcher `tools/dispatcher.py` PID 3942566 (bash wrapper 3942564, tee 3942567), started 2026-10-10 13:05:39 CDT (18:05:39Z) from worktree `agent-01-coordinator`.
  - Worker PID 3942594 (child of dispatcher): `tools/worker.py F-61 --lane 06 --kind implement --risk medium --max-turns 80 --timeout 3500`, started 13:05:40 CDT. Log: `var/worker-F-61.out` (agent-01-coordinator worktree). Lane 06 worktree: `agent-06-communications`, branch `research/agent-06-communications` at 9590ae5.
  - `var/dispatcher.jsonl`: 18:05:40Z `launch` lane 06 task F-61 (dry=false); 18:07:11Z and 18:08:42Z `idle` with running=["06"]. Earlier: 17:58:37Z `stop` ("no READY work", F-60 finished) .
  - Quota at launch: "session 17.0% / week 17.0% are under the limits".
  - Queue warning at launch (pre-existing, not blocking): unknown status cells for B-13, A-21, X-03 rows; "queue stale for 06: recorded heads do not include origin 9590ae5".
- Restart mechanism (existing): the watchdog `tools/coordinator_watch.py --serve-port 8479 --interval 120` (PID 2491363, started Oct 8 23:16, wrapper 2491361) runs dispatcher_action/start_dispatcher on its 120 s cycle with a 600 s restart guard. It brought the dispatcher back at 13:05:39, ~26 s after the c35e0c7 queue repair was committed (13:05:13). No interactive coordinator wake was needed. Watchdog status.json (generated 18:07:41Z) shows coordinator_head c35e0c7. Receipt: `docs/receipts/2026-10-10-dispatcher-adoption-observed.md` (agent-01-coordinator worktree). Note: the watchdog process predates the repair, so it adopted the queue by reading the repo, not by restarting itself.
- The 127.0.0.1:8479 health endpoint was not queried (curl was blocked in this sandbox); status.json file was used instead.

## Queue
- F-60 DONE and F-61 READY (dispatcher is running it; row left as-is, dispatcher/worker own its status change). No duplicate launch.

## Regression protection (NOT done here)
- Needs code and tests, which docs-only pickup may not do. Handed off as READY_QUEUE row **A-57** (lane 01 code): fail-closed queue-merge check, concrete replay of the 9435d68 stale-side merge (it took the remote side of READY_QUEUE.md, dropping newer F-60/F-61 rows and reverting F-60), plus a legitimate explicit reopen/cancel that stays attributable.
- Root cause (INFER from commit message "took remote side for files I did not edit"): merge resolved the whole queue file to one side instead of merging row-by-row.

## Tests
- None run (docs only). Source/test evidence for A-57: UNK until that lane delivers.

## Remaining
- F-61 completion/verification: owned by lane 06 and its worker; check `var/worker-F-61.out` and dispatcher.jsonl for exit.
- A-57 code work: unowned until a code lane picks it up. No owner decision needed. No handoff mechanism to an interactive engineering coordinator was used; A-57 in the queue is the supported route.
