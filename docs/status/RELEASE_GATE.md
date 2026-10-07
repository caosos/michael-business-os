# Release gate: wave two (PASS)

- **Run:** 2026-10-07 13:26 -0500
- **Command:** `.venv/bin/python -I tools/release_gate.py --fetch`
- **Mode:** DRY-RUN only. Throwaway local PostgreSQL 16.

## Lane heads tested

| Lane | Commit |
|---|---|
| 01-coordinator | `ca6d056` |
| 02-opportunity | `0dd506b` |
| 03-economics | `405cc77` |
| 04-state | `a08dd9f` |
| 05-governance | `0559bfa` |
| 06-communications | `e3b56d2` |
| 07-marketing | `862fc89` |
| 01-coordinator (local HEAD) | `ca6d056` |

## Checks

| Check | Result | Time | Summary |
|---|---|---|---|
| frozen contracts (validate_contracts.py) | PASS | 0.3s | schemas checked: 9 |
| ADR-0010 vectors (reference self-test) | PASS | 0.1s | PASS receipt_chain: 2 receipts verified |
| full test suite (pytest) | PASS | 107.8s | 158 passed in 106.87s (0:01:46) |
| cross-lane interop (tools/interop_check.py) | PASS | 0.2s | 6/6 Python lanes CONFORM (vectors + rejections + vendored-copy identity) |
| lane D/E e2e + strict AT-1 (03 engine, 05 gateway, 04 schema) | PASS | 3.2s | chain 53 ok=True · reference 53 receipts verified · effector 0 (live 0) · contract errors 0 · AT-1 {'ok': True, 'drift_count': 0, 'weak_receipt_count': 0, 'items': 4} · final {'trailer': 'RESEARCHING', 'drywall_repair': 'RESEARCHING', 'smart_home_install': 'ARCHIVED', 'mower': 'ARCHIVED'} |

## Coverage notes

- **Action path with 05's real gateway on lane D:** `tests/integration/test_spine_on_lane_d.py::test_full_lifecycle_with_lane_e_gateway` (inside the full suite). YES→ACTED, exactly one ACTION_EXECUTING by the gateway, 1 dry-run effector call, 0 live.
- **Real-engine scoring + strict AT-1:** the lane D/E run with lane C's engine. Fixture items the engine scores MAYBE/PASS park or archive, so this run may execute no action. That is by design: the action path is covered above.
- **Lane G (07):** the independent `qa/` A1–A10 + G1–G4 re-run on lanes D/E is task G-04, reported on 07's branch.
