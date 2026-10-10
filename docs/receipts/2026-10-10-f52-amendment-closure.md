# F-52: close the F-51 AMENDMENT (A)(B)(C) (lane 06, DRY-RUN, staging only)

Provenance: queue row F-52 and `docs/handoff/F-51-amendment.md` (coordinator branch, read at fetch time). F-51's receipt/status never cite "AMENDMENT" (FACT: grep finds none), so the worker had not read it; F-51 delivered the unchecked section, the controls and the demo split from the owner's earlier ask.

## Covered by F-51 (@ e327469, evidence = its receipt + tests) vs not
| Item | Status before F-52 | F-52 |
|---|---|---|
| A: min/max price and radius constrain every row | DONE (`partition`) | unchanged, test `test_unknown_price_or_distance_never_in_checked_results` |
| A: unknown price/distance not passed, separate section | DONE, but always-open list | now a closed `<details>` "Optional ... Click to open" |
| A: invalid numeric filter shows visible message | NOT DONE (bad number silently None) | DONE: `validate()` (non-number, negative, over cap, min>max) -> `#filter-errors`, no search run; 5 parametrised tests; real browser min 900 / max 100 |
| B: dense photo gallery, price on card, short title, town, closes, posted age | NOT DONE | DONE: `gallery_card` (posted age printed as "not given": GSA has none) |
| B: left sidebar with categories, ZIP/radius, min/max | NOT DONE (top form) | DONE: inputs live in the sidebar (`form='mkform'`), top bar has sort/view/search |
| B: 3-4 customizable rows, owner picks/orders; empty = "No matching known inventory" | NOT DONE | DONE: Row 1-4 selects (trailers, equipment, vehicles, electronics, tools), checked categories replace the focus; "other" row for the rest |
| B: responsive, honest missing-photo placeholders, advanced filters in disclosure, cached not fresh, GSA-only stated, no branding/scraping | partly | DONE: grid auto-fills, 390px viewport no overflow, tile text, "Cached copy ... not a fresh fetch" |
| C: save, dismiss, more/less like this, persisted, visible why, reset, disable | NOT DONE | DONE (`market_prefs.py`, JSON file `var/market_prefs.json` or `MBOS_MARKET_PREFS_FILE`); CSRF only (view preference, no money/contact) |
| C: never overrides hard filters / invents profit / outside data | n/a | DONE: applied after `partition`; rank only reorders and hides dismissed; order follows owner sort unless "suggested" |

Also fixed: the card buttons had the same faded-CSS fault as F-51's Search (computed bg rgb(36,86,201), text rgb(246,247,249), opacity 1 now). Two old tests asserted list-card wording on the default view; they now request `view=list`.

## Evidence
Real Chrome (`tools/f52_browser.py`, real cached GSA file as of 2026-10-10T00:19Z, 154 lots): `docs/receipts/f52-screenshots/` + `run-log.json`. Default: rows trailers:3, equipment:0 (empty text shown), vehicles:8, other:1; strict broad 150 mi / max 100000: 5 checked, 148 in the closed unchecked section; custom rows electronics:0 / trailers:6; save+more-like-this gave "Why suggested" lines, Reset cleared; mobile no overflow.
Tests: `tests/test_market_f52.py` (16). Health: see AGENT_STATUS. Live :8766 still needs the ONE owner-gated reload (F-49+F-50+F-51+F-52). Not done/UNKNOWN: posted age (source has none); category matching is title+category keywords, a label not a claim; GSA photos stay a tile (login-gated).

Health (final): reference (ungrouped, run before the 2 test-wording fixes) 338 passed / 3 failed: the 2 wording/allowlist failures were fixed and re-run green (63 passed in the touched files); the third, `test_resale_f39` TimeoutError, is the pre-existing ungrouped-run stall noted in F-50 (passes alone). Lane D+E 105 passed / 2 failed (pre-existing F-32 stored-input tests). `tools/run_tests.sh` therefore exits 1 for the same pre-existing reasons.
