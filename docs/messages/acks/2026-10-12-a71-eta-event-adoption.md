# ACK -> WORKING — A-71 ETA-driven checkpoints + event outbox (answers 5 liaison messages)
Messages: 2026-10-11-owner-eta-driven-checks, -eta-driven-checks-hardcoded, -use-pr1-event-bridge, -visible-claude-activity-updates, 2026-10-12-owner-event-driven-worker-wake.
- **Project / task:** DealSniffer / A-71 (the next unused id after historical A-70; A-70 is not reused).
- **Responsible:** Agent 01 (coordinator-owned code: tools/coordinator_watch.py and a new tools/eta_checkpoints.py).
- **Stage:** WORKING (implementation started 2026-10-11 22:52 CDT).
- **Evidence reviewed:** A-71 row (CLAIMED/PARTIAL: PR #1 transport proven by the cloud side, comments 6115954194/6115961662; code/docs/tests NOT implemented); the local watchdog (459 lines; receipts/state in var/watchdog); host: `gh` is NOT authenticated here (`gh auth status`: not logged in), so the local relay cannot post PR #1 comments yet.
- **ETA (from scope):** about 90 minutes: checkpoint schema + timer + exactly-one-outcome logic + outbox (stable event id, dedupe, ordering, retry without duplicates, isolation) + PR #1 relay via gh + docs (README, COORDINATION, COORDINATOR_WATCHDOG) + deterministic tests.
- **next_check_at:** 2026-10-11 23:52 CDT
- **Expected acceptance:** the A-71 test list passes; the watchdog writes a WORKING/DONE/NEED outcome at a due next_check_at; events land once in the outbox; relay posts once when gh is authenticated (else a structured NEED).
- **Blocker:** relay transport only: NEED `gh auth login` on this host (owner) or an equivalent already-authorized token; implementation itself is NOT blocked.
- **Parallel product work:** B-29 Blackmon events READY for lane 02 (dispatcher); combined Marketplace release waits on the owner command recorded in LIVE_RELOAD_PACKET_8766.md.
