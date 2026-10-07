# Release gate: wave two (FAIL)

- **Run:** 2026-10-07 18:08 -0500
- **Command:** `.venv/bin/python -I tools/release_gate.py --fetch`
- **Mode:** DRY-RUN only. Throwaway local PostgreSQL 16.

## Lane heads tested

| Lane | Commit |
|---|---|
| 01-coordinator | `deec1d1` |
| 02-opportunity | `bd5076b` |
| 03-economics | `3d6212c` |
| 04-state | `c97ba6b` |
| 05-governance | `f10aabb` |
| 06-communications | `8b10212` |
| 07-marketing | `bb4bc04` |
| 01-coordinator (local HEAD) | `deec1d1` |

## Checks

| Check | Result | Time | Summary |
|---|---|---|---|
| frozen contracts (validate_contracts.py) | PASS | 0.3s | schemas checked: 10 |
| ADR-0010 vectors (reference self-test) | PASS | 0.0s | PASS receipt_chain: 2 receipts verified |
| full test suite (pytest) | PASS | 230.5s | 232 passed in 229.49s (0:03:49) |
| cross-lane interop (tools/interop_check.py) | PASS | 0.1s | 6/6 Python lanes CONFORM (vectors + rejections + vendored-copy identity) |
| installed lane packages == pushed heads (no stale installs) | FAIL (rc 1) | 0.0s | mbos_governance: 2 differ (policy.py, spine_adapter.py), 0 missing |
| lane D/E e2e + strict AT-1 (03 engine, 05 gateway, 04 schema) | PASS | 4.6s | chain 60 ok=True · reference 60 receipts verified · effector 0 (live 0) · contract errors 0 · AT-1 {'ok': True, 'drift_count': 0, 'weak_receipt_count': 0, 'items': 4} · final {'mower': 'ARCHIVED', 'drywall_repair': 'RESEARCHING', 'trailer': 'RESEARCHING', 'smart_home_install': 'ARCHIVED'} |

## Coverage notes

- **Action path with 05's real gateway on lane D:** `tests/integration/test_spine_on_lane_d.py::test_full_lifecycle_with_lane_e_gateway` (inside the full suite). YES→ACTED, exactly one ACTION_EXECUTING by the gateway, 1 dry-run effector call, 0 live.
- **Real-engine scoring + strict AT-1:** the lane D/E run with lane C's engine. Fixture items the engine scores MAYBE/PASS park or archive, so this run may execute no action. That is by design: the action path is covered above.
- **Lane G (07):** the independent `qa/` A1–A10 + G1–G4 re-run on lanes D/E is task G-04, reported on 07's branch.
