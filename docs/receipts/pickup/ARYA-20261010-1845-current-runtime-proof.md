# Pickup receipt: ARYA-20261010-1845-current-runtime-proof

Read-only. Observed-host facts taken at 2026-10-10T18:46Z (host clock 13:46 CDT). Repo facts from `origin/research/agent-01-coordinator` @ 568d593. No launch, restart, kill, code change, spend or other-project action.

## F-137 (observed host)
- **RUNNING, launched automatically by the existing dispatcher.** `var/dispatcher.jsonl`: `launch lane 06 task F-137` at 2026-10-10T18:42:04Z, cmd `tools/worker.py F-137 --lane 06 --kind implement --risk medium --max-turns 80 --timeout 3500`, `dry:false`. It launched about 3 min after `exit lane 06 F-136 rc 0` at 18:39:02Z.
- Process: PID 3974897 (python `tools/worker.py`), etime 04:10 at 18:46:14Z, cwd the agent-01-coordinator worktree. Dispatcher is PID 3942566 (tmux `mbos-dispatcher`, since 18:05Z).
- Dispatcher heartbeats at 18:43:35Z and 18:45:06Z report `running:["06"]`, quota session 21% / week 18% (under limits).
- Log phase: `var/worker-F-137.out` is 0 bytes at 18:46Z, so there is no phase output yet. The log is empty at 4 min, so it is not evidence of progress. Timeout 3500 s, so the earliest stall flag is about 19:40Z.
- Watchdog (`var/watchdog/status.json`, 18:46:03Z): `dispatcher_running:true`, `dispatcher_action:NONE`, `stalled_workers:[]`, `quota_allows_a_turn:true`.
- Conclusion: the 1839 receipt's "needs a future merge/manual launch" wording is superseded. The existing watchdog/dispatcher route launched F-137 as it did F-61 and F-136. No duplicate launched.
- Warnings the dispatcher logged at 18:39:02Z (not blocking): queue-schema parse warnings on rows B-13, A-21, X-03 (free text in status cells), and `queue stale for 06: recorded heads do not include origin 1182e8a`.
- Repo evidence: READY_QUEUE F-137 row (P1, lane 06) on the coordinator branch.

## A-57 (pickup-merge regression guard; coordinator-owned code)
- READY_QUEUE A-57 is P1, "CODE lane, NOT done by docs-only pickup". There is no observed execution of it.
- Route check (observed host):
  - tmux session `mbos-agent-01` does not exist (`tmux has-session` fails). Only mbos-dev-ui, mbos-dev-worker, mbos-dispatcher, mbos-pickup and mbos-watchdog exist.
  - The watchdog reports Agent 01 `state: STOPPED`, `session: null`, `decision: no live Claude session (awaiting connection)`. `last_wake` is null.
  - `var/watchdog/mode.json` is `{"wake": false}`. Tmux self-wake is off by the owner/classifier decision of 2026-10-09, and I did not change it.
  - The dispatcher only dispatches specialist-lane (06) rows. Its count of approved ready rows for specialist lanes is 1 (F-137), and it is occupied by lane 06. A-57 is a coordinator-lane row, so no automatic route runs it.
  - The pickup executor (this job) is bounded to docs/ only, so it cannot do A-57.
- Conclusion: **nobody is executing A-57.** The existing supported route delivers messages only (liaison inbox → ACK by pickup). It does not deliver code work to an engineering session. A live Agent 01 Claude session has to attach, or the owner has to decide how coordinator code work is delivered.
- I did not touch other Claude sessions (PID 2937731 and 3445544 are bare `claude` processes in other cwds; their identity or role is UNKNOWN).

## Owner decision needed (exact)
One of:
1. Start or attach an interactive Agent 01 Claude session in the coordinator worktree (it then reads the queue and takes A-57 itself). This needs no tmux self-drive.
2. Approve a bounded dispatcher lane for coordinator code rows (A-57 in `tools/inbox_pickup.py` or its merge helper). That is a scope and access expansion, so I did not do it.

I did not enable tmux self-driving, create a coordinator, expand access or touch the UI.

## Tests
None run (read-only verification). Numbers above come from process, log and JSON reads.

## Remaining blockers
- A-57: no executing session (above).
- F-137: running. Watch for the terminal outcome in `var/dispatcher.jsonl` (`exit lane 06 task F-137`) or a stall flag after about 19:40Z.
