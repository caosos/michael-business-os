# Receipt P-03-17: plan_from_db skips malformed-scorecard Items
Tags: FACT / INFERENCE / UNKNOWN. DRY-RUN; no external action.

- **FACT:** `mission_feed.plan_from_documents` (used by `plan_from_db`) pre-validates each live scored Item with `mission._candidate`. An Item raising KeyError/TypeError/IndexError/ValueError/ArithmeticError/AttributeError (e.g. scorecard `derived` without `branches`) is dropped from the plan and named in `unknowns` as `item <id> skipped: malformed scorecard (<Err>: <msg>)`. The plan is never aborted.
- **FACT:** New test `test_malformed_scorecard_item_skipped_and_named`; `plan_errors` (Agent 01 `mbos.mission`, from `git archive origin/research/agent-01-coordinator`) returns `[]` for it.
- **Provenance:** files `economics/src/mbos_economics/mission_feed.py`, `economics/tests/test_mission_feed.py`; health: `PYTHONPATH=src:tests pytest tests -q` = 356 passed, 22 skipped.
- **INFERENCE:** a skipped Item can silently lower the plan's EV; surfaced only via `unknowns`.
