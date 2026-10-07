# Receipt: D-10 (adopt 06's consent/DNC ledger into lane D)

- Timestamp: 2026-10-07T18:00:19Z
- Agent: 04
- Source (read-only): `origin/research/agent-06-communications` @ `19b0982`: `comms_spec/sql/0001_comms_ledger.sql`, `comms_spec/ledger.py`, `tests/test_comms_ledger.py`

## Built: `state/migrations/0011_comms_ledger.sql`
- **Compatibility:** schema `mbos_comms` with identical tables, columns, function and trigger names, so 06's `comms_spec.ledger` SQL runs unchanged.
- **Insert-only:** the error text still says "insert-only" (06's tests match on it), now with SQLSTATE MB001.
- **Lane-D additions:**
  1. `receipt_id` is a real FK, and it must be a receipt for the same `contact_ref` written **in the same transaction**, in the right direction (enabling = GRANT_CREATED, revocation or listing = GRANT_REVOKED).
  2. **Fail-safe asymmetry:** only `gateway` can record what *enables* a send (consent granted, DNC clear). Any writer can record STOP, revocation or a listing.
  3. **Raw contact values:** `contacts.value` is SELECT-able by `gateway` only, through column grants.

## Results (FACT)
- `pytest`: 182 passed, twice.
- `tests/test_comms_ledger.py` replays 06's own statements on lane D's schema:
  - flow; idempotent `register_contact`; raw values never in receipts; chain verifies
  - insert-only with 06's error text
  - event + receipt commit together, or neither
  - a stale, foreign or wrong-direction receipt is refused
  - asymmetry and column privileges

## Not yet met (honest)
The queue acceptance is "06's F-07 tests pass on lane D's schema". 06's suite runs through Agent 01's spine, which still writes to the reference DDL until A-01 phase 2 lands. So D-10's final acceptance is **Blocked on A-01 phase 2**.

Notes for 06 when that happens:
- On a lane-D database, `ensure_schema()` must skip when `to_regclass('mbos_comms.contacts')` is not null: the app role cannot (and must not) re-create or replace owner objects.
- `register_contact` filters on `value`, so it needs the `gateway` privilege. `mbos_dbos` has it.
