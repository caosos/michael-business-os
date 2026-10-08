# Receipt: P-03-15 plan_from_db proven on lane D PostgreSQL 16
Provenance: DRY-RUN, throwaway pgserver cluster, no external action. Sources: `git archive origin/research/agent-04-state` (migrations 0017 `capital_fund`, `set_mission`, `v_mission_current`, `capital_position_document`, `v_item_documents`), coordinator `mbos.mission.plan_errors`, lane helper `economics/tests/lane_d.py`.
- Added `economics/tests/test_mission_feed_lane_d.py` (no source change). One sequential test on a real PG16 cluster with 04's schema:
  1. Empty DB -> `UNKNOWN`, no legs, unknowns list mission/scored_items; `plan_errors` == [].
  2. Approver login (`mbos_operator_ui`) sets a mission -> `DO_NOT_SPEND`, no legs, ledger listed as unfunded.
  3. Approver funds $2,000 via `mbos.capital_fund`; 4 scored goldens (3 YES, 1 MAYBE) written via `StateStore` -> `DEPLOY` plan, `plan_errors` == [], every leg's `scorecard_id` equals the id stored in `v_item_documents`, and the plan's ledger comes from `capital_position_document()` (principal/available 2000).
- Result: with coordinator `mbos` + contracts + 04 state: 369 passed, 2 skipped, 0 failed. Without the env: 349 passed, 22 skipped, 0 failed (lane-D tests skip, never fail).
- FACT: mission period matters: goldens have days_to_cash 10-22, so a 7-day period yields `HOLD` with no legs (nothing lands in the week). The test uses a 30-day period. Mission values (target 1500, 30 h, bankroll 2000) are test fixtures, not Michael's.
