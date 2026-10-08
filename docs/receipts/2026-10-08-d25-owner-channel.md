# Receipt: D-25 (owner_channel role; F-80 / F-81 / F-83)

- Timestamp: 2026-10-08
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue row D-25; `state/migrations/0017`, `0019`, `0020`; `state/bootstrap/roles.sql`.
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only; nothing persistent, nothing contacted.

## Built
`state/migrations/0021_owner_channel.sql`, `state/bootstrap/roles.sql` (new NOLOGIN role `owner_channel`, granted only to `mbos_operator_ui`), `state/tests/test_owner_channel.py` (18 tests), `test_human_only_owner_paths.py` adjusted.
- `set_mission`, `capital_fund`, `capital_withdraw`, `set_campaign`, `cancel_campaign` (and the internal `_capital_owner_receipt`, `_campaign_revise`): EXECUTE revoked from `approver`, granted to `owner_channel`. `_require_human_owner` checks `pg_has_role(current_user,'owner_channel')` first, then the human-actor claim (second layer).
- INSERT on `mbos.mission` and `mbos.campaigns` moved from `approver` to `owner_channel`.
- `capital_entry_for`: fund/withdraw receipts need `owner_channel` for the writing session, so a forged receipt through `append_receipt` (granted to approver) is also refused.
- F-81: `mbos._campaign_validate` (owner/title non-empty strings, `max_price_usd` a number in [0, 1e12), category non-empty, keywords an array of strings, every string <= 200 chars). F-83: `set_campaign` refuses any revision of a CANCELLED campaign.

## Acceptance
- FACT: as the real `mbos_dbos` login (via `provision()`), all five functions are refused with a forged `{type:human,id:michael}` and a real provenance id; direct mission INSERT and a forged capital_fund receipt via `append_receipt` are refused; no ledger/campaign rows. `owner_channel` members = `mbos_operator_ui` only.
- FACT: as `mbos_operator_ui` fund, mission, set/cancel campaign work (withdraw is authorised, then refused for no earned capital) and `verify_chain` is OK.
- FACT: 13 bad campaign bodies refused, boundary values (price 0, 200-char title) accepted, resurrection of a CANCELLED campaign refused.
- FACT: health `cd state && .venv/bin/python -m pytest`: all green, 280 passed, 1 skipped, 0 failed (counted from the progress dots; the summary line was lost to a tail).
- UNK: 01's gate (mbos_dbos) was not run here. It never calls these five paths as an agent; any caller that did will now get 42501 by design.

## Limits
- INFER: `record_outcome` human closes (0018) still rely on approver membership for `mbos_dbos`; out of D-25 scope.
- INFER: existing clusters need `roles.sql` re-run (it creates `owner_channel` and the grant) before migration 0021.
