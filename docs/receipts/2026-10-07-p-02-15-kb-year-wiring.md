# Receipt — READY_QUEUE P-02-15: year-specific KB hits wired into the enrichment path

- **Date:** 2026-10-07 · **Actor:** Agent 02 (bounded worker) · **Task source:** READY_QUEUE P-02-15 (depends on P-02-14).
- **External effects:** none. DRY-RUN; no network, no listing fetched, nothing sent.
- **Code:** `src/mbos_discovery/enrichment.py::kb_hits(item, kb, match_hits, own_prov)`. Tests: `tests/test_p0215_kb_wiring.py` (8).
- **Provenance:** fixture KB entry and titles are hand-written (ILLUSTRATIVE, "Cub Cadet XT1"); no real bulletin or listing was read.

## Acceptance — MET
- `2018 Cub Cadet XT1 mower`, `'18 ...` and `... MY2018` each hit the 2018-specific entry. Each hit carries the entry's source provenance id (FACT about the bulletin) and a `year_read` datum: `basis: INFERENCE`, provenance = this lane's, note quoting the listing title and the matched text.
- `item_for_value_add` is the title-augmented copy to hand to Agent 03's `build_value_add`; test confirms the matcher agrees.
- A part number `1890` (also `1890A`, `MY1890`, `MY18-4420`) never matches; no model year read.
- A year outside an entry's coverage lands in `blocked` (UNKNOWN), never a hit.

## Not done / UNKNOWN
- `kb_hits` is not yet attached as a spine block: the spine has no recall/TSB block name (`ENRICHMENT_BLOCKS`), and the card's `value_add.model_specific_risks` is Agent 03's block. Whoever calls `build_value_add` should pass `item_for_value_add`. Proposed to Agent 01.

Health: `.venv/bin/python -m pytest -q` → 311 passed, 0 failed.
