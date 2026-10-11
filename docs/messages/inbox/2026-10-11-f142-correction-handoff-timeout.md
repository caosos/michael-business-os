# F-142 correction handoff evidence timeout — inspect existing feed, then claim same row

**Route:** existing Agent 01 coordinator / claim-first READY_QUEUE only.
**Recorded:** 2026-10-11T18:06:06Z / 13:06:06 CDT.
**Priority:** P0 continuation of F-142; not a new task.

Coordinator commit `104cefdf8bded1ad2f87b03d63f02c6ed936b301` made F-142 READY — CORRECTION REQUIRED at 2026-10-11T18:00:54Z. At 18:06:05Z (311 seconds later), GitHub still showed coordinator head `104cefd` and lane 06 head `5b2fadc`; no new ACK, claim/START, worker receipt or correction commit was visible.

This is an **evidence timeout**, not proof that the host feed/process was absent. Do not infer Claude is idle from GitHub alone.

Exact existing recovery action:
1. Inspect the current Agent 01 tmux session, `next_work.py` watcher/arm log, dispatcher, active claims and queue parser against coordinator `104cefd`.
2. If F-142 was already announced or claimed, publish the timestamped host/claim receipt without starting anything else.
3. If it was not announced, use the existing session/feed to claim **the same F-142 row** and dispatch exactly one lane 06 worker. Do not create another coordinator, watchdog, monitor, scheduler, task ID or service.
4. Correction scope: move/consolidate Keywords, Condition and More filters so Search Now is last across the complete filter area. Preserve the real GET form, Enter, Save/PIN and current behavior. Re-run exact-commit desktop/mobile Chrome acceptance. Do not request or perform live `:8766` reload until staging passes.
5. ACK/WORKING or structured NEED through the existing path, with current host timestamp and loaded SHA.

A-68 remains PARTIAL unless this genuine eligible-task transition is timestamped <=300 seconds. A-69 remains historical DONE.
