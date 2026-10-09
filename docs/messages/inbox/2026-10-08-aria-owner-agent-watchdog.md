# OWNER INSTRUCTION: Reliable Claude coordinator wake and GitHub inbox delivery
**Date:** 2026-10-08 CDT
**Sender:** Aria on behalf of Michael
**Recipient:** Existing Michael Business OS Agent 01 persistent coordinator
**Priority:** Operations reliability (no live actions)

Michael clarified: "do we need to set them each on a github read for instructions on what we want them to do? ... give me what I need to make it happen."

## Already in place
- `docs/COORDINATION.md` mandates Agent 01 to `git fetch` and read `origin/liaison/aria-to-agent-01:docs/messages/inbox/` on startup, each task completion, and coordinator sync; ACK to `docs/messages/acks/`.
- `mbos-dispatcher` runs bounded workers from READY_QUEUE, with a quota guard. It does not prove that the *Claude Agent 01 conversation* is automatically awakened to check a newly posted owner message.
- Host-reboot persistence is separately gated as O-1 (NEEDS OPERATOR). Do not enable host persistence without owner approval.

## Required coordinator task
1. Read this message, ACK with a durable receipt on your own coordinator branch, and summarize current actual Agent01/dispatcher heartbeat configuration (not assumptions).
2. Coordinate with the existing Desktop-Agent control plane polling GitHub every ~120s for the CAOSCare/Desktop-Agent issues. Add the missing **Deal Sniffer liaison inbox** to the *central* read-only poller/notification bridge if suitable, instead of creating competing pollers or a second dispatcher.
3. On new authenticated liaison message, the cheap monitor should create a durable inbox item, deduplicate, send/notify to Agent 01 when an active session is available, and record actual ACK after Agent01 reads it; do not label delivery as ACK. Retry safely after restart, and show stale/disconnected when no agent is available.
4. Keep the dispatcher checking approved READY work, worker completion/stalls/quota; an idle poll with no work must not invoke a Claude model. If an actual periodic Claude wake is needed, make it bounded, event-driven and quota aware; do not burn context or credits just to say idle.
5. Maintain DRY-RUN ONLY. Never launch unapproved live acquisitions, contacts, ads, account funding, API calls, installs, destructive actions or any change across project authority boundaries.
6. Return a tested end-to-end ACK with source file and any limitations; report through established durable status receipts. No owner action tonight.

Do not replace Agent 01's coordinating authority. No action without a receipt. No receipt without provenance.
