# DealSniffer immediate event bridge

Created: 2026-10-11 20:07 America/Chicago
Owner: Michael
Coordinator: existing Agent 01 only

This long-lived pull request is an event transport for the existing DealSniffer coordinator/watchdog. It is not a queue, source of truth, coordinator, worker, watchdog, or monitor.

The existing local watchdog may post concise PR conversation comments for meaningful DealSniffer events:

- DELIVERED
- ACK
- WORKING or material progress
- DONE
- NEED / BLOCKED
- missed ACK, ETA, or next_check_at
- next bounded item dispatch
- task-boundary reconciliation
- test, review, browser, reload, or recovery state changes

Each comment must name task, stage, evidence, realistic ETA or UNKNOWN, exact America/Chicago next_check_at or MISSING, blocker, and provenance. The event-driven ChatGPT supervisor converts each meaningful comment into a short visible update for Michael.

Do not merge or close this PR while DealSniffer operations are active. GitHub remains transport only; authoritative state stays in the living checklist, queue, receipts, exact commits, and loaded-service evidence.

Governing rule: “No action without a receipt. No receipt without provenance.”
