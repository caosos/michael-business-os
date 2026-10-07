# Release gate: wave two (PASS)

- **Run:** 2026-10-07 18:19 -0500
- **Command:** `.venv/bin/python -I tools/release_gate.py --fetch`
- **Mode:** DRY-RUN only. Throwaway local PostgreSQL 16.

## Lane heads tested

| Lane | Commit |
|---|---|
| 01-coordinator | `526489a` |
| 02-opportunity | `bd5076b` |
| 03-economics | `3d6212c` |
| 04-state | `c97ba6b` |
| 05-governance | `4e3c10f` |
| 06-communications | `8b10212` |
| 07-marketing | `9a790c5` |
| 01-coordinator (local HEAD) | `526489a` |

## Checks

| Check | Result | Time | Summary |
|---|---|---|---|
| frozen contracts (validate_contracts.py) | PASS | 0.3s | schemas checked: 10 |
| ADR-0010 vectors (reference self-test) | PASS | 0.0s | PASS receipt_chain: 2 receipts verified |
| full test suite (pytest) | PASS | 187.2s | 234 passed in 186.22s (0:03:06) |
| cross-lane interop (tools/interop_check.py) | PASS | 0.1s | 6/6 Python lanes CONFORM (vectors + rejections + vendored-copy identity) |
| installed lane packages == pushed heads (no stale installs) | PASS | 0.0s | identical: mbos_economics 29 files vs research/agent-03-economics; mbos_governance 24 files vs research/agent-05-governance |
| lane D/E e2e + strict AT-1 (03 engine, 05 gateway, 04 schema) | PASS | 3.7s | chain 60 ok=True · reference 60 receipts verified · effector 0 (live 0) · contract errors 0 · AT-1 {'ok': True, 'drift_count': 0, 'weak_receipt_count': 0, 'items': 4} · final {'smart_home_install': 'ARCHIVED', 'mower': 'ARCHIVED', 'trailer': 'RESEARCHING', 'drywall_repair': 'RESEARCHING'} |

## Coverage notes

- **Action path with 05's real gateway on lane D:** `tests/integration/test_spine_on_lane_d.py::test_full_lifecycle_with_lane_e_gateway` (inside the full suite). YES→ACTED, exactly one ACTION_EXECUTING by the gateway, 1 dry-run effector call, 0 live.
- **Real-engine scoring + strict AT-1:** the lane D/E run with lane C's engine. Fixture items the engine scores MAYBE/PASS park or archive, so this run may execute no action. That is by design: the action path is covered above.
- **Lane G (07):** the independent `qa/` A1–A10 + G1–G4 re-run on lanes D/E is task G-04, reported on 07's branch.
