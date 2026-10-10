# Receipt F-51: /market income-first acceptance (staging, DRY-RUN)

Lane 06. Builds on F-47/F-48/F-49/F-50. No new dashboard; no network, no contact, no spend. Code state only: **LIVE :8766 is NOT reloaded**; one consolidated owner-gated reload (F-49 + F-50 + F-51) is still needed.

## What changed (code)
1. **Min AND max price**: number boxes plus two accessible range sliders (labelled, keyboard operable). The page's CSP forbids scripts, so there is no JS: the slider wins only if moved from the rendered value (`prev_min/prev_max`), else the typed number. Slider range $1 to $20,000 is a control scale only, stated on the page as not a budget. Applied filters are plain chips (`#applied-filters`). Filters persist across navigation (`app.market_last`, in memory; `?new=1` clears).
2. **Origin and radius**: editable origin (default Conway AR, ZIP 72032) and radius (default 150 mi, editable). Known distances beyond the radius are hidden (counted). Unknown/unresolved locations, and lots with no bid when a price range is set, go to a separate optional section (`#unchecked-section`), never counted as local or in range. Zero results says so (`#zero-results`). No coordinates invented (F-50 gazetteer caveat kept; duplicate caveat render removed).
3. **Default view** = trailers/equipment focus ("any of" terms, editable) near Conway; **Broad inventory mode** is an explicit checkbox, off by default. **Working capital** shown as a documented SETTING ($500 protected principal, DEAL_SNIFFER_START_HERE s1, `MBOS_WORKING_CAPITAL_USD`) apart from "Verified cash: UNKNOWN". Not a spend authorization.
4. **Demo**: sidebar link and the "Show demo data" pointer removed from normal routes; demo is reachable only at `/demo` (not in nav). History untouched.
5. **GSA plain language** panel: government surplus auctions, cache freshness (6 h STALE rule), image/login limit (no bypass, no fabricated photos), original-listing link. Auction cards: "Current bid ... (not a sold price or final cost)", "Asking price: none (auction)", "all-in cost UNKNOWN (never the final cost)".
6. **Search faded: diagnosis (real Chrome 155 via Playwright)**: cause = CSS, not disabled and not focus. Computed style before: `disabled=false, opacity=1, color rgb(255,255,255) on background rgb(239,239,239)` (global `button` sets white text but the plain Search button had no background class). Screenshot `00-before-search-button-faded.png`. Fix: `.mk-form button` accent background with `--bg` text, focus-visible outline, larger Search. After: bg rgb(36,86,201), text rgb(246,247,249), `12-search-button-focus.png`. Save/Enable buttons got the same style.

## Real-browser acceptance (`tools/f51_browser.py` + `tools/f51_run_steps.py`; screenshots in `docs/receipts/f51-screenshots/`, log `run-log.json`)
Cache: `agent-01-coordinator/var/cache/gsa-active-auctions.json`, as-of 2026-10-10T00:19:23Z, 4.3 h old at run time (not stale), 154 lots in scope of 1179. In every step the DOM result set equals an independent computation (`match: true`):
| step | filters | main results / unchecked |
|---|---|---|
| 01 default | trailers/equipment, Conway, 150 mi | 12 / 41 |
| 02 broad | 150 mi, $1 to $20,000 | 5 / 148 (no-bid lots unchecked) |
| 03 / 04 | 150 mi, $100 to $500 / min $100 | 0 / 121 and 0 / 131 (zero shown honestly) |
| 05 | broad, 75 mi | 11 / 135 |
| 06 | broad, 1 mi | 0 (no known-distance lot) |
| 07 | origin "Zzyzx 99999", 50 mi | 0 / 154 (origin not located, radius not applied, all unchecked) |
| 08 | focus + 150 mi + $1 to $20,000 | 2 / 51 |
| 09 | keyboard on max slider to $101, Search | max chip $101, 5 / 126 |
10 persisted chips after /wanted and back; 11 `/demo`; normal pages (`/market`, `/wanted`, `/gsa`) contain no `demo=1`.

## Tests
New `tests/test_acceptance_f51.py` (9 tests). Updated for the new behaviour: `test_live_demo_f46`, `test_market_f47` (demo link gone), `test_landing_f48` (the labelled $500 SETTING is allowed). Health command: `tools/run_tests.sh` (see AGENT_STATUS for numbers).

## Not done / UNKNOWN
Persistence is in memory (lost on UI restart). Min price and focus terms are not saved into campaigns (frozen schema has no field). "Repairable" cannot be verified from GSA data: the focus is keywords only. Stub store used in the browser run (no live queue); the real cache was used.
