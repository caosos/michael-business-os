# Receipt: F-54 radius boundary, saved-search persistence, refused requests keep the last good choices (lane 06, DRY-RUN)

- Task: F-54 (ARYA-20261010-0551), base artifact F-53 `e1621cf`. No live reload, install, paid usage, credential or contact.
- Provenance: code diffs in `operator_ui/market_search.py`, `market_view.py`, `market_routes.py`; tests in `tests/test_market_f53.py`; browser evidence `tools/f54_browser.py` -> `docs/receipts/f54-screenshots/` (run-log.json, UTC 2026-10-10, headless Chrome, isolated instance).

## Defects confirmed and fixed
1. **Radius rounding (FACT):** `_card` did `round(haversine, 1)` and the filter used it, so a lot 50.04 mi away passed a 50 mi limit. Now the card keeps the real distance; only the display rounds. Test with the real haversine on the fixture lots fails on the old rounding (verified by reverting) and passes on the fix; the exact distance is inclusive, 0.001 mi below is excluded.
2. **Saved-search loss (FACT):** save/reload dropped min price, category focus, row order, broad mode and condition. They now ride in the campaign's `nice_to_have` (`min:`, `cat:`, `rows:`, `broad:`, `cond:`; the frozen schema has no field, same pattern as `exclude:`). Not saved, and the page says so: sort, view, closing date. A saved search still needs a max price (campaign rule). More than 12 words is refused loudly by the campaign parser, never silently cut.
3. **Prefs overwrite (FACT, found by 01):** a refused request (`radius=x`) replaced the stored `last` choices. Now only requests that pass `parse_query` validation are remembered; a refused one is told so and leaves the last good choices. Test: valid, invalid, plain load, new app instance = valid choices, no banner (fails on the old code, verified).

## Matrix
Six cases and three audits: see `docs/handoff/F-51-F-52-acceptance-matrix.md` (A04, A16, A17, B01, B12, B16, B18, B19, C07, C08). Honest downgrades: B01 PARTIAL (3 columns at 1648, not five-across), B12 PARTIAL (no real external click), C08 PARTIAL (diff review). The 921 px mobile first-card stays a disclosed limitation.

## Gates (final artifact, `tools/run_tests.sh`, 2026-10-10)
- Reference suite: 375 passed / 1 failed (`test_resale_f39`, socket timeout, known baseline, not /market).
- Lane D + E: 105 passed / 2 failed (`test_inputs_f32` KeyError 'value', known baseline).
- `tests/test_market_f53.py`: 35 passed.
- Live acceptance: NOT RUN (owner-gated reload).
