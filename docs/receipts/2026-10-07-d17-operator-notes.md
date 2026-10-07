# Receipt: D-17 (operator-note store)

- Timestamp: 2026-10-07T21:59:03Z
- Agent: 04
- Inputs (read-only):
  - Agent 03's note contract and loader at `research/agent-03-economics @ b41a0f8`
  - Agent 01's ruling, Option A
  - The loader was extracted with `git archive` into Agent 04's scratchpad and **used**, not copied into the repo.

## Built
- `state/migrations/0016_operator_notes.sql`: the table and its CHECKs, the human-provenance and same-transaction-receipt guards, entry, retraction and head resolution, the folded view, `operator_notes_document()`, and the grants. `StateStore` methods; `docs/state/OPERATOR_NOTES.md`.

## Results (FACT)
- `pytest`: 223 passed, twice. It is 24 passed and 1 skipped when Agent 03's loader is absent.
- **Acceptance with the real loader:** `python -m mbos_economics note check FILE` exits 0 on the database-rendered document, and `load_manual_notes` returns exactly the live notes.
- The `basis` hole was caught by the tests: the entry function had been silently storing a note claiming FACT as RECOMMENDATION. It now refuses.
- Live: the scratch DB upgraded 0013 → 0016 (each receipted), and `verify_chain` is OK at 190 receipts.
- Housekeeping: the scratch cluster's socket directory was recreated and removed again, and `/run/user/1001` is clean.
