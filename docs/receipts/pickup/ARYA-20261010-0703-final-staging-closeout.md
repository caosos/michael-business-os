# Pickup receipt: ARYA-20261010-0703-final-staging-closeout

Read-only reconciliation by Agent 01 pickup, docs only. No code, tests, browser, restart, reload, fetch, spend or contact. Observed against `origin/research/agent-06-communications` @ `026058e` (read via git, not checked out).

## Already done by the existing lane (no duplicate worker dispatched)
- **F-56 @ `d89c87c`**: `_save()` now submits cat, row1-row4, condition; `tests/test_market_f56.py` (3 tests fail on old code, pass on fix); real Chrome Save click, reopen and process restart each show visible known-section IDs equal to the independent partition (`docs/receipts/f56-browser/f56-browser.json`, saved `cat:trailers`, `rows:equipment>trailers>>`, `cond:trailer`). This closes the gap "serialization alone is not browser proof" at the staging level.
- **F-57 @ `85c416d`** (receipt `docs/receipts/2026-10-10-f57-market-wide-density.md`): conway-1648 first card top 535 -> 367 px, 5 across but only in the Vehicles row (starts about 872 px, partly below the fold); the Trailers row has only 3 real lots. Mobile 390: first card 949 -> 768 px, single column. **Retained limitation: on mobile, price and title still require scrolling; no claim of complete first-viewport browsing.** No further layout redesign was dispatched.

## Reconciliation of the four requested gaps
| Gap | Finding | Status |
|---|---|---|
| Save/reopen/restart of categories, condition, order in a rendered browser | Proven in real Chrome on staging at `d89c87c` (above). Live: NOT RUN (owner-gated) | DONE (staging) |
| Clean real-cache screenshots with truthful metadata; stub vs no-stub | F-57 sidecars (`docs/receipts/f57-after/*.json`) record code_sha `85c416d`, URL/port 8771, viewport, filters, UTC time 07:01:38Z, cache path/sha256/as-of, B19 12/12 match. **F-56 shots were captured with the tree dirty** (`operator_ui_tree_dirty: true`, base `b0b5980`) so use the F-57 set as the clean set. Wording fix: `tools/capture_market.py` says "no stub store"; F-57's `tools/serve_market_staging.py` runs `StubStore`. Both are true of different things: **inventory shown = REAL cached GSA file; persistence/decision store behind the page = STUB (isolated, scratch prefs).** So these runs prove real listings, links, filters and prefs-file retention; they do NOT prove real DB persistence. The F-54 receipt line "no stub store" is therefore inaccurate for the serve tool and must read "real cache, stub decision store" | PARTIAL: relabel needed (F-58) |
| Full reference regression without excluding resale_f39 | NOT satisfied. F-56 and F-57 both ran with `tests/test_resale_f39.py` deselected (known order-dependent socket timeout; passed alone 4/4 in the 02:04Z receipt). Latest numbers: reference 377 passed / 0 failed (excl. resale_f39); lane D+E 105 passed / 2 failed (known F-32 `test_inputs_f32`). The deselection is not a pass for resale_f39. | NOT DONE (F-58) |
| Canonical acceptance matrix updated with PASS/FAIL/PARTIAL/NOT RUN | Lane 06's copy of `docs/handoff/F-51-F-52-acceptance-matrix.md` is updated through F-55 (43 PASS, 3 PARTIAL: B01, B12, C08 as of F-54) but has **no F-56/F-57 rows or downgrades**. The copy on this coordinator branch is still the original, all NOT RUN. F-56's stated downgrades (count-only `.mk-g` navigation checks -> UNVERIFIED; A17 PASS only for Save/reopen/restart; B19 PASS on fidelity only) exist only in receipt prose | PARTIAL (F-58) |

Cache provenance comparison: F-57 `b19_comparison_with_cache` = 12/12 checked cards and 81/81 optional links match cache IDs and original `itemDescURL`; broader 19/19 and 268. Unknown-result separation and strict filters were unchanged by F-57 per its receipt (unit tests).

## Queue change
Added **F-58** (P0, lane 06, one bounded worker, no duplicate) for the code/test remainder: committed-artifact final pass, resale_f39 run alone with bounded timeout and honest result, stub label fix, matrix F-56/F-57 rows. See `docs/status/READY_QUEUE.md`.

## Packet
`docs/runbooks/port8766-reload-rollback-verification-packet.md`: reload/rollback/verification, cache staleness and the existing supported refresh route (GSA adapter, DEMO_KEY read-only; B-12 key decision). Live reload remains NOT approved.

## Tests
None run (docs-only). Numbers above are quoted from lane 06 receipts, not re-measured.

## Remaining
- Owner: approve/decline one live reload after F-58; optionally approve one read-only GSA refresh.
- F-58 (code/test lane) must finish before the reload can be recommended.
