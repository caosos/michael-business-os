# Receipt — READY_QUEUE B-13: lane-B Deduper on the spine path (relist + pHash via A-14 context)

- **Date:** 2026-10-07 · **Actor:** Agent 02 · **Task source:** READY_QUEUE @ agent-01 `a910ad9` (B-13), plus Agent 01's dispatch.
- **Inputs:** `mbos` @ `a910ad9`: `interfaces.Deduper` with `context`, `NormalizedListing.match_hints`, `spine.ingest`. Installed read-only from `git archive`.
- **External effects:** none.

## Acceptance: "02's corpus through 01's spine `ingest`: F2 0.00% missed, 0 false merges" — MET (FACT)
- `tests/test_b13_spine_dedup.py::test_corpus_through_spine_f2_zero_missed_zero_false_merges`: 7 days → real `spine.ingest` on PG16 → **0.00% missed, 0 false merges, 38/38**.
- First run: **2.56% missed** (1 relist). Root cause: the price band in the blocking key, $1,627 → $1,497 across 1500. Fixed by coarsening the key to `category|state`.
- Also fixed: the F2 missed-rate formula, which could be offset by false merges (observed −2.7% in the photo-less run). It now counts extra Items per object.
- Deduper edge tests: relist, original still listed, unknown fetch, other seller, > 14 days, cross-source, pre-A-14 call.
- Full suite: **171 passed**.
- Not run: `spine_d` (lane-D backend). Its Deduper call is identical by code reading. Not filled on the spine path: `normalized.images` (spine artifact hook needed).
