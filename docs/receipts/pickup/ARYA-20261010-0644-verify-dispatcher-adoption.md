# Pickup receipt: ARYA-20261010-0644-verify-dispatcher-adoption

Observed read-only at 2026-10-10T06:44:45Z (01:44 CDT). No restart, reload, or code change was made.

## Observed facts (execution, separate from ACK and queue readiness)
- **Dispatcher:** PID 3502055 (`.venv/bin/python -I tools/dispatcher.py`, tee PID 3502056), started 2026-10-10 01:34:14 CDT (06:34:14Z). Elapsed about 10.5 min.
- **Loaded code revision:** c7d8524 was committed 01:34:08 CDT, 6 s before the dispatcher started. The dispatcher imports from the `agent-01-coordinator` worktree, whose HEAD is 90639b4 (01:35:27). So it started on c7d8524 or later, i.e. **not pre-c7d8524 code**. This is inferred from timestamps; the process does not expose its own revision. No reload was needed and none was done.
- **F-56 launch:** `var/dispatcher.jsonl` 06:34:15Z `launch` lane 06 task F-56 (`tools/worker.py F-56 --lane 06 --kind implement --risk high --max-turns 100 --timeout 3500`, dry=false). It was the only F-56 launch event (1 attempt).
- **Worker ownership:** `tools/worker.py` PID 3502090 and its child `claude -p` PID 3502101 are alive at 06:44Z (about 10.5 min). One worker, lane 06 only; no duplicate F-56 worker; the lane is the lock owner.
- **Dispatcher state since launch:** `idle` events 06:35:46Z to 06:43:21Z every ~90 s, `running: ["06"]`, "nothing ready for an idle lane". Quota guard: session 30.0% / week 11.0%, under limits.
- **F-57 gate:** 06:34:47Z `reset` event clears F-57's burned attempts (2 earlier dependency-BLOCKED no-op runs). F-57 is not launched and stays gated until F-56 actually completes (c7d8524 `ready_for` honours dependencies).
- **Worker output:** `var/worker-F-56.out` is still empty and no F-56 commit exists yet, so there is **no completion evidence**. F-56 is RUNNING, not DONE.
- **Dirty-worktree guard:** the coordinator worktree has uncommitted edits in `tools/coordinator_watch.py` and `tests/unit/test_coordinator_watch.py`. They are 01's own in-progress work, not the worker's. They did not stop the launch.

## Tests
No tests run. This task did not change any code.

## Remaining / owner decisions
- None needed. Next check: when PID 3502090 exits, read `var/worker-F-56.out` and the F-56 commit, then the dispatcher may release F-57.
- No READY_QUEUE row added or changed. F-56 and F-57 rows are unchanged.
