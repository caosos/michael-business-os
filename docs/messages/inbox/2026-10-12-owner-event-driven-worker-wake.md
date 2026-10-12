# OWNER DELIVERY — event-driven worker wake; correction of A-70 collision

- **Delivered:** 2026-10-12T00:04:30Z
- **Project:** DealSniffer / caosos/michael-business-os ONLY
- **Coordinator:** existing Agent 01
- **Priority:** P0 operating-control correction
- **Stage:** DELIVERED
- **Blocker:** immediate cloud Slack wake is blocked because the Automations service reports @ChatGPT is not a member of #all-ask-aria.
- **Next action:** reconcile this into the existing ETA/watchdog adoption work using the next unused task ID, preserve B-26, and hardcode the event outbox/relay without creating another monitor.

## Owner clarification

Michael requires the cloud supervisor to wake whenever the worker/coordinator publishes DELIVERED, ACK, WORKING, DONE, NEED/BLOCKED, or an ETA/checkpoint exception. The supervisor must inspect the event and decide what must happen to keep the work moving. This internal wake is required even when healthy progress does not warrant interrupting Michael.

Hourly polling is fallback only; it does not satisfy the event-driven ACK requirement.

## Explicit correction

The prior delivery `2026-10-11-owner-eta-driven-checks-hardcoded.md` suggested A-70. FACT: A-70 is already the completed shared-Slack-liaison disposition recorded in `docs/receipts/pickup/ARYA-20261011-0118-shared-slack-liaison.md`. Do not reuse A-70. Preserve that history and assign the ETA/watchdog adoption the next unused ID during reconciliation.

## Hardcoded event path requirement

Extend the same existing local watchdog; do not create a second watchdog, coordinator, worker, queue, or monitor.

1. Every accepted DELIVERED/ACK/WORKING/DONE/NEED-BLOCKED checkpoint is written to the existing canonical receipt lane and to one machine-readable event outbox with project, task, stage, receipt path, exact commit, observed_at, ETA, next_check_at, notification class, and provenance.
2. The existing relay publishes each new DealSniffer event once to the established `#all-ask-aria` liaison thread, with a stable event ID for deduplication. Do not publish secrets or message bodies from other projects.
3. Slack is event transport, not canonical truth and not host-liveness proof. The cloud event handoff re-reads GitHub and current host receipts.
4. The cloud supervisor wakes on every relevant event and supervises the queue. It notifies Michael only for the exception categories in the ETA addendum.
5. Add tests for outbox deduplication, event ordering, project isolation/quarantine, every required stage, retry without duplicates, and no notification loop.
6. If the host lacks an already-authorized Slack relay credential/path, record a structured NEED naming the exact missing mechanism. Do not create or expose a token and do not claim immediate cloud wake.

## Current external blocker observed by cloud supervisor

At 2026-10-11 19:03 CDT, updating the existing `DealSniffer PR handoff` event automation to include Slack failed atomically with: @ChatGPT is not in `#all-ask-aria`. No duplicate automation was created; the existing event automation remains the prior PR-only handoff and the enabled hourly Deal Sniffer supervisor remains the fallback.

The narrow owner-side action for immediate Slack events is to add the existing @ChatGPT app to `#all-ask-aria`. After that, update the existing event-handoff automation with both its GitHub PR trigger and the Slack channel trigger; do not create a third automation.

No action without a receipt. No receipt without provenance.
