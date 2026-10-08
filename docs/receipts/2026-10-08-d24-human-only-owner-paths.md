# Receipt: D-24 (close the agent_write exemption in `_require_human_owner`)

- Timestamp: 2026-10-08
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue row D-24; `state/migrations/0018`, `0019` of this branch.
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only; nothing persistent, nothing contacted.

## Built
`state/migrations/0020_human_only_owner_paths.sql`, `state/tests/test_human_only_owner_paths.py` (7 tests).
- `mbos._require_human_owner` no longer exempts `agent_write` members. `set_mission`, `capital_fund`, `capital_withdraw`, `set_campaign`, `cancel_campaign` need actor.type human with a non-empty id for every session (42501 otherwise). `record_outcome` is untouched (its 0018 rule lives inline).

## Acceptance
- FACT: as the real `mbos_dbos` login (via `provision()`), each of the five functions refuses agent / system / blank-id / id-less / empty actors; no capital or campaign rows written.
- FACT: `mbos_dbos` with a human actor passes the guard (it is an approver member); the Operator UI login (`mbos_operator_ui`) human path still works and `verify_chain` is OK.
- FACT: health `cd state && .venv/bin/python -m pytest`: **262 passed, 1 skipped, 0 failed** (255 + 7).
- UNK: 01's gate was not run here; it is expected to be unaffected because it only calls these paths with human actors, if at all.

## Limits
- INFER: the DB still cannot tell two humans apart; the UI must pass the authenticated author (R14).
