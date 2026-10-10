# Receipt: F-57 /market wide-screen density (DRY-RUN)

## What changed (`operator_ui/market_view.py` CSS only, applies on /market; plus tools)
- `main` max-width 1060 -> 1900 px on /market; sidebar 230 -> 210 px; gallery grid `minmax(min(230px,100%),1fr)` (was 190 px): 5 across at 1648 px, 1 on a phone.
- "Operator UI" title hidden, banner/header/page-title padding shrunk; the 18-link nav stays (one line at 1648; a single horizontally scrolling line under 700 px instead of stacking).
- An empty row's "No matching known inventory" note spans the grid instead of wrapping in one narrow cell.
- Unchanged: strict filters, the closed unchecked section, honest login-gated photo tiles (no `<img>`, B19 title/link comparison still matches the cache).
- Tools: `tools/capture_market.py` (from Agent 01's branch; adds `MBOS_GSA_CACHE` override and a `cards_across_in_first_viewport` metric), `tools/serve_market_staging.py` (isolated loopback staging, stub store, scratch prefs). Test `tests/test_market_f57.py`.

## Evidence (real cache sha256 d02f3acc...a154ba7, 1,179 lots, as-of 2026-10-10T00:19:23Z; sidecar JSON per shot)
| shot | before `ab81bed` first card top | after `85c416d` first card top | after, cards across in first viewport |
|---|---|---|---|
| conway-1648 | 535 px | **367 px** (< 400) | **5** (Vehicles row, bottom of the viewport; Trailers row has only 3 real lots) |
| broader-1648 | 535 px | 367 px | 5 |
| conway-390 | 949 px (earlier run) / 949 | 768 px | 1 (unchanged single column, no horizontal overflow) |
Shots: `docs/receipts/f57-before/`, `docs/receipts/f57-after/`. B19: 12/12 checked cards match the cache, 81 optional links in cache; 19/19 broader, 268 optional.

## Honest limits
- The Conway search has only 3 trailer lots, so the first *row* shows 3 cards; the 5-across is the Vehicles row starting at ~872 px, partly below the fold in a 1000 px viewport (card tops visible). Not a claim that the first row has 4+.
- "Before" sidecars predate the across metric; their 3-across count is from the screenshot.
- Live :8766 not reloaded (owner-gated).

## Tests
Reference (resale_f39 deselected, known timeout): 377 passed, 0 failed (exit 0; includes 2 new). Lane D+E: 105 passed / 2 failed (known F-32 pair).
