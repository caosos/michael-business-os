# Receipt: F-58 final staging closeout (DRY-RUN)

Provenance: queue row F-58 (ADDED BY 01, ARYA-20261010-0703). Run on lane 06 head `3a28c64` (committed; `git status` clean before the capture). No live reload, installs, spend, contact or credentials. Live :8766 NOT RUN.

## 1. Capture and relabel
- `tools/capture_market.py` sidecar/docstring wording fixed: inventory = REAL cached GSA file; decision store = STUB (`serve_market_staging.py` uses `StubStore`). The old "no stub store" claim was wrong; no real-persistence claim comes from stub runs.
- `docs/receipts/f58-real-cache-screenshots/` (cache sha256 d02f3acc...a154ba7, 1,179 lots, as-of 2026-10-10T00:19:23Z, read from the coordinator checkout via `MBOS_GSA_CACHE`):
  conway-1648: 12/12 checked cards match cache, 81 optional links in cache, first card top 367 px, 5 across, no overflow; conway-390: 12/12, 81, top 768, 1 across, no overflow; broader-1648: 19/19, 268, top 367, 5 across.
  The 5 across at 1648 is the Vehicles row at the bottom of the viewport; the Conway Trailers row shows 3 (only 3 real lots).

## 2. Test results (150 s timeout per file; reference mode and `MBOS_UI_LANE_D=1`)
| scope | result |
|---|---|
| all 33 `tests/test_*.py` files, each alone, both modes | PASS (rc 0) every file, including `test_resale_f39.py` 4 passed alone (6-8 s) |
| `tests/lane_d` | 2 FAILED / 105 passed: BASELINE F-32 pair (`test_inputs_f32.py::test_quote_on_the_drywall_lead_moves_it_to_yes_over_http`, `::test_scope_override_on_an_unknown_category_item_moves_it_over_http`) |
| whole `pytest tests` (362 s) | 380 passed / 1 FAILED: BASELINE `test_resale_f39::test_item_moves_intake_to_sold_with_receipt_and_simulated_is_never_earned` (passes alone, fails in the combined run; cause not re-diagnosed, not claimed resolved) |
New failures: none. TIMEOUT: none. Totals for the JSON line: 380 passed + 105 passed in the two runs above; 3 baseline failures (resale_f39 in combined run, F-32 pair).

## 3-4. Matrix
`docs/handoff/F-51-F-52-acceptance-matrix.md` updated: F-58 header block, F56/F57 rows, B16 downgraded to UNVERIFIED (count-only), scope notes on A17 and B19, B01/B12/C08 PARTIAL, mobile limitation (nav scrolls, title hidden; price/title legibility on a phone not separately evidenced). Sync: the coordinator branch is another lane's, so lane 06 cannot write to it; Agent 01 pulls the file from `research/agent-06-communications` at the F-58 commit.
