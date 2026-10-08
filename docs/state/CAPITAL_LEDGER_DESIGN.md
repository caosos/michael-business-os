# Capital ledger: design for D-18 (draft; waits on Agent 01's A-23 `mission.schema.json`)

- **Sources:** `docs/product/DEAL_SNIFFER_START_HERE.md` §1, ADR-0013, READY_QUEUE D-18/A-23.
- **Status:** DESIGN ONLY. Field names and invariants are adopted from A-23 when it is pushed, so nothing here is built yet.

## Model (from the owner direction)
- `mbos.mission`: the owner's weekly mission (`target_usd`, `period`, `hours_available` (nullable = UNKNOWN), `capital`). Append-only. A change is a new version row, receipted.
- `mbos.capital_ledger`: insert-only entries. Each entry carries `kind`, `amount`, `item_id`, `mode` (dry_run | live, as in `budget_ledger`), the receipt it was **derived from**, and provenance.
- `mbos.v_capital_position`: a pure fold over the entries, giving `protected_principal`, `earned_working_capital`, `capital_deployed`, `realized_profit` and `available_to_deploy`.

| Entry kind | Fed by | Effect |
|---|---|---|
| `fund` | Michael's owner-set bankroll ($500 protected principal) | protected_principal += amount |
| `deploy` | a committed acquisition / repair / material spend (`BUDGET_COMMITTED`) | available → deployed, **per item** |
| `return` | a closed flip: `OUTCOME_RECORDED` (`flip_sold`, `flip_unsold_salvaged`) | deployed principal for that item → back to available |
| `profit` | the same closing outcome, when `revenue > total_cost` | realized_profit += profit; earned_working_capital += profit |
| `loss` | the closing outcome, when `revenue < total_cost` | reduces earned_working_capital first; any remainder reduces protected_principal and sets the **principal-impaired flag** |

## Properties the database should hold
1. Insert-only, and each entry is written in the same transaction as its receipt. No entry without a receipt.
2. **Replay reproduces the position:** `mbos.capital_position_replay()` rebuilds the position from `receipts` alone, and a test asserts that it equals `v_capital_position`.
3. `available_to_deploy` can never go negative: a `deploy` that would overdraw is refused (fail closed). It is checked under a lock, like the budget caps.
4. Principal returns exactly once per item (a unique key on the item's closing entry).
5. Dry-run accounting only in wave one: `live` entries are CHECKed to 0, like `budget_ledger`.

## Questions for Agent 01 (needed to finalise A-23)
1. **Which pool funds a deployment?** The direction says to "increasingly operate from earned profits while preserving original principal." My default: spend `earned_working_capital` first, then protected principal. Please confirm.
2. **A loss that exceeds earned capital:** does it permanently reduce `protected_principal`, or is it tracked as a drawdown to be rebuilt? My default is a real reduction plus a flag.
3. **Which receipts feed `deploy`:** `BUDGET_COMMITTED` (category purchase or repair), or an explicit new receipt type? Real money is $0 in wave one, so these are dry-run planning entries.
4. **Per-item principal:** may one item have several `deploy` entries (acquisition plus repair), all returned on close?
5. **Currency and rounding:** USD only, `numeric(14,2)`. Sub-cent amounts are not meaningful for capital.
