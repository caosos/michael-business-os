# Receipt: C-04, sold-comps feed (Agent 03 lead, Agent 02 sources)

- **Date:** 2026-10-07
- **Task:** `C-04` (READY_QUEUE @ agent-01 `0d107df`). Claimed at `688f852`. Code at `882c726`.
- **Scope:** this branch only. Read-only and fixture-first: no network code, no live calls.

## Hand-off with Agent 02 (agreed by cross-session message, 2026-10-07)
**Agent 02 owns the comps sources,** in `mbos_discovery.comps` on its branch:
- manual inbox
- eBay Marketplace Insights: fixture-first; live only with an approved keyset
- raw retention and comp de-duplication

It emits `SoldComp` records (`kind, price, sold_date, source, url, provenance_id, fetched_at, raw_ref, category, title, condition, location, currency`) plus one FACT Provenance record per comp.

**Agent 03 owns selection, the bundle and estimation.** 02 asked three questions, answered as follows:
- (a) The key is `price` only.
- (b) 03 routes `condition=parts` to `as_is_comps`.
- (c) 03 assembles the bundle through `build_comps_bundle` / `research_step`.

## Outputs
- `economics/src/mbos_economics/comps_feed.py`: `query_key`, `build_comps_bundle`, `load_fixture_comps`, `research_step`.
- `estimate.py`: one FACT `Item.research[]` entry per comp used, carrying the comp's own `provenance_id`, `source_uri` and `fetched_at`.
- `config/estimation-priors.json` **2026.10.1**:
  - `comps_sources` registry: mirrors ADR-02-0202, fail-closed; `ebay_browse` may report asking prices only.
  - `comps_query` fixed vocabulary.
  - 2026.10.0 is archived in `config/history/`.
- `tests/fixtures/comps/sold_comps.json`: 5 valid comps and 11 decoys, one per rule. `tests/test_comps_feed.py`: 13 tests.

## Acceptance evidence (FACT)
"A 02-fixture flip with comps advances RESEARCHING → SCORED with FACT-tagged comp provenance":
- **Item:** Agent 02's Conway 6x12 enclosed trailer (02 @ `7b4d9a8` pipeline output), set to RESEARCHING, plus the fixture comps.
- **Result:** `proposed_next_state = SCORED`, verdict MAYBE (composite 61.8).
  - Resale target $2,100: trimmed median of the 4 sold comps (2 eBay Insights, 1 more eBay, 1 manual).
  - As-is median $900, from the `parts` sale.
- **Provenance:** 5 FACT research entries, each with its own comp `provenance_id`. All persisted provenance validates against Provenance v1, and the scored Item validates against Item v1.0.0 and the 03 v1.1.0 schemas.
- **Replay:** the scored Item replays byte-identically.
- **Rejections:** all 11 decoys are rejected, each for its own rule (forbidden, unknown or kind-mismatched sources; stale or future dates; wrong category; EUR; missing or non-FACT provenance; vocabulary conflict; duplicate). Each rejection is reported with its reason.
- **Order independence:** reversing the input order gives the same bundle. The test caught a first-wins dedup bug; it is fixed by canonical ordering.
- **Suite:** 118 passed, 70 subtests (py3.12 + jsonschema); 118 OK, 6 skipped (py3.10 stdlib).

## Open items
- UNKNOWN: eBay Marketplace Insights is a restricted-access API. Live sold data needs eBay approval and a keyset (a Michael action item, same as 02's eBay runbook). Until then, real sold comps arrive through the **manual** source.
- INFERENCE: eBay sold prices are national, not local. Ask-to-sold ratios and LEARN calibrate that; the vocabulary limits type/size mismatch only.
