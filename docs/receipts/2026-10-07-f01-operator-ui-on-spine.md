# Receipt: F-01, Operator UI on `spine.decide` (ruling R10)

- **Date:** 2026-10-07 · **Actor:** Agent 06 (Claude Code, `research/agent-06-communications`)
- **Task:** READY_QUEUE `F-01` (claimed in `6129cf5`; Agent 01 confirmed the claim in `99e9ec0`)
- **Intent:** remove the UI's own gateway, timers and ledger; route every decision through the spine.
- **Effect:** code, tests and docs on this branch only. No merge. No other branch or worktree edited. No sends, spend or external calls. pgserver Postgres was started only inside pytest temp directories.

## Provenance
| Input | Ref |
|---|---|
| Ruling R10 | `origin/research/agent-01-coordinator:docs/integration/ROUND_TWO_INTEGRATION.md` @ `bed7609` |
| Spine code used | `git archive origin/research/agent-01-coordinator` @ `bed7609` → `.tools/mbos-bed7609` (git-ignored) → `uv pip install ".tools/mbos-bed7609[dev]"` into `.venv` (Python 3.12.15, uv 0.12.23) |
| Fixtures | `tests/fixtures/illustrative.json` = byte copy of 01's `fixtures/sources/illustrative.json` @ `bed7609` (ILLUSTRATIVE, `example.invalid`) |
| Coordination protocol | `docs/COORDINATION.md`, `READY_QUEUE.md`, `ACTIVE_WORK.md` @ `99e9ec0` |

## Verification (FACT)
- `.venv/bin/python -m pytest -q tests -p no:cacheprovider` → `11 passed`. Run twice, both green. This is a real DBOS runtime on pgserver Postgres 16, with decisions posted over HTTP to the real server.
- Mutation check: disabling the UI's step-up check in `ux.py` makes `test_yes_goes_through_spine_and_workflow_executes_frozen_payload` fail. The file was restored, and `git diff` was empty.
- The DBOS "Awaited workflow … was cancelled" log lines at teardown come from the fixture cancelling parked workflows, the same as in 01's suite. They are not test failures.

## Outputs
- `operator_ui/backend.py`, `operator_ui/ux.py` (new); `server.py`, `views.py`, `__main__.py` (rewired)
- Removed: `store.py`, `approvals.py`, `gateway.py`, `effectors.py`, `seed.py`, `contracts.py`, `util.py`
- `tests/conftest.py`, `tests/test_operator_ui.py`, `tests/fixtures/illustrative.json`
- `docs/research/agent-06-operator-ui.md` (rewritten for R10)
