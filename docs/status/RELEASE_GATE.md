# Release gate: wave two (FAIL)

- **Run:** 2026-10-07 19:35 -0500
- **Command:** `.venv/bin/python -I tools/release_gate.py --fetch`
- **Mode:** DRY-RUN only. Throwaway local PostgreSQL 16.

## Lane heads tested

| Lane | Commit |
|---|---|
| 01-coordinator | `e20d6af` |
| 02-opportunity | `cb7d3c1` |
| 03-economics | `4579261` |
| 04-state | `cd7e338` |
| 05-governance | `da7a93e` |
| 06-communications | `0a3c672` |
| 07-marketing | `7342abc` |
| 01-coordinator (local HEAD) | `e20d6af` |

## Checks

| Check | Result | Time | Summary |
|---|---|---|---|
| frozen contracts (validate_contracts.py) | PASS | 0.5s | schemas checked: 11 |
| frozen contracts pinned (FROZEN.sha256.json) | PASS | 0.1s | OK: 26 contract files match the pin |
| ADR-0010 vectors (reference self-test) | PASS | 0.0s | PASS receipt_chain: 2 receipts verified |
| full test suite (pytest) | PASS | 516.2s | 285 passed in 512.77s (0:08:32) |
| suite floor (tools/release_gate_floor.json) | PASS | 0.0s | passed 285 (min 250), skipped 0 (max 3), failed 0 |
| cross-lane interop (tools/interop_check.py) | PASS | 0.1s | 6/6 Python lanes CONFORM (vectors + rejections + vendored-copy identity) |
| installed lane packages == pushed heads (no stale installs) | FAIL (rc 1) | 0.0s | mbos_governance: 1 differ (cli.py), 1 missing, 0 extra () |
| lane D/E ACTION path (real gateway, follow-up, PANIC drill, live effector rows must be 0 and >=2 calls) | PASS | 8.5s | effector calls 2 (live 0) · executed 2 · follow-up {'policy_denied': False, 'executed_receipts': 2, 'second_request': True, 'concurrent': {'accepted': 1, 'refused': ['DecisionRefused', 'DecisionRefused', 'DecisionRefused', 'DecisionRefused', 'DecisionRefused'], 'live_pending': 1}} · panic drill True · chain ok True |
| lane D/E e2e + strict AT-1 (03 engine, 05 gateway, 04 schema) | PASS | 6.9s | chain 60 ok=True · reference 60 receipts verified · effector 0 (live 0) · contract errors 0 · AT-1 {'ok': True, 'drift_count': 0, 'weak_receipt_count': 0, 'items': 4} · final {'mower': 'ARCHIVED', 'smart_home_install': 'ARCHIVED', 'drywall_repair': 'RESEARCHING', 'trailer': 'RESEARCHING'} |

## Coverage notes

- **Action path with 05's real gateway on lane D:** `tests/integration/test_spine_on_lane_d.py::test_full_lifecycle_with_lane_e_gateway` (inside the full suite). YES→ACTED, exactly one ACTION_EXECUTING by the gateway, 1 dry-run effector call, 0 live.
- **Real-engine scoring + strict AT-1:** the lane D/E run with lane C's engine. Fixture items the engine scores MAYBE/PASS park or archive, so this run may execute no action. That is by design: the action path is covered above.
- **Lane G (07):** the independent `qa/` A1–A10 + G1–G4 re-run on lanes D/E is task G-04, reported on 07's branch.
