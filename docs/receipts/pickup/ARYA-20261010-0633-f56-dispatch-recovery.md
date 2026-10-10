# Pickup receipt: ARYA-20261010-0633-f56-dispatch-recovery

Executor: automatic inbox pickup (docs-only, dry-run). Date 2026-10-10.

## Verified (already fixed by c7d8524)
- `docs/status/READY_QUEUE.md` F-56 (line 383) now has 7 cells (awk split on ` | `): deps `F-54, F-55`, status `**READY**`, agent `worker:lane-06 (sonnet)`. Task and acceptance text intact.
- F-57 (line 384) has 7 cells, deps `F-56`, READY. `python3 tools/foreman.py --no-fetch` lists only `ready=F-56(P0)` for lane 06; F-57 is not offered, so the dependency gate works. No active worker was on F-56 at check time (claimed=-), so no duplicate-dispatch risk from this row.
- Regression tests in `tests/unit/test_foreman.py` (added in c7d8524): run by direct call, 5 pass (parse/reconcile/dependency/short-row tests). 3 capsys-based tests could not run here (no pytest installed; not a failure of the code, not counted). Not independently re-run under pytest.

## Not done (needs code, live worker, or owner decision; outside docs-only scope)
- Explicit surfacing of malformed rows (none implemented: no "invalid" handling in foreman.py) and no-repeat-attempt guarantee for unmet deps: queued as **A-53** (owner Agent 01).
- Executing F-56 Save-form correction, staging acceptance, then F-57: these are lane-06 code tasks. F-56 is READY and dispatchable by dispatcher/foreman `--launch`; F-57 follows only after F-56 DONE with a lane 06 receipt. I did not mark any dependency complete.

## Blockers
None for F-56 dispatch. A-53 pending.
