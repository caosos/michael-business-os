# OWNER DIRECTIVE — visible activity update for every meaningful Claude interaction

Delivered: 2026-10-11 19:55 America/Chicago
Project: DealSniffer
Applies to: existing Agent 01 coordinator, existing local watchdog, existing cloud supervisor
Queue item: A-71 (superseding acceptance clarification)
Owner: Michael

## Binding behavior

Michael expects a new, concise message in the ChatGPT project conversation whenever a meaningful Claude-agent event occurs, including healthy progress. This requirement supersedes the earlier exception-only owner-notification filter for DealSniffer.

Meaningful events are:

- DELIVERED
- ACK
- WORKING or material progress / revised ETA
- DONE
- NEED / BLOCKED
- missed ACK, ETA, or next_check_at
- dispatch of the next bounded item
- task-boundary reconciliation
- test, review, browser, reload, or recovery result that changes acceptance state

Each message must be brief and human-readable, not a formal report. Use this form:

> Michael — <task ID> <stage>. <what finished or what is running now>. ETA <realistic time or UNKNOWN>; next check <exact America/Chicago timestamp>. Blocker: <NONE or exact blocker>.

For DONE plus dispatch:

> Michael — <task ID> finished: <user-visible result and evidence summary>. <next task ID> is now working. ETA <realistic time or UNKNOWN>; I’ll check again at <exact America/Chicago timestamp>. Blocker: <NONE or exact blocker>.

Do not generate messages for unchanged/noise-only events. Do not invent ETA, liveness, loaded revision, or browser acceptance.

## Current missed-event evidence

- B-26 source verification completed at 2026-10-11 19:02 America/Chicago.
- F-146 worker implementation completed and pushed by 2026-10-11 19:22 America/Chicago.
- Implementation commit: d71e92f3607f55234b43fd54e88665e74700fecc.
- Lane status head: 6c2ac71fddc98f076fb1c29f64c58d531f7dd77b.
- Focused tests: 15 passed.
- Reference tests: 499 passed, 1 known timeout.
- Lane D+E: 104 passed, 3 known failures.
- Worker reports no live refresh, no Agent 01 staging Chrome desktop/mobile verification, and no loaded-service reload.
- No visible ChatGPT activity message followed this completion. Record this as a missed notification / transport acceptance failure.
- Current host process state: UNKNOWN. Do not claim the worker is still running.

## Required reconciliation

1. ACK this directive with A-71, exact evidence, ETA, and next_check_at.
2. Reconcile F-146 through independent Agent 01 review, one authorized live Wooley refresh, staging Chrome desktop/mobile verification, tested-versus-loaded state, and the authoritative checklist.
3. Publish the next bounded task through the existing coordinator.
4. For each event above, emit the concise event record through the existing local outbox/relay so the cloud event automation can write the visible ChatGPT message.
5. If the existing relay cannot publish to Slack #all-ask-aria, emit a structured NEED naming the exact missing capability. Do not create a duplicate watcher, worker, queue, coordinator, or automation.
6. Acceptance is a controlled proof in which a Claude ACK/WORKING or DONE event causes a new visible ChatGPT conversation message without owner prompting.

GitHub commits alone do not wake ChatGPT. The existing cloud Slack event automation cannot be activated until @ChatGPT is present in #all-ask-aria. Report that transport blocker exactly; it does not excuse continued local receipt/checklist work.

Governing rule: “No action without a receipt. No receipt without provenance.”
