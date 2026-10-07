# Receipt: D-08 (pgvector rebuildable index, acceptance D3)

- Timestamp: 2026-10-07T17:54:43Z
- Agent: 04
- Task: READY_QUEUE D-08

## Built
- `state/migrations/0010_vector_index.sql`:
  - `mbos.item_embeddings`: a projection keyed by (item_id, model) with an MBOS-CJSON-1 content_hash
  - an HNSW cosine index
  - `mbos.similar_items()`
  - grants: readers query, agent_write refreshes, and only the owner can drop or rebuild
- Bootstrap and test harness: the superuser creates pgvector 0.6.2 in schema `mbos_ext`. The migration refuses to run without it.
- `state/mbos_state/vector_index.py`:
  - `refresh`, `rebuild`, `verify`, `search`
  - `HashEmbedder` (mbos-hash-embed v1): deterministic, offline, no LLM spend

## Results (FACT)
- `pytest`: 176 passed, twice. The D3 tests passed three more times on their own. `tests/test_vector_index.py` checks:
  - **D3:** after drop + delete + rebuild, rows are byte-identical, exact top-5 results are identical, and HNSW results (forced and proven by EXPLAIN) equal the ground truth before and after.
  - the similarity ranking is meaningful
  - drift detection, and that refresh is incremental (exactly 2 rows rewritten)
  - privileges
  - rebuilding leaves the chain head and the items untouched
- Note: HNSW returns ties (orthogonal items, distance 1.0) in no defined order, so the comparisons are set-wise over the whole table with (distance, item_id) sorting.
- Live: `bootstrap.sh` re-run on the scratch cluster installed pgvector and applied 0010 (receipted; `verify_chain` OK, 184 receipts). There, refresh indexed 12 items with no drift, and rebuild gave identical results.
