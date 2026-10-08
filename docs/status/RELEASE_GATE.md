# Release gate: wave two (PASS)

- **Run:** 2026-10-08 11:40 -0500
- **Command:** `.venv/bin/python -I tools/release_gate.py --fetch`
- **Mode:** DRY-RUN only. Throwaway local PostgreSQL 16.

## Lane heads tested

| Lane | Commit |
|---|---|
| 01-coordinator | `818a8ed` |
| 02-opportunity | `55a7e19` |
| 03-economics | `1262a85` |
| 04-state | `4a11f1b` |
| 05-governance | `44a0fb2` |
| 06-communications | `3a30680` |
| 07-marketing | `6428267` |
| 01-coordinator (local HEAD) | `818a8ed` |

## Checks

| Check | Result | Time | Summary |
|---|---|---|---|
| git fetch origin (the gate must compare against REAL pushed heads) | PASS | 0.0s | ok |
| frozen contracts (validate_contracts.py) | PASS | 0.4s | schemas checked: 15 |
| frozen contracts pinned (FROZEN.sha256.json) | PASS | 0.0s | OK: 38 contract files match the pin |
| ADR-0010 vectors (reference self-test) | PASS | 0.1s | PASS receipt_chain: 2 receipts verified |
| full test suite (pytest) | PASS | 249.4s | 461 passed in 248.28s (0:04:08) |
| suite floor (tools/release_gate_floor.json) | PASS | 0.0s | passed 461 (min 250), skipped 0 (max 3), failed 0 |
| cross-lane interop (tools/interop_check.py) | PASS | 0.2s | 6/6 Python lanes CONFORM (vectors + rejections + vendored-copy identity) |
| installed lane packages == pushed heads (no stale installs) | PASS | 0.0s | identical: mbos_economics 36 files vs research/agent-03-economics; mbos_governance 29 files vs research/agent-05-governance |
| bankroll canon (cash caps <= protected principal) | PASS | 0.0s | all lane cash caps <= $500 |
| lane D/E ACTION path (real gateway, follow-up, PANIC drill, live effector rows must be 0 and >=2 calls) | PASS | 4.8s | login ['mbos_dbos', False] · effector calls 2 (live 0) · executed 2 · follow-up {'policy_denied': False, 'executed_receipts': 2, 'second_request': True, 'concurrent': {'accepted': 1, 'refused': ['DecisionRefused', 'DecisionRefused', 'DecisionRefused', 'DecisionRefused', 'DecisionRefused'], 'live_pending': 1}} · panic drill True · chain ok True |
| lane D/E e2e + strict AT-1 (03 engine, 05 gateway, 04 schema) | PASS | 3.4s | chain 67 ok=True · reference 67 receipts verified · login mbos_dbos (superuser=False) · effector 0 (live 0) · contract errors 0 · AT-1 {'ok': True, 'drift_count': 0, 'weak_receipt_count': 0, 'items': 4} · final {'trailer': 'RESEARCHING', 'mower': 'RESEARCHING', 'drywall_repair': 'RESEARCHING', 'smart_home_install': 'RESEARCHING'} |

## Coverage notes

- **Action path with 05's real gateway on lane D:** `tests/integration/test_spine_on_lane_d.py::test_full_lifecycle_with_lane_e_gateway` (inside the full suite). YES→ACTED, exactly one ACTION_EXECUTING by the gateway, 1 dry-run effector call, 0 live.
- **Real-engine scoring + strict AT-1:** the lane D/E run with lane C's engine. Fixture items the engine scores MAYBE/PASS park or archive, so this run may execute no action. That is by design: the action path is covered above.
- **Lane G (07):** the independent `qa/` A1–A10 + G1–G4 re-run on lanes D/E is task G-04, reported on 07's branch.
