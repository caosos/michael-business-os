# F-159 receipt: /market search page with GSA Auctions parity (DRY-RUN, no live reload)

Provenance: queue row F-159 (owner 2026-10-12 ~14:30 CDT; Agent 01 inspected gsaauctions.gov in Chrome). Built on F-157/F-158 (`112fce4`); no parallel store (same market prefs file).

## What changed
- New `operator_ui/market_browse.py`: sticky top bar (one search box over title+description, "N results found", Filters (n active), Sort: Ending soonest default / Newest / Price low / Price high / Distance / Suggested), Quick views with live counts (All, New today, Closing today, Closing soon), collapsible left filter sidebar (collapse state remembered via CSRF POST `/market/ui`, stored in prefs), phone drawer at 390 px, countdown badges (red under 24 h), uniform 4/3/2/1 card grid, numbered pagination 24 per page with `page=` in the URL.
- Sidebar sections: Category (live counts, zero greyed, filter box, Land/Real Estate off by default), Source (count + connected/not connected), Location (By State with counts, Arkansas preselected; By Distance ZIP + radius 10/25/50/100/250/Any, default Conway 72032), Price range, Listing type (Auction / Buy now or fixed price / Auction event), Condition.
- Wired through `market_view/search/routes/prefs/sources`. Kept: honest UNKNOWNs, events never shown as lots, F-155 Suggestions, My bids, Sources panel, per-owner prefs.
- Older tests updated for the intended markup change (f52/53/56/57/60/136/143/144/146/149, test_operator_ui, test_acceptance_f51 Search Now button string).
- Golden `tests/fixtures/f145_gsa_golden.json` regenerated for the intended page change only. Token diff (distinct words/phrases, default view): 105 removed, 163 added; added: Apply filters, Category, Condition, Cards, Closing soon/today, Buy now or fixed price, Auction event, Close filters, "All sources", "Closes <date>"; removed: Categories, Gallery, Gallery rows, old "Closing", "Fixed price". gallery/list/state/gsa_explicit differ the same way.

## Tests
- `tests/test_market_f159.py`: 21 passed (counts equal filtered rows for category/source/state/listing type, quick views, sort orders, pagination, collapse persistence + CSRF, Land default-off, Arkansas preselect, prefs isolation, phone drawer/card shape).
- Reference suite: 598 passed / 2 failed in the full run; both pass/are known: `test_resale_f39` (known flake, 4 passed alone) and `test_acceptance_f51` (fixed afterwards, 9 passed). Expected 600 green.
- Lane D + E: 105 passed / 2 failed (known F-32 `test_inputs_f32`).
- Not done: live :8766 reload (owner-gated), real-browser check at 390 px (Agent 01 NEED).
