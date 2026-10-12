# michael-business-os
Persistent self-hosted AI business operating system for opportunity discovery, deal scoring, marketing, CRM, communications, approvals, receipts, and revenue optimization.

## ETA-driven checks and event outbox (owner addendum, adopted verbatim 2026-10-12)

```text
PROJECT OPERATING ADDENDUM — ETA-DRIVEN CHECKS AND EXCEPTION ALERTS

This rule applies to every project and supplements the existing one-bounded-item and receipt protocol.

1. Every ACK / WORKING receipt must include:
- Project and bounded task ID
- Responsible coordinator or worker
- Current stage
- Evidence reviewed
- Realistic ETA
- Exact next_check_at timestamp in America/Chicago
- Expected acceptance test or completion evidence
- Current blocker, or NONE

2. The ETA must come from the actual work scope, tests, browser verification, deployment steps, and known host conditions. Do not invent an ETA or use a meaningless generic estimate.
3. The existing LOCAL watchdog owns the exact next_check_at timer. Do not create another coordinator, worker, queue, watchdog, or monitor.
4. At next_check_at, the watchdog must inspect the current process, receipts, repository state, and loaded service state where applicable. It must publish exactly one of:
- WORKING — current evidence, progress, revised ETA, and new next_check_at
- DONE — exact commit, tests/results, browser or review evidence, loaded revision, host observation, user-visible result, cost if known, timestamp, and next eligible item
- NEED / BLOCKED — exact blocker, exact required action or command, impact, compatible work continuing, and next check time
5. Finishing early requires an immediate DONE receipt and dispatch of the next eligible bounded item. Do not wait for the scheduled check.
6. A missed ETA or missed next_check_at is an exception. Record it with provenance. Do not claim the worker stopped unless current host evidence proves it; otherwise state: APPEARS STALE — HOST STATE UNVERIFIED.
7. Notify Michael promptly only for DONE requiring owner acceptance; NEED / BLOCKED; missed ACK, ETA, or check time; failed test, delivery, deployment, or recovery; genuine owner decision; material cost or authority boundary. Do not notify Michael for routine healthy progress, ordinary build authority already granted, or unchanged state.
8. The CLOUD supervisor remains the hourly fallback. Every hourly run must show: current bounded task and queue stage; latest exact receipt and commit; tested state versus loaded state; last timestamped host observation or UNKNOWN; ETA and next_check_at; blocker; one next action. Cloud GitHub activity is not proof that a host process is alive. Slack, GitHub, or other supported events may provide earlier wake-ups, but they do not replace host receipts.
9. Keep every project isolated. Do not edit, dispatch, supervise, or recover another project's work. Route misdelivered work to the proper project and preserve quarantine until the intended recipient is verified.
10. Add this rule to the project's authoritative README or START_HERE, operating instructions, living checklist, coordinator instructions, and executable local-watchdog behavior. Add tests that prove the receipt schema, exact timer, three allowed outcomes, early DONE, missed-check exception, and notification filtering. Cloud prompt text alone does not satisfy adoption.

Return a dated adoption receipt showing exact files, commit, tests, loaded revision/host observation where applicable, and how the first ETA-driven check will be verified.

Governing rule: “No action without a receipt. No receipt without provenance.”
```

Implementation in this repository (A-71): `tools/eta_checkpoints.py` (checkpoint schema validation, exact America/Chicago `next_check_at`, exactly one WORKING/DONE/NEED outcome at a due check, early DONE, `APPEARS STALE — HOST STATE UNVERIFIED` without host evidence, once-only event outbox `var/watchdog/events.jsonl` with stable event ids, project quarantine, ordered relay without duplicates or loops), called every cycle by the existing local watchdog `tools/coordinator_watch.py`; tests `tests/unit/test_eta_checkpoints.py`. Record a checkpoint: `tools/eta_checkpoints.py WORKING --task <ID> --responsible <who> --evidence <...> --eta <scope-based> --next-check '2026-10-11 23:52 CDT' --acceptance <...> --blocker NONE`.
DealSniffer override (owner directive 2026-10-11 19:55 and 20:09 CDT): every meaningful event (DELIVERED, ACK, WORKING/material progress, DONE, NEED/BLOCKED, missed ACK/ETA/next_check_at, dispatch, reconciliation, acceptance-changing results) is relayed as one concise comment on GitHub PR #1 (transport only, never truth, never merged); `owner_alert` marks the exception classes of item 7. The relay needs an authenticated `gh` on the host; until then events queue in the outbox and the watchdog records one structured NEED.
