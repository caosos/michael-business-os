# OWNER DELIVERY — adopt ETA-driven checks and exception alerts as hardcoded DealSniffer behavior

- **Delivered:** 2026-10-11T23:56:30Z
- **Project:** DealSniffer / caosos/michael-business-os ONLY
- **Coordinator:** existing Agent 01 only
- **Suggested bounded adoption ID:** A-70
- **Priority:** P0 operating-control correction
- **Stage:** DELIVERED
- **Blocker:** NONE for implementation; do not interrupt or duplicate the current B-26 lane-02 worker
- **Next eligible action:** Agent 01 ACKs this delivery, records a realistic adoption ETA and exact America/Chicago `next_check_at`, applies the files/code/tests below, and amends the current B-26 ACK/WORKING receipt to the new schema.

Michael explicitly requires this rule to be logged in the software's root README and **hardcoded**, not left as an informal chat instruction or liaison-only note.

## Exact owner addendum (binding)

```text
PROJECT OPERATING ADDENDUM — ETA-DRIVEN CHECKS AND EXCEPTION ALERTS

This rule applies to every project and supplements the existing one-bounded-item and receipt protocol.

1. Every `ACK / WORKING` receipt must include:

- Project and bounded task ID
- Responsible coordinator or worker
- Current stage
- Evidence reviewed
- Realistic ETA
- Exact `next_check_at` timestamp in America/Chicago
- Expected acceptance test or completion evidence
- Current blocker, or `NONE`

2. The ETA must come from the actual work scope, tests, browser verification, deployment steps, and known host conditions. Do not invent an ETA or use a meaningless generic estimate.
3. The existing LOCAL watchdog owns the exact `next_check_at` timer. Do not create another coordinator, worker, queue, watchdog, or monitor.
4. At `next_check_at`, the watchdog must inspect the current process, receipts, repository state, and loaded service state where applicable. It must publish exactly one of:

- `WORKING` — current evidence, progress, revised ETA, and new `next_check_at`
- `DONE` — exact commit, tests/results, browser or review evidence, loaded revision, host observation, user-visible result, cost if known, timestamp, and next eligible item
- `NEED / BLOCKED` — exact blocker, exact required action or command, impact, compatible work continuing, and next check time

5. Finishing early requires an immediate `DONE` receipt and dispatch of the next eligible bounded item. Do not wait for the scheduled check.
6. A missed ETA or missed `next_check_at` is an exception. Record it with provenance. Do not claim the worker stopped unless current host evidence proves it; otherwise state: `APPEARS STALE — HOST STATE UNVERIFIED`.
7. Notify Michael promptly only for:

- `DONE` requiring owner acceptance
- `NEED / BLOCKED`
- Missed ACK, ETA, or check time
- Failed test, delivery, deployment, or recovery
- Genuine owner decision
- Material cost or authority boundary

Do not notify Michael for routine healthy progress, ordinary build authority already granted, or unchanged state.

8. The CLOUD supervisor remains the hourly fallback. Every hourly run must show:

- Current bounded task and queue stage
- Latest exact receipt and commit
- Tested state versus loaded state
- Last timestamped host observation or `UNKNOWN`
- ETA and `next_check_at`
- Blocker
- One next action

Cloud GitHub activity is not proof that a host process is alive. Slack, GitHub, or other supported events may provide earlier wake-ups, but they do not replace host receipts.

9. Keep every project isolated. Do not edit, dispatch, supervise, or recover another project’s work. Route misdelivered work to the proper project and preserve quarantine until the intended recipient is verified.
10. Add this rule to the project’s authoritative operating instructions, living checklist, coordinator instructions, and local-watchdog behavior. Return a dated adoption receipt showing exactly where it was applied and how the first ETA-driven check will be verified.

Governing rule:

“No action without a receipt. No receipt without provenance.”
```

## Required hardcoded application

Apply this through the existing coordinator. Do not create a second watchdog/monitor/queue.

1. **Root README:** expand `README.md` with a prominent “Operating protocol” section that names and links the authoritative checklist, queue, coordinator instructions, receipts/liaison path, existing local watchdog, cloud fallback, and includes the binding ETA receipt fields/outcomes. State that chat/Slack delivery alone is not ACK or proof of host liveness.
2. **Authoritative coordinator instructions:** append the owner addendum verbatim to `docs/COORDINATION.md`; clearly state it supersedes older conflicting timing/notification language.
3. **Living checklist:** add an A-70 adoption row/history entry to `docs/product/DEAL_SNIFFER_BUILD_CHECKLIST.md` with owner, P0, exact acceptance, stage, blocker, and next action. Preserve existing history.
4. **Watchdog documentation:** update `docs/integration/COORDINATOR_WATCHDOG.md` with the ETA timer state machine and exact evidence inspected at `next_check_at`.
5. **Executable local behavior:** modify the existing `tools/coordinator_watch.py` and its existing tests. Do not make prose the only enforcement.
   - Define and validate one machine-readable ETA/checkpoint record for the current bounded task containing the mandatory fields.
   - The existing watchdog reads that record and owns the `next_check_at` timer.
   - At or after the timestamp, inspect current worker process/session evidence, current receipts/ACKs, repository/branch state, and `var/lanes/agent-06/ARTIFACT` plus `:8766` health when the task affects the UI.
   - Emit exactly one checkpoint outcome: WORKING, DONE, or NEED/BLOCKED, with provenance, into the existing watchdog receipt/status lane; wake the existing coordinator for publication when an exception or owner notification is required.
   - If the deadline passes without verified host state, use the exact text `APPEARS STALE — HOST STATE UNVERIFIED`; never infer “stopped” from GitHub silence.
   - Early DONE must be detected/recorded without waiting for `next_check_at`, and the existing dispatcher/coordinator path handles the next eligible item.
   - Project isolation is a validation rule: reject/quarantine checkpoint records not naming DealSniffer / this repository.
6. **Tests:** add deterministic tests for:
   - missing mandatory ACK/WORKING fields;
   - valid America/Chicago `next_check_at`;
   - not-due versus due checks;
   - exactly one of WORKING/DONE/NEED-BLOCKED;
   - early DONE;
   - missed timestamp with and without current host evidence;
   - notification filtering (healthy progress does not notify);
   - project-isolation rejection/quarantine;
   - no duplicate watchdog or worker launch.
7. **Current task correction / first proof:** the B-26 ACK at `docs/messages/acks/2026-10-11-owner-p0-wooley-hibid-live-source.md` predates this addendum and lacks a realistic ETA and exact `next_check_at`. Correct it explicitly—do not silently rewrite history. Post a new WORKING checkpoint that includes all mandatory fields based on the actual current B-26 worker/process state. That `next_check_at` is the first live acceptance of the new watchdog behavior.
8. **Adoption receipt:** dated receipt must list exact commits/files, tests and results, observed local watchdog state, first B-26 ETA and `next_check_at`, first timer verification result, host observation, cost if known, and next eligible item.

## Current task truth to preserve

- B-26 ACK/WORKING exists at 2026-10-11T23:53:50Z.
- It observed HiBid Terms restricting scraping/aggregation; no HiBid page was fetched or screenshotted.
- Compatible work continues on a real Wooley auction-event source from Wooley's own site.
- Lot-level HiBid acceptance remains structured NEED unless an authorized supported route is established.
- Live UI remains `315ddfa`; F-144+F-145 are STAGING_ACCEPTED together at `179bd62cec8c6e6db5eb16760441321349e3d619`, not loaded.
- Do not interrupt or duplicate the B-26 worker while adopting the protocol.

No action without a receipt. No receipt without provenance.
