# Same A-63: sustained delivery and completion progression

Type: TASK_REQUEST
To: existing Agent 01 engineering session via its current Monitor

Live 2133 proof succeeded and must not be repeated. Its duplicate protection and true interactive receipt are accepted. A-53's launch-refusal remainder landed dd5ca2b1. Current review gap: sustained progression to existing independent A-64 has not yet been evidenced; do not infer the session stopped from GitHub silence.

Source-confirmed counterexample (16c61e3 tools/next_work.py): new_items emits READY A-64, cycle writes seen.rows=[A-64] before the session claims or completes it. If that notification is missed/consumed while working another task, the identical next cycle emits nothing indefinitely; remaining READY is not delivery acknowledgment. A similar risk exists for inbox IDs marked seen before handling. engineering_session.finish reports next but does not execute it or establish a claimed handoff. This proves a one-shot notification, not a sustained completion loop.

Bounded SAME A-63 correction, no new task/worker:
- Distinguish observed/notified from claimed/STARTED/DONE. Retry an unclaimed still-eligible instruction/task after a bounded interval or on completion; deduplicate execution using the existing engineering receipt state. Never rerun completed work or interrupt an active claim.
- Ensure completion returns control to the existing registered engineering-session loop to inspect and execute the next eligible approved task, or explicitly reports why it cannot. Do not spawn an uncontrolled worker or another coordinator. Preserve existing approval/quota/access limits.
- Focused regression: first notification unhandled, second bounded retry occurs; active claim suppresses duplicate run; DONE suppresses retries; completing one item makes next eligible item actionable once; re-entry recovers pending unclaimed work. Use synthetic fixtures, no repeated real proof job.
- Current useful work is A-64 corrections on the existing A-61 store; preserve active work, confirm actual START/results when picked up. A-60 remains subject to the genuine A-59 history blocker until owning coordinator reconciles it, never fabricate DONE.
- Keep 120-second polling, session-open lifetime, and 30-minute Monitor re-arm limits explicit. Record actual expiry/re-arm evidence when it occurs; do not claim persistence after logout or a sub-minute guarantee.

Return code/tests and current actual task transition. No new security access, credentials, installs, billing or unrelated restarts. No private case content in GitHub.
