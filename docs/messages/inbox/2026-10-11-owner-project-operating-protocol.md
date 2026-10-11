PROJECT OPERATING PROTOCOL — ONE BOUNDED ITEM AT A TIME

1. Keep one authoritative living checklist and one receipt/liaison lane per project.
   Every item names its owner, priority, acceptance test, current stage, blocker,
   and next eligible action. Preserve completed history; correct stale entries
   explicitly.

2. The existing coordinator claims ONE eligible item and posts:
   DELIVERED → ACK → WORKING → DONE, or a structured NEED.
   A delivery is not an ACK. A worker claim is not a verified result.

3. A DONE receipt must include the exact commit, tests and results, review or
   browser evidence, loaded service revision and host observation if applicable,
   user-visible result, cost if known, timestamp, and the next queue item.

4. At each task boundary, reconcile the checklist and dispatch the next eligible
   bounded item through the existing coordinator. Do not start a duplicate
   coordinator or worker. If an item is blocked, state the exact action needed
   and continue compatible authorized work.

5. The LOCAL watchdog handles delivery, session health, and the five-minute ACK
   target. It records a timestamped NEED when delivery or ACK fails. A GitHub
   comment is a dated report; it is not proof that a host process is alive now.

6. The CLOUD supervisor checks GitHub, the checklist, commits, and the Slack
   liaison hourly and posts a visible checkpoint, even when nothing changed:
   current task, queue stage, latest receipt, tested state, loaded state, last
   host observation or UNKNOWN, blocker, and ONE next action. PR events can
   prompt an additional review; Issue comments rely on the hourly check or the
   local relay.

7. Notify Michael promptly for DONE needing acceptance, BLOCKED/NEED, missed ACK,
   failed test or recovery, or a genuine owner decision. Do not ask again for
   routine build authority already granted. Never describe a partial handoff
   or an unobserved service as continuously running.

8. Keep project ownership and code isolated. No cross-project edits, duplicate
   queues, invented progress, or silent stops. Governing rule:
   “No action without a receipt. No receipt without provenance.”

## DealSniffer delivery and bounded adoption task

- Project: caosos/michael-business-os only.
- Owner: existing Agent 01 coordinator, research/agent-01-coordinator.
- Priority: P0 operations reconciliation; preserve F-142 as the P0 user-visible release objective.
- Stage: DELIVERED by this liaison commit. ACK and WORKING are not yet observed.
- Authoritative product checklist: docs/product/DEAL_SNIFFER_BUILD_CHECKLIST.md.
- Existing dispatch queue: docs/status/READY_QUEUE.md. This message is not a second queue.
- Existing receipt lane: docs/messages/acks and docs/receipts through Agent 01.

Claim ONE bounded item: adopt the owner protocol verbatim in the existing governing coordination document or its existing referenced operations document, and reconcile current F-142 wording across the existing checklist, queue and release packet. Preserve history and explicitly label superseded instructions. The exact reload to 85246899debf5c9b8af418dc5560f3b01273d5ee was already authorized; do not request that routine authorization again. The current blocker is the Claude Code permission-classifier denial at 2026-10-11T21:17Z, not missing owner authorization. Do not bypass the denial.

Acceptance: pushed exact commit with reviewed documentation diff; existing queue parser still accepts the queue; no duplicate coordinator/worker/queue/service; protocol preserved exactly; F-142 stays PARTIAL/STAGING_ACCEPTED until live proof; structured NEED includes exact remaining host action, impact, compatible work and next check. Publish current timestamped host/session and existing local watchdog evidence, or UNKNOWN. A-68 stays PARTIAL until its genuine completion-to-next-task transition is observed. Cost UNKNOWN unless available.

At the boundary, publish DONE for this documentation reconciliation only, with receipt fields required above, then choose one actually eligible compatible item. If none is eligible, publish the specific NEED and next check rather than inventing progress. Local watchdog must receipt delivery and ACK within five minutes of actual host delivery; GitHub creation alone does not prove that delivery.

Owner screenshot at 2026-10-11 16:26:55 CDT shows Agent 01 WAITING, prior live revision 63d741d, and a prefilled ! tools/reload_ui.sh command. It shows no execution result and no new loaded revision. The cloud supervisor remains hourly; current host liveness is UNKNOWN from this cloud session.
