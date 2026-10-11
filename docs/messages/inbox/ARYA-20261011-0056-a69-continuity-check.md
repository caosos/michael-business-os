# Continue existing A-69: restore the ongoing work and owner-interrupt loop

Type: TASK_REQUEST
Priority: P1
Task: A-69 (existing task; do not create a duplicate)
Owner direction: Michael's directive in this conversation is to keep the existing coordinator and workers progressing through eligible work, and route genuine owner decisions/blocks back to Aria/Michael. Use the existing Agent 01 session and inbox/ACK protocol.

## Evidence from Michael's restart screenshot
A local Claude Code session reported, at about 2026-10-11 05:54 UTC:
- `mbos-dispatcher` running.
- `mbos-watchdog` restarted with `--no-wake`.
- `:8766/market` returned HTTP 200.
- A-69 appeared READY.
This is screenshot-reported evidence, not independent verification. It does not prove ports 8477/3000, the next_work feed, an A-69 claim, or a live task handoff.

## Request
1. On receipt, inspect current repo/host state, owner pause/quota, active claims, existing dispatcher, watchdog, and Agent 01's existing `next_work.py --watch 120` feed. Distinguish the coordinator watchdog from the task feed; do not infer that one keeps the other armed.
2. Use the existing Agent 01 claim-first flow to claim/continue A-69 if it is still eligible. Do not create another task, coordinator, worker, monitor, scheduler, or service.
3. Complete A-69's existing acceptance: re-arm the one existing feed before its Monitor lifetime ends; record arm/expiry timestamps; suppress duplicate watchers; preserve A-68 pause/quota/dedup/active-claim/dependency/DONE rules; add focused tests; obtain live evidence for successive arms and eligible-task progression. If the session is closed or a prerequisite is absent, record the exact blocker and recovery procedure.
4. Verify the owner-interrupt protocol end-to-end: ordinary task completion continues to the next eligible task; only a genuine owner decision or hard blocker creates a concise durable request to Aria/Michael through the existing inbox/ACK route. An ACK is not execution. Keep requests and receipts traceable to a task and commit.
5. Inspect how the existing dispatcher/feed/watchdog recover after logout/reboot. Reuse existing services and units; propose any missing startup service with evidence before creating it. Do not assume that a running `--no-wake` watchdog is a functioning task handoff.
6. Verify live health of `:8766`, `:8477`, and `:3000` from the host, and report each result separately. Do not restart or alter app releases merely to make checks green.

## Constraints
No paid usage, quota bypass, credentials, outbound contact, spend, purchase, deployment, unrelated code edits, duplicate processes, or cleanup/push of unrelated local changes. Keep all claims separated into screenshot report, source/tests, and live runtime evidence. Continue to the next compatible authorized task after A-69 only through the existing queue and claim protocol.

## Acceptance
Agent 01 ACK/disposition; pushed claim or exact eligibility blocker; A-69 code/test/receipt and live re-arm/progression evidence or exact runtime blocker; owner-interrupt behavior verified; three port results; and a clear statement of what remains unverified.
