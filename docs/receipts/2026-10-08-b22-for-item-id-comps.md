# Receipt: B-22 — comps entered FOR an Item (F-108)

- Task: B-22 (READY_QUEUE, origin/research/agent-01-coordinator). DRY-RUN; no external calls.
- Change (`src/mbos_discovery/comps.py`): manual comp entries accept `for_item_id` (stored on the comp record only when set). `candidate_comps` puts a comp paired to the exact Item first and skips the category/window/similarity cuts. A comp paired to another Item is excluded. New optional `unmatched=` list receives `{comp_id, title, reason}` for every dropped comp, and `unmatched_gap_text()` renders the gap line.
- Provenance: the comp keeps its human FACT provenance (entered_by) and raw_ref. The pairing itself is the human's input, not an inference.
- Example: "Generic / 55in LED TV $92" entered with `for_item_id` of the TV now matches regardless of category or title. An unpaired, dissimilar comp is listed with its reason.
- Contract for Agent 06 (F-31): write `for_item_id` = Item `item_id` into the manual comp JSON.
- Test: `tests/test_c04_comps.py::test_f108_*`. Suite: 312 passed, 0 failed.
