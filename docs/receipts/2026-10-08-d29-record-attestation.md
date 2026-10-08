# Receipt: D-29 (owner UI login records Michael's attestation)

- Timestamp: 2026-10-08
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue row D-29; lane C convention `attestation:<key>` (`origin/research/agent-03-economics` `mbos_economics/inputs.py` `ATTEST_PREFIX`); coordinator `spine_d.record_attestation`; migrations 0015, 0021, 0023.
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only.

## Built
- `state/migrations/0024_record_attestation.sql`
  - `mbos.record_attestation(item_id, evidence_key, note, actor, provenance_ids, idempotency_key)`: SECURITY DEFINER, EXECUTE only to `owner_channel`. Requires an owner_channel session (42501), a human actor with an id (42501), a valid key/note (MB004), and `provenance_ids[1]` a human provenance naming that same human (MB004). Writes ONE research entry `{field: attestation:<key>, basis: FACT, source_uri: human:<id>, provenance_id}` via `append_item_research`; receipt ITEM_STATE_CHANGED with the human actor; idempotent on the key.
  - Guard trigger `ab_items_attestation_guard` on `mbos.items`: any write that adds an `attestation:` research entry is refused (42501) unless it runs as the table owner (inside the definer function). `agent_write` keeps `append_item_research`/`update_item_doc` for lane enrichments.
- Tests: `state/tests/test_record_attestation.py` (7 tests; real `mbos_dbos` via `provision()`, `mbos_operator_ui` via the owner store).

## Acceptance
- FACT: owner UI login records a receipted human attestation; replay is idempotent; the entry is in `items.doc.research` readable by the reader role (lane C input); `verify_chain` OK.
- FACT: real `mbos_dbos` is refused `record_attestation`, and refused appending/patching an `attestation:` entry directly via `append_item_research` and `update_item_doc`; a `card.comps` enrichment still works.
- FACT: health `cd state && .venv/bin/python -m pytest`: 292 passed, 1 skipped, 0 failed.
- UNK: 01's gate was not run here. NOTE for 01/06: lane C and this ruling use `attestation:<key>`, but coordinator `spine_d.record_attestation` (and its test) writes `attestation.<key>` and appends as agent_write; it must switch to calling `mbos.record_attestation` on the owner login (the new guard will refuse its direct append) and use the colon form.
