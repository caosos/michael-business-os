# Receipt — READY_QUEUE B-05: wake-event producer (lane B → A-08)

- **Date:** 2026-10-07 · **Actor:** Agent 02 · **Task source:** READY_QUEUE @ agent-01 `aa88e7a` (B-05), plus Agent 01's dispatch message.
- **Inputs:** `mbos.workflows.notify_event` / `WAKE_EVENTS`, `mbos.ledger.record_provenance` @ `aa88e7a` (installed read-only from `git archive`).
  - Illustrative trailer economics from 01's `fixtures/sources/illustrative.json` were used, test-only and labelled.
- **External effects:** none. Fixtures only; nothing executes. The test's own HOLD was closed with NO, recorded as "test cleanup", inside a throwaway pgserver database.

## Acceptance: "A HOLD with `wake_on=price_change` wakes from a 02 fixture re-sighting; it never executes" — MET (FACT)
- Test: `tests/test_b05_wake_events.py::test_hold_wakes_on_lane_b_price_change_and_never_executes`.
  - Real DBOS workflows on Postgres 16.2.
  - HELD → price drops from 950 to 800 at the source → re-discovery → delivery → AWAITING_APPROVAL.
  - The APPROVAL_REQUESTED intent names `price_change`.
  - Zero ACTION_EXECUTING or ACTION_EXECUTED receipts.
  - The evidence provenance is FACT.
- Mutation check: removing the `notify_event` call leaves the item HELD (the test fails).
- Unit tests cover first sighting, price change, `new_info` with changed fields, auction-ending once per end time, and outbox dedup across reloads. The standalone pipeline hook is tested too.
- Full suite: **128 passed, 0 skipped**.
