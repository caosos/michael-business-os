# Release gate: wave two (PASS)

- **Run:** 2026-10-07 20:41 -0500
- **Command:** `.venv/bin/python -I tools/release_gate.py --fetch`
- **Mode:** DRY-RUN only. Throwaway local PostgreSQL 16.

## Lane heads tested

| Lane | Commit |
|---|---|
| 01-coordinator | `bc0e8d8` |
| 02-opportunity | `543d939` |
| 03-economics | `0f109e0` |
| 04-state | `cf3bd8c` |
| 05-governance | `4f12ab7` |
| 06-communications | `e9281dd` |
| 07-marketing | `52dff65` |
| 01-coordinator (local HEAD) | `bc0e8d8` |

## Checks

| Check | Result | Time | Summary |
|---|---|---|---|
| git fetch origin (the gate must compare against REAL pushed heads) | PASS | 0.0s | ok |
| frozen contracts (validate_contracts.py) | PASS | 0.4s | schemas checked: 15 |
| frozen contracts pinned (FROZEN.sha256.json) | PASS | 0.1s | OK: 38 contract files match the pin |
| ADR-0010 vectors (reference self-test) | PASS | 0.0s | PASS receipt_chain: 2 receipts verified |
| full test suite (pytest) | PASS | 211.6s | 415 passed in 210.49s (0:03:30) |
| suite floor (tools/release_gate_floor.json) | PASS | 0.0s | passed 415 (min 250), skipped 0 (max 3), failed 0 |
| cross-lane interop (tools/interop_check.py) | PASS | 0.2s | 6/6 Python lanes CONFORM (vectors + rejections + vendored-copy identity) |
| installed lane packages == pushed heads (no stale installs) | PASS | 0.0s | identical: mbos_economics 33 files vs research/agent-03-economics; mbos_governance 29 files vs research/agent-05-governance |
| lane D/E ACTION path (real gateway, follow-up, PANIC drill, live effector rows must be 0 and >=2 calls) | PASS | 5.2s | effector calls 2 (live 0) · executed 2 · follow-up {'policy_denied': False, 'executed_receipts': 2, 'second_request': True, 'concurrent': {'accepted': 1, 'refused': ['DecisionRefused', 'DecisionRefused', 'DecisionRefused', 'DecisionRefused', 'DecisionRefused'], 'live_pending': 1}} · panic drill True · chain ok True |
| lane D/E e2e + strict AT-1 (03 engine, 05 gateway, 04 schema) | PASS | 3.2s | chain 61 ok=True · reference 61 receipts verified · effector 0 (live 0) · contract errors 0 · AT-1 {'ok': True, 'drift_count': 0, 'weak_receipt_count': 0, 'items': 4} · final {'trailer': 'RESEARCHING', 'drywall_repair': 'RESEARCHING', 'mower': 'RESEARCHING', 'smart_home_install': 'RESEARCHING'} |

## Coverage notes

- **Action path with 05's real gateway on lane D:** `tests/integration/test_spine_on_lane_d.py::test_full_lifecycle_with_lane_e_gateway` (inside the full suite). YES→ACTED, exactly one ACTION_EXECUTING by the gateway, 1 dry-run effector call, 0 live.
- **Real-engine scoring + strict AT-1:** the lane D/E run with lane C's engine. Fixture items the engine scores MAYBE/PASS park or archive, so this run may execute no action. That is by design: the action path is covered above.
- **Lane G (07):** the independent `qa/` A1–A10 + G1–G4 re-run on lanes D/E is task G-04, reported on 07's branch.
