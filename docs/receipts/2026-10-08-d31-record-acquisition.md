# Receipt: D-31 (Michael records an off-system purchase; capital deploys then; F-115 duplicate close)

- Timestamp: 2026-10-08
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue row D-31 (F-114 ruling, F-115); migrations 0017 (capital ledger), 0021, 0023 (record_outcome), 0024/0025 (owner-only definer pattern); `docs/state/CAPITAL_LEDGER_DESIGN.md`.
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only. Nothing was bought or spent.

## Built
- `state/migrations/0026_record_acquisition.sql`
  - `mbos.record_acquisition(item_id, amount_usd, note, actor, provenance_ids, idempotency_key)`: SECURITY DEFINER, EXECUTE only to `owner_channel`. Needs an owner_channel session (42501), a human actor with an id (42501), `provenance_ids[1]` a human provenance naming that human, a note, and an amount 0.01..10,000,000 with at most 2 decimals (MB004).
  - It writes, atomically: a purchase action request (`money.purchase`, payload `owner_acquisition`) with a human ACTION_PROPOSED, moved to `executed`, and a dry-run `BUDGET_COMMITTED` receipt (category purchase, USD, human actor). The existing 0017 trigger turns the receipt into a `deploy` entry.
  - Over `available_to_deploy`, or an unfunded ledger, is refused (MB006) and everything rolls back. Idempotent on the key.
  - Needed plumbing: transition `drafted -> executed` with an empty role list (only the definer/owner can use it), and `areq_require_receipt` also accepts BUDGET_COMMITTED as the receipt for that move. The receipt contract is unchanged (BUDGET_COMMITTED already requires an action request, hence the request).
  - F-115: `record_outcome` refuses (MB006) a closing outcome for an item whose capital is already closed, via the definer helper `_capital_item_closed`. Idempotent replays still return the first result. The ledger already ignored it silently; now the caller is told.
- Tests: `state/tests/test_record_acquisition.py` (11 cases, real `mbos_operator_ui` and `mbos_dbos` roles). `test_capital_ledger.py::test_one_close_per_item...` updated: the second close is now refused instead of silently ignored.

## Acceptance
- FACT: UI login records $120 on a $500 ledger: available 500 -> 380, deployed 0 -> 120; close at revenue 200 returns the 120 principal + 80 profit (available 580); `capital_verify` and `verify_chain` OK.
- FACT: over-available ($100.01 on $100) and unfunded refused, no action request left behind; duplicate close refused; agent/gateway roles and the real `mbos_dbos` login refused.
- FACT: health `cd state && .venv/bin/python -m pytest`: 323 passed, 1 skipped, 0 failed.
- NOTE for 01/06 (A-wrapper, F-33): pass a human provenance from `mbos.record_provenance` as `provenance_ids[1]`; the return value is the BUDGET_COMMITTED receipt id. The duplicate-close message contains "already closed".
