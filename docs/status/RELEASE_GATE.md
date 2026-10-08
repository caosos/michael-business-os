# Release gate: wave two (FAIL)

- **Run:** 2026-10-07 19:53 -0500
- **Command:** `.venv/bin/python -I tools/release_gate.py --fetch`
- **Mode:** DRY-RUN only. Throwaway local PostgreSQL 16.

## Lane heads tested

| Lane | Commit |
|---|---|
| 01-coordinator | `51dbd51` |
| 02-opportunity | `b9e8224` |
| 03-economics | `5ae60e4` |
| 04-state | `b943b44` |
| 05-governance | `4623747` |
| 06-communications | `5bf4304` |
| 07-marketing | `7342abc` |
| 01-coordinator (local HEAD) | `51dbd51` |

## Checks

| Check | Result | Time | Summary |
|---|---|---|---|
| frozen contracts (validate_contracts.py) | PASS | 0.4s | schemas checked: 15 |
| frozen contracts pinned (FROZEN.sha256.json) | PASS | 0.1s | OK: 38 contract files match the pin |
| ADR-0010 vectors (reference self-test) | PASS | 0.0s | PASS receipt_chain: 2 receipts verified |
| full test suite (pytest) | FAIL (rc 1) | 422.9s | 2 failed, 340 passed in 421.56s (0:07:01) |
| suite floor (tools/release_gate_floor.json) | FAIL (rc 1) | 0.0s | passed 340 (min 250), skipped 0 (max 3), failed 2 |
| cross-lane interop (tools/interop_check.py) | PASS | 0.1s | 6/6 Python lanes CONFORM (vectors + rejections + vendored-copy identity) |
| installed lane packages == pushed heads (no stale installs) | FAIL (rc 1) | 0.0s | mbos_governance: 3 differ (gateway.py, schemas/policy.schema.json, spine_adapter.py), 2 missing, 0 extra () |
| lane D/E ACTION path (real gateway, follow-up, PANIC drill, live effector rows must be 0 and >=2 calls) | PASS | 5.8s | effector calls 2 (live 0) · executed 2 · follow-up {'policy_denied': False, 'executed_receipts': 2, 'second_request': True, 'concurrent': {'accepted': 1, 'refused': ['DecisionRefused', 'DecisionRefused', 'DecisionRefused', 'DecisionRefused', 'DecisionRefused'], 'live_pending': 1}} · panic drill True · chain ok True |
| lane D/E e2e + strict AT-1 (03 engine, 05 gateway, 04 schema) | PASS | 4.2s | chain 61 ok=True · reference 61 receipts verified · effector 0 (live 0) · contract errors 0 · AT-1 {'ok': True, 'drift_count': 0, 'weak_receipt_count': 0, 'items': 4} · final {'drywall_repair': 'RESEARCHING', 'mower': 'RESEARCHING', 'trailer': 'RESEARCHING', 'smart_home_install': 'RESEARCHING'} |

## Coverage notes

- **Action path with 05's real gateway on lane D:** `tests/integration/test_spine_on_lane_d.py::test_full_lifecycle_with_lane_e_gateway` (inside the full suite). YES→ACTED, exactly one ACTION_EXECUTING by the gateway, 1 dry-run effector call, 0 live.
- **Real-engine scoring + strict AT-1:** the lane D/E run with lane C's engine. Fixture items the engine scores MAYBE/PASS park or archive, so this run may execute no action. That is by design: the action path is covered above.
- **Lane G (07):** the independent `qa/` A1–A10 + G1–G4 re-run on lanes D/E is task G-04, reported on 07's branch.
