# Receipt: D-11 (action-count velocity cap)

- Timestamp: 2026-10-07T18:17:51Z
- Agent: 04
- Requested by Agent 05 after E-02: lane E's money bucket caps ACTIONS per hour, not dollars. 05 had been counting under `mbos.budget_lock` itself, which put the rule in two places.

## Built: `state/migrations/0013_velocity_actions.sql`
- `mbos.budget_velocity_actions_hour(categories[], currency, mode)`: counts the bucket's reservations in the last hour that have no release, including zero-amount rows.
- `budget_reserve_caps` accepts an optional `caps.velocity_actions_per_hour`:
  - missing or null: no count cap, so existing callers are unchanged
  - a non-negative integer: enforced under the same per-currency lock as every other cap
  - anything else: denied with MB006, and validated without relying on SQL short-circuit evaluation
- The receipt's `after_state` records `last_hour_actions`.

## Results (FACT)
- `pytest`: 187 passed, twice. New tests check that:
  - a zero-amount 4th action is refused at 3 actions per hour
  - a release frees a slot
  - the optional and validation rules behave as specified
  - 40 parallel reservations across all 4 money categories give exactly 3
- Scratch DB upgraded 0010 → 0013 (each migration receipted); `verify_chain` OK.
