# F-137: F-136 acceptance gaps (labels, gallery, `_amt`, evidence precision, real-browser persistence)
Provenance: code at the commit that adds this file's parent change (see AGENT_STATUS); cache copy as-of 2026-10-10T00:19:23Z; evidence `docs/receipts/f137-screenshots/f137-evidence.json` (script `tools/f137_browser.py`). DRY-RUN. Isolated staging: stub store, loopback ephemeral port, test PIN, copy of the cache. No live :8766 reload, no fetch, no bid/purchase, no live secrets.

## Accepted state behavior (F-136, unchanged)
By State / By Distance, multi-select, chips, also-radius, saved via nice_to_have (locmode/states/alsorad). Not reimplemented. `tests/test_market_f136.py` 15 passed.

## Corrected labels
- `market_search.auction_labels(p, asof)`: "ESTIMATED $X (cached current bid + $inc increment, as of cached <timestamp>; live minimum unverified)"; key renamed `est_next_bid`; never called the minimum. No bid: UNKNOWN, opening minimum not in cache (cached increment still shown).
- `_amt` rejects inf/nan (and a non-finite sum, e.g. 1e308+1e308), negatives, bools, strings.
- Gallery card (`market_view.gallery_labels`): "Bid $25 → est. next ~$98 (cached, unverified) · Reserve: Yes (amount undisclosed)" (Yes/No/UNKNOWN); list card line reads "Next bid: ESTIMATED ...".
- Tests: `tests/test_market_f137.py` 12 passed (incl. parametrized `_amt`); `test_market_f61.py` adjusted for the rename; f61+f137+f136 = 33 passed.

## Baseline test failures (not caused by F-137)
Reference: 419 passed / 1 failed (`test_resale_f39` socket timeout, known). Lane D+E: 105 passed / 2 failed (`test_inputs_f32` x2, known F-32).

## Visual proof (`docs/receipts/f137-screenshots/`)
Desktop 1648x1000 and mobile 390x844: gallery labels, list labels, state panel AR/TX. Label shots are SCROLLED viewports (first label centred; scrollY recorded per shot in the JSON). The state shot is UNSCROLLED (scrollY=0) and records `search_now_in_first_viewport` = true on both viewports. The older `tools/f136_state_shots.py` captures: only the `state_find` scenario uses scrollIntoView (scrolled-viewport evidence); the rest were at scrollY=0, but scrollY was not recorded then.
Persistence: REAL Chrome clicked the real Save button (states AR+TX, mode state, also-radius on); reopened via the saved search's Run link; then the server PROCESS was terminated and a new process (different pid, same data dir) started and the saved search reopened again. Visible controls and the 5 visible known-section lot IDs were identical before save, after reopen and after restart: PASS. The earlier F-136 HTTP-form + recreated-app test was not a browser Save/restart and is not claimed as one.

## Owner live gate
Live :8766 needs the one consolidated owner-gated reload; not done here.

## Foreman
F-137 is READY for lane 06 in READY_QUEUE.md on the coordinator branch. I cannot observe the foreman's dispatch from this worktree: "exactly one worker starts" is UNVERIFIED by me.
