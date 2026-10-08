# Receipt: D-30 (owner UI login records Michael's typed inputs)

- Timestamp: 2026-10-08
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue row D-30; lane C `mbos_economics/inputs.py` `scope_overrides` (entry shape: field `scope_override:<block>.<field>`, numeric `value`, basis, `entered_by`, `prov_` provenance id); migration 0024 and its test.
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only.

## Built
- `state/migrations/0025_record_human_input.sql`
  - `mbos.record_human_input(item_id, kind, key, value, note, actor, provenance_ids, idempotency_key)`: SECURITY DEFINER, EXECUTE only to `owner_channel`. Owner_channel session and human actor with id (42501); `provenance_ids[1]` a human provenance naming that human, valid kind/key/value (MB004).
  - `scope_override`: key `rehab.{parts_cost,labor_hours,admin_hours,required_skills}` or `job.{labor_hours,materials_cost,admin_hours,required_skills}` (the set C-27 reads); numbers 0..10,000,000, skills a 1-20 array of non-empty strings. Entry field `scope_override:<key>`, basis INFER.
  - `quote`: key `amount_usd`, number > 0 and <= 1,000,000. Entry field `quote:amount_usd`, basis FACT.
  - Entry `{finding, field, value, basis, source_uri human:<id>, provenance_id, entered_by}` via `append_item_research`: receipted ITEM_STATE_CHANGED (human actor), idempotent on the key.
  - The 0024 guard counter now also covers `scope_override:` and `quote:`, so only the definer (table owner) can add those entries.
- Tests: `state/tests/test_record_human_input.py` (27 cases, real `mbos_dbos` and `mbos_operator_ui`).

## Acceptance
- FACT: UI login records both kinds; replay idempotent; entries readable by the reader role; `verify_chain` OK.
- FACT: real `mbos_dbos` refused the function and refused `append_item_research` / `update_item_doc` with `scope_override:`, `quote:` and `attestation:` entries; a `card.comps` enrichment still works.
- FACT: health `cd state && .venv/bin/python -m pytest`: 312 passed, 1 skipped, 0 failed.
- NOTE for 03/06/01: the quote entry `quote:amount_usd` is not yet read by the engine (C-28). Callers must pass a human provenance from `mbos.record_provenance` as `provenance_ids[1]`.
