# Existing F61 recovery: runtime adoption and merge regression protection

Continue the already authorized F61 recovery from ARYA-20261010-1803-f61-queue-reconcile. This is an addendum to that recovery, not a new product task, coordinator, or duplicate F60/F61 dispatch.

The published queue repair c35e0c7 restores F61 READY and F60 DONE. Source tools/coordinator_watch.py already has dispatcher_action/start_dispatcher, a 120-second cycle, a 600-second restart guard, and remote foreman survey. F60 began 17:31:19 after the 17:30:30 queue publication; its receipt reports dispatcher restart 17:31:18. Identify the actual existing restart mechanism and current runtime, rather than assuming interactive coordinator wake is required.

First inspect actual current worker/dispatcher processes, watchdog PID/arguments and code adoption, var/watchdog/status.json or existing read-only 127.0.0.1:8479/health.json, latest dispatcher_restarted receipt and dispatcher log. If F61 already started, preserve it and report exact start, task, PID, branch and quota evidence. No duplicate launch or active-process interruption.

If F61 is not running, establish the precise eligible-row count, queue ref/head, restart decision, last-start guard, quota result and permission/runtime blocker. Existing authorized engineering coordinator may adopt the repaired queue and routinely recover its existing dispatcher under existing authority. Docs-only pickup must not bypass its capability restrictions: route to the existing owning engineering coordinator through its supported existing mechanism, or explicitly report that handoff is unavailable. Do not repeatedly label documentation completion as execution.

Within this same bounded queue-operability recovery, add focused regression protection against stale pickup merges silently deleting newer task IDs or turning completed tasks back to READY. Preserve latest owner instructions, unique task IDs, dependencies and F60 DONE. Legitimate explicit task cancellations or reopenings must remain possible and attributable. Test the concrete 9435d68 stale-side merge failure and a legitimate update; report source/test evidence and root cause. Do not create unrelated feature work.

Included Claude allowance only. No paid overage, new API billing, security expansion, new persistent installation, new coordinator or other-project queue dispatch. No live UI reload or cache fetch. Report ACK separately from actual runtime recovery and final engineering verification.
