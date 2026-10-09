# Receipt: D-32 (F-127: human-input research entries conform to the frozen Item schema)

- Timestamp: 2026-10-09
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue row D-32; migrations 0024, 0025; `state/tests/contracts-v1.0.0/item.schema.json` (research items: additionalProperties false).
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only.

## Built
- `state/migrations/0027_human_input_conform.sql`: `mbos.record_human_input` (same signature) now writes `{finding, field, basis, source_uri 'human:<id>', provenance_id}`. `finding` is one canonical JSON string (`mbos.cjson`) of `{"value":..., "entered_by":"<id>"}` (canonical key order, so `entered_by` sorts first). The note text moves to the receipt reason.
- Second violation found and fixed: scope_override used basis `INFER`, not in the frozen `evidence_tag` enum; now `INFERENCE`.
- `record_attestation` (0024) already wrote no extra properties; unchanged.
- Backfill: none. Entries from 0025 are history (hash chain); re-recording the input appends a corrected entry. Old entries would still fail the schema on any database that already holds them.
- Tests: `test_record_human_input.py` updated; new `test_quote_override_and_attestation_keep_item_conformant` validates the whole item document against the frozen schema after a quote, a scope override and an attestation, then `verify_chain`.

## Acceptance
- FACT: health `cd state && .venv/bin/python -m pytest`: 324 passed, 1 skipped, 0 failed.
- INFER: `mbos audit` itself (coordinator package) was not run; the same frozen schema is validated in the test.
- NOTE for lane C readers: value and author are now read by `json.loads(entry["finding"])`.
