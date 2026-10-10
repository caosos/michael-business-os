# Pickup receipt: ARYA-20261010-0530-owner-resume-included-quota

Status: **COMPLETED** (docs reconciliation only; dry-run; no code, restart, spend or contact).

## Actual state (FACT, `ps` at read time)
- The 0528 pause was never applied to processes: dispatcher (`tools/dispatcher.py`, pid 3399447), pickup daemon (pid 3355056) and the lane-06 worker `tools/worker.py F-53 ... --timeout 3500` (pid 3399484) are all still running. No durable pause flag file exists in the repo (grep for PAUSED_BY_OWNER finds only docs records).
- So "resume" = remove the stale doc-level holds; nothing to restart. No duplicate coordinator/worker started.

## Reconciled in docs/status/READY_QUEUE.md
- F-53: BLOCKED/PAUSED_BY_OWNER -> RESUMED/RUNNING under the same worker; stale "SUPERSEDED: pause" text replaced.
- PAUSE-01 (host stop of dispatcher/pickup): CANCELLED; the 0528 receipt's host-action list (stop dispatcher/pickup) is void and must NOT be executed.
- The 0528 ack/receipt remain as history, superseded by this one.

## Boundaries carried forward
Included existing allowance only: no paid usage, credit purchase, upgrade, new API billing or credentials. On quota exhaustion: checkpoint and report the observed blocker, no retry loop, no paid-provider switch. Precise quota is UNKNOWN (not observed). UI reload, security and production gates unchanged; systemd/linger still not approved. Desktop operational-visibility completion resumes separately; Care continues non-voice pilot work (their own queue rows, not touched here).

## Next task
F-53 (4 F-52 acceptance gaps) continues in the running worker; then the acceptance matrix. Tests: none (docs only).

## Remaining blockers
None for this instruction. WORKING_COUNT.md still carries the old pause text; Agent 01 refreshes it on next sync.
