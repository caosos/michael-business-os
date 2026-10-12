# F-163 receipt: /market layout rework of F-159 (DRY-RUN, no live reload)

Provenance: queue row F-163 (owner 2026-10-12 'GSA parity'; Agent 01 inspected `64ce371` in headless Chrome 1440x1600 and 390x1500). Reuses F-159 code; same prefs file, no new store.

## What changed
- Order: sticky top bar (one search box, ONE `Search` submit, result count, Sort, View, Filters toggle; one line at 1440) then quick-view pills, then left column (Filters card first, then My bids) and the result grid right away.
- My bids is a collapsed `<details>` with its count in the summary, below the Filters card. Per-source status list moved into the collapsed Sources panel (summary 'N connected, M not connected'); an offline GSA error still shows in place. FIXTURE banner kept, one line (ellipsis, full text in title and markup). Suggestions is a collapsed 'Suggestions (N)' strip above the grid. Applied-filter chips and the result heading are one compact line.
- Card: photo, source badge, countdown badge, title, City, ST + distance, closing time, current bid + bidders, one `View` (a dashed 'No live link' tag when the link is not a verified live one, no button). Save / Not interested / More / Less / Hide / my max / I bid on this and the reserve line sit in a `⋯` `<details>` menu (no script). Sort and View apply on change via the existing same-origin script; Search does the same without script.
- Active quick-view pill and current page: white on blue (#1d4ed8); count readable.
- Phone: Filters stays a drawer; title banner hidden to save height.

## Measured (headless Chrome, fixture caches, 12 tracked bids, fixture banner on)
- 390x900: first result card top 391 px (< 900). 1440x900: Filters top 196, grid top 442 (< 450), Filters card above My bids, bar items on one row, exactly 1 submit in the top bar, each visible card has exactly 1 primary control.

## Tests
- New `tests/test_market_f163.py`: 3 passed. f159: 21 passed. Older tests updated only for 'Search Now' -> 'Search' (f47, f51 acceptance, f60).
- Golden `tests/fixtures/f145_gsa_golden.json` regenerated for the intended change. Token diff (default/gallery/state/explicit): removed 'Apply', 'Search Now'; added 'Search', 'Suggestions (N)' strip, 'collapsed; click to open' (My bids), 'Details and actions' (⋯ menu), 'ranked by the engine, display only'. List view: same minus the ⋯ menu.
- Full suite: reference 602 passed / 1 failed (known resale_f39 timeout); lane D+E 105 passed / 2 failed (known F-32). Not done: live :8766 reload (owner-gated), Agent 01 real-browser re-check (NEED).
