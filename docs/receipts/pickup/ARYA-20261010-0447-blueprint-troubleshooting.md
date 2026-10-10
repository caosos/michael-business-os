# Pickup receipt: ARYA-20261010-0447-blueprint-troubleshooting

- **observed_at:** 2026-10-10T04:48Z–04:52Z (FACT: executor run). Docs-only, dry-run. Tests run: 0 (no code changed; pytest is not installed for the system python in this worktree, so no suite was run).
- **Stages:** pickup/ACK = done (04:48:08Z). Execution of this docs reconciliation = done by this run. Code completion, staging acceptance, live acceptance = not applicable to this task; for F-51/F-52/A-52 all three are NOT done.

## What was done
- Added "Troubleshooting history: coordination and delivery" at the end of `docs/operations/AI_PROJECT_OPERATING_BLUEPRINT.md` (RUNBOOK.md is outside docs/, so not edited): stage vocabulary, immutable-id rule, a symptom/cause/fix/rollback/next-owner table, and the pickup vs dispatcher vs interactive-wake roles.
- Added a one-bullet stage-separation rule to the project overrides in `docs/operations/AI_PROJECT_OPERATING_BLUEPRINT.md`.
- Added a status pointer to `docs/product/DEAL_SNIFFER_START_HERE.md` (F-51/F-52 not accepted anywhere).
- No duplicate blueprint, log, coordinator or daemon. Existing receipts are linked, not copied.

## Reconciled facts (evidence)
- Duplicate/already-ACKed execution: fixed in `7bd5160` with a regression test.
- A-52 false idle/stale heartbeat: still unfixed in code (`tools/inbox_pickup.py` line 38 `HEARTBEAT_S=600`, line 193 `ttl_sec: 300`). Row A-52 in READY_QUEUE stays READY (lane 01 code). Evidence: `docs/receipts/pickup/ARYA-20261010-0431-execution-handoff-proof.md`.
- Strict unknown price/distance defect: unfixed; owned by F-51 (A), then F-52. Scope: `docs/handoff/F-51-amendment.md`.
- F-51 amendment handoff: unproven; see `docs/receipts/pickup/ARYA-20261010-0433-f51-scope-handoff.md` and its BLOCKED ACK. Lane-06 branch head at last look was `8257e2e` (F-50); no F-51 commit seen.
- Persistence: PREPARED, NOT INSTALLED (`docs/operations/PICKUP_PERSISTENCE.md`). No installation receipt exists.
- Not edited (coordinator-owned): READY_QUEUE rows; the F-50 row staleness noted in the 0431 receipt remains for the coordinator.

## Remaining blockers / owner decisions
- Owner: `loginctl enable-linger michaelos` approval, only if persistence across reboot is wanted.
- Agent 01 (code session): add a one-line link from RUNBOOK.md section 7 to that subsection.
- Lane 06: prove F-51 read the amendment (receipt/status citing "AMENDMENT"). Agent 01: implement A-52.
- F-51 product work was not delayed by this change.

Safety: no bids, spend, contact, restart, deploy, secrets or other-branch writes.
