# F-142: Search Now moves to the bottom of the filter card (owner correction 2026-10-11 11:21 CDT)

Provenance: owner screenshot showed `Search Now` above Min/Max; F-60 (`63d741d`) rendered the button before `_slider(...)`. DRY-RUN, no network, no live reload.

## Change
- `operator_ui/market_view.py` `_side_filters`: order is now Location panel, price sliders (Min/Max number + range), Categories + note, then the single `Search Now` submit. Still `type='submit' form='mkform'` (the real GET form), so click and Enter, every filter, the Save/PIN boundary and the secondary nav (New Search, My Campaigns, Saved Deals, Auctions Closing Soon) are untouched.
- Tests (`tests/test_market_f60.py`): new rendered-order test (button after every filter control, only button in the card); `_card` helper updated; real-Chrome test now asserts the button is below Min/Max and both sliders on desktop (1280) and 390 px, and that Max=25 narrows 6 -> 4 known lots, Enter with 20000 widens them again, radius persists.
- Evidence tool `tools/f142_search_bottom_shots.py`; screenshots + metadata JSON in `docs/receipts/f142-search-bottom-screenshots/` (desktop 1648x1000 click+Enter, mobile 390x844 click; before/after Min=5/Max=25; first viewport + full page). Staging: stub store, copy of the real GSA cache (as-of in the JSON). All 6 captures: `below_both_sliders` true, `below_all_filter_controls` true (the clipped scrolling state list is excluded from the geometry check, it sits above the button in DOM order), `inside_filter_card` true. The button is no longer in the first viewport on desktop (about y=1244); that is the owner's requested position.

## Results
- f60 4 passed; f51/f53 related 47 passed; full reference run 460 passed / 0 failed; lane D+E 105 passed / 2 failed (known F-32 `test_inputs_f32`, unrelated).

## :8766 live verification: NEED
No already-authorized release gate for a :8766 reload exists in the queue for this task, and live probing was not done. NEED: owner/Agent 01 authorizes the one consolidated reload of :8766 at this commit; then record artifact hash, `/health`, cache sha256 and a fresh screenshot. Not claimed live.
