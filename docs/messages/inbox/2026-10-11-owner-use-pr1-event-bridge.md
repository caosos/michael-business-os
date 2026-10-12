# OWNER DIRECTIVE — use proven PR #1 event bridge for visible activity

Delivered: 2026-10-11 20:09 America/Chicago
Project: DealSniffer
Task: A-71 event transport acceptance
Owner: Michael
Coordinator: existing Agent 01 only

## Proven state

Slack connection and membership are verified:

- channel: #all-ask-aria
- channel ID: C0C81K9QNGK
- @ChatGPT member ID: U0C8E9T7L9J
- membership verified after reinstall

The Slack webhook automation validator still falsely rejects that verified membership. Do not ask Michael to reinstall or reinvite again.

The existing DealSniffer immediate automation is now explicitly attached to GitHub PR #1:

- https://github.com/caosos/michael-business-os/pull/1
- bridge commit: 1e4c02d82fdec349ac0d079d13929ff6c5ae2c01
- controlled event comment: 6115961662
- automation observed run: 2026-10-11 20:08:54 America/Chicago

This is the current proven immediate event path.

## Required local watchdog behavior

For every meaningful DealSniffer event, the existing local watchdog/coordinator posts one concise PR #1 conversation comment. Events include DELIVERED, ACK, WORKING/material progress, DONE, NEED/BLOCKED, missed ACK/ETA/next_check_at, next-item dispatch, task-boundary reconciliation, and acceptance-state-changing test/review/browser/reload/recovery results.

Comment form:

```
DEAL SNIFFER: <task ID> — <stage>
Result/current work: <short exact statement>
Evidence: <exact commit/receipt/tests/browser/loaded state>
ETA: <realistic time or UNKNOWN>
next_check_at: <exact America/Chicago timestamp or MISSING>
Blocker: <NONE or exact blocker>
Host observation: <timestamp or UNKNOWN>
Next bounded item/action: <one item>
```

PR #1 is transport only. It is not a source of truth, coordinator, queue, worker, watchdog, monitor, or merge target. Keep authoritative state in the living checklist, queue, receipts, exact commits, and loaded-service evidence. Do not merge or close PR #1 while DealSniffer operations are active.

## Immediate reconciliation required

1. ACK this directive under A-71.
2. Reconcile F-146 independently: one authorized live Wooley refresh, desktop/mobile Chrome acceptance, tested-versus-loaded state, checklist/receipt update.
3. Post the F-146 event receipt to PR #1.
4. Dispatch the next single bounded task and post that event to PR #1.
5. Include realistic ETA and exact next_check_at in every ACK/WORKING.

Acceptance is a real Agent 01/Claude receipt posted to PR #1 that causes a new visible ChatGPT message for Michael without owner prompting.

Governing rule: “No action without a receipt. No receipt without provenance.”
