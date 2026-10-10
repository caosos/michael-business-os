# Receipt: real-cache visual evidence for F-54 (answers ARYA-20261010-0610), by the interactive Agent 01

**Independent of lane 06's F-55 worker** (launched 06:12:22Z, still running when this was written). This is Agent 01's own capture; it does not replace F-55's matrix audit.

## Provenance (every shot has a JSON sidecar in `docs/receipts/f54-real-cache-screenshots/`)
- **Code:** lane 06 `120e452` (F-54), exported to `var/lanes/agent-06.new`, served by the real `operator_ui` on **isolated staging http://127.0.0.1:8767** (live :8766 untouched), scratch prefs file, no stub store, **no fixture**.
- **Source:** the actual cached GSA file `var/cache/gsa-active-auctions.json`: 3,606,527 bytes, sha256 `d02f3acc4a6eef4b7abd4065c2dc5d4370dd6064fe0bba1b385ec6a8fa154ba7`, 1,179 lots, fetched 2026-10-10T00:19:23Z from the official GSA Auctions API (receipt `2026-10-09-gsa-api-smoke.md`). The page itself says "last fetched 2026-10-10 00:19 UTC (5.9 h ago)" and "Cached copy of the GSA list, not a fresh fetch" (both verified visible at 1648x1000, 315 px and 445 px from the top).
- **Captures (UTC 06:13:18-06:13:21):** `conway-1648` (realistic search: Conway AR, 150 mi, default trailers/equipment focus, 1648x1000), `conway-390` (same search, 390x844), `broader-1648` (**labelled broader browsing example**, broad mode, 300 mi, not the acceptance search). Each has first-viewport and full-page PNGs. Tool: `tools/capture_market.py` (real Chrome via Playwright).
- **Adversarial fixture evidence** (nine-item hostile-title fixture) is lane 06's `f54-screenshots/B01-*`; it is synthetic and not used here.

## B19: displayed listings vs the cache (computed, not eyeballed)
- Conway search: **12** checked cards; every displayed link equals that lot's `itemDescURL` in the cache, and every title equals the cache `itemName` (whitespace-normalised; display truncation with "..." accepted only as a prefix of the cache title). **81** more links in the closed "could not be checked" section are all lots in the cache (link check only). Broader example: 19 checked cards all match, 268 optional links all in the cache. Mismatches: none after correcting my own script (first runs wrongly flagged double-space titles and the optional section's different markup).
- Photos: all cards show the login-gated tile, no `<img>`; no photo is fabricated.

## What the first viewport shows (my reading of `conway-1648-first-viewport.png`) - for Arya's review
- Works: listings-first order (filters left, results right), applied-filter chips, cache timestamp, "12 results within 150 mi of Conway, AR", three Trailers cards (Marianna utility trailer $25, Greenbrier Striker tank trailer and Monark boat trailer with "No bids yet / price UNKNOWN"), WATCH labels, original-listing links, empty Equipment row says "No matching known inventory".
- **Gaps (honest):** (1) the results area is a narrow centered column on a 1648 px screen: only **3 cards across** with large empty margins, far from the dense five-across photo-led reference (the F-54 matrix already records B01 PARTIAL); (2) photos are text tiles because GSA images need a GSA login; (3) the old "Operator UI" header and a 16-item nav bar still sit above "Michael's Marketplace"; (4) the three visible cards are mostly "No bids yet", which is real data but a weak first impression; (5) at 390 px the first card starts at 930 px, below the first screen (disclosed earlier).

## Not done
Live reload (owner-gated); matrix substep audit (F-55); the Save-form defect (F-56, confirmed in `market_view.py::_save()` by Arya's review, not re-tested by Agent 01 on the rendered page).

## Addendum 2026-10-10 ~06:57Z: F-56 verified by Agent 01
- Lane 06 `d89c87c` (status `ab81bed`): tests `test_market_f56 + f53 + f52` = 54 passed (run by Agent 01). The real-Chrome run (`docs/receipts/f56-browser/f56-browser.json`) shows the actual Save click POSTing cat=trailers, row1=equipment, row2=trailers, condition=trailer; saved `nice_to_have` = min:0, cat:trailers, rows:equipment>trailers>>, broad:1, cond:trailer; reopen and a fresh restart show equal visible IDs and the same applied-filter chips.
- Not confirmed by Agent 01: that the saved ROW ORDER is rendered after reopen (the browser JSON lists only the `trailers` row in the DOM after reopening, in broad mode); lane 06's screenshots were captured with the fix still uncommitted (`operator_ui_tree_dirty: true`, disclosed in its receipt), so the code SHA on those shots is the working tree, not a commit. Live acceptance remains owner-gated.
- Dispatch: F-56 exited rc 0 at 06:53:57Z; the dispatcher launched F-57 at once (its dependency was then met); one worker at a time.
