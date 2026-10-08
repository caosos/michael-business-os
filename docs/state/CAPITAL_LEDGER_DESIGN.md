# Capital ledger (D-18): as built, migration `0017_capital_ledger.sql`

- **Sources:** `docs/product/DEAL_SNIFFER_START_HERE.md` §1, ADR-0013, and Agent 01's `mission.schema.json` (A-23).
- **Rulings applied** (Agent 01, technical):
  - Earned capital funds deployments first, then protected principal.
  - A loss consumes earned capital first. The remainder is recorded as `principal_impairment` and flagged. `protected_principal` is never rewritten.
  - Entries come from existing receipt types, and they are tagged `dry_run`.
  - An item may have several deploy entries, and all of them are returned on close.
  - USD only, `numeric(14,2)`.
- **Invariants** (the schema, validated by `mbos.mission.ledger_errors`):
  - `available_to_deploy = protected_principal − principal_impairment + earned_working_capital − capital_deployed`
  - Impairment only exists while earned is 0.
  - Impairment does not exceed the principal.

## Objects
| Object | What it is |
|---|---|
| `mbos.mission` | The weekly mission. `weekly_target_usd` and `hours_available` may be NULL (UNKNOWN, never guessed). Versioned and insert-only. |
| `mbos.set_mission()` | Owner channel (approver) only. A revision is a new row. |
| `mbos.v_mission_current` | The latest mission in the schema's shape, with NULLs kept as NULL. |
| `mbos.capital_ledger` | Insert-only entries. **No role can insert**: they are derived from receipts by one trigger, and each cites its `source_receipt_id`. |
| `mbos.capital_fund()` / `capital_withdraw()` | Owner channel only. They write the receipt, and the trigger derives the entry. |
| `mbos.v_capital_position` | The position per mode. It is the schema's `capital_ledger` fields plus flags: `principal_impaired`, `overdrawn`, `open_items`, `unconfirmed_closing_outcomes`. |
| `mbos.capital_position_document()` | Exactly the schema's `capital_ledger` object, `principal_impairment` included. |
| `mbos.capital_replay()` / `capital_verify()` | Rebuild the entries from **receipts alone** with the same rule, and compare with the table. |

## How entries are derived (one rule, `mbos.capital_entry_for`)
| Receipt | Entry | Effect |
|---|---|---|
| `CONFIG_VERSION_BUMPED`, `entity_type` `capital_fund` | `fund` | protected_principal += amount |
| `CONFIG_VERSION_BUMPED`, `entity_type` `capital_withdraw` | `withdraw` | takes from earned only; refused beyond it |
| `BUDGET_COMMITTED`, category in `capital_deploy_categories` (purchase, money) | `deploy` (per item) | capital_deployed += amount; **refused** if it exceeds available |
| `OUTCOME_RECORDED`, kind in `capital_closing_kinds`, **human-recorded**, with realized numbers | `close` | principal returns (basis = the item's deployed sum), net goes to earned / realized |

The category and kind lists are data tables, so they change by migration, not by code.

Internally the ledger keeps one signed earned position **X** = Σ net − withdrawals. The schema's fields are
`earned_working_capital = max(X, 0)` and `principal_impairment = max(−X, 0)`, so impairment exists only while earned is 0.
A later profit therefore repairs the impairment first, since the invariant leaves it nowhere else to go.
Michael's own rebuild decision is an explicit `fund`.

## Safety
- **Capital cannot be minted by an agent.**
  - fund, withdraw and close need an approver-role session. This is the writing session's role, checked at insert time.
  - Close also needs a **human-recorded** outcome. Agent-reported closing outcomes move nothing and are counted in `unconfirmed_closing_outcomes`.
  - A forged receipt from any other role is refused (42501).
- **Fail closed:** a deploy over `available_to_deploy` is refused, and the budget commit and its receipt roll back.
- **Inactive until Michael funds it.** Until then nothing is accounted or refused, so existing budget flows are unchanged.
- **Dry-run accounting only** in wave one (CHECK on `mode`). Wave-one money is $0.
- Replay is insertion-role independent: `capital_verify` replays with the role gate off, so the verifier works for any reader.

## Known edges (honest)
- A loss larger than the item's deployed basis (costs that never went through the ledger) can push `available_to_deploy` below 0. The view sets `overdrawn` instead of hiding it.
- A closing outcome without realized numbers stays open and is listed under `open_items`.
- The `BUDGET_COMMITTED` receipt carries no mode, so deploys read it from `details.dry_run`. All entries are `dry_run` in wave one anyway.
