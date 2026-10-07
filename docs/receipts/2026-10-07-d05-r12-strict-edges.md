# Receipt: D-05 (R12 strict item edges)

- Timestamp: 2026-10-07T17:26:35Z
- Agent: 04
- Inputs:
  - READY_QUEUE @ `0d107df` (D-05, P0)
  - Agent 01's dispatch (R12 re-affirmed)
  - `origin/research/agent-01-coordinator` @ `c0c0a69`: `src/mbos/state_machine.py` (ITEM_TRANSITIONS) and `tests/integration/test_state04_adapter.py::test_r12_item_edges_match_lane_d`

## Action
`state/migrations/0006_r12_strict_item_edges.sql` does two things:
- deletes NORMALIZED→SCORED, HELD→APPROVED, LEARNED→ARCHIVED and LEARNED→FAILED
- sets LEARNED back to terminal

ACTED→AWAITING_APPROVAL is kept.

## Results (FACT)
- `pytest`: 138 passed. `test_r12_strict_item_edges` replaces the 0005 accommodation test.
- An existing 0005 database (180-receipt seeded chain) upgraded with `migrate`:
  - 0006 was applied with its own CONFIG_VERSION_BUMPED receipt
  - `verify_chain`: OK, 180 receipts
- The live `mbos.item_state_transitions` set **equals** 01's `ITEM_TRANSITIONS` (41 edges). That is the exact assertion of `test_r12_item_edges_match_lane_d`.
