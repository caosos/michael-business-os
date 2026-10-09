# ACK: 2026-10-09-aria-owner-deal-sniffer-readable-ui

- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/2026-10-09-aria-owner-deal-sniffer-readable-ui.md` (commit 8abbfa8, 2026-10-09 11:29 CDT)
- **Classification:** OWNER_INPUT + TASK_REQUEST. **Disposition: INCORPORATED as backlog task F-38 (lane 06).** Acked by Agent 01, 2026-10-09. No purchase, spend, contact, deploy or live action; no permission control bypassed.

## Decisions
| Owner point | Handling |
|---|---|
| 5 glanceable cards (DONE / WORKING / BLOCKED / OPPORTUNITIES / NEXT) on the landing screen | F-38 acceptance 1 |
| Opportunity card fields, with earned vs simulated vs unverified vs speculative kept apart | F-38 acceptance 2 (the Oct 8/9 reports are structure examples only, never shown as verified deals) |
| Click-driven decisions using only controls the UI already supports; PIN and owner boundaries kept | F-38 acceptance 3 (no invented actions) |
| Restrained styling, top 3 priorities, rest collapsible | F-38 acceptance 4 |
| Do not derail P1 repairs; do not reset data | F-38 depends on F-37 (same lane, same files) and A-49; P1 order unchanged: A-49, then D-32 / C-31 / F-37, then F-38 |
| Acceptance: real local UI with clearly labelled test data, UI tests or screenshots, every DONE receipt-backed, every action causes its real state transition | F-38 acceptance 6 |
| Wake permission kept separate; no broad Bash rule, no bypass | Unchanged: the self-wake is not enabled, the commit/enable step is waiting on the owner's narrow rule |

## Receipt
Queue row F-38 added to `docs/status/READY_QUEUE.md`; assigned to the existing lane-06 worker through the dispatcher (cheapest capable model, Sonnet). Provenance: owner message above; no sender action implied. Quota: the 5-hour window is above the guard until 2026-10-09T05:20Z, so launches wait for it.
