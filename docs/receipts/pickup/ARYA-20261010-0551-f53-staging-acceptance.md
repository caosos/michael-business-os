# Pickup receipt: ARYA-20261010-0551-f53-staging-acceptance

Routine coordination only (dry-run). No code, restart, spend, bid, contact or other-project change.

## What was done
- Read the instruction and the F-53 artifact `origin/research/agent-06-communications` (e1621cf, status commit a85be15) and its `docs/handoff/F-51-F-52-acceptance-matrix.md`.
- Verified from the matrix: A16, B01, B16, B18, C07, C08 are NOT RUN; A17, B12, B19 are PASS with disclosed gaps (saved-search relaxation not retested; link click not performed; raw source-ID comparison not done).
- Verified by reading code (not running it): `operator_ui/market_search.py:136` computes `round(haversine_miles(origin, c), 1)` in `_card`. The radius defect is real in source; matrix A04 PASS ("distance compared unrounded") is not supported by that line. A04 is treated as unproven until the F-54 boundary test exists.
- Saved-search: `criteria_to_query` (market_search.py:108) and `save_form` (market_view.py:281) exist; the omission of min_price/categories/row order is for lane 06 to reproduce (not run here).
- Added READY_QUEUE row **F-54** (lane 06, one worker, follows F-53, no duplicate) covering the six cases, three audits, radius fix, saved-search round trip and gates.

## Tests
None run (no code or browser work in pickup). Gate numbers on file for e1621cf are lane 06's: reference 371 passed/1 failed (`test_resale_f39`), lane D+E 105 passed/2 failed (F-32), not re-verified.

## Remaining blockers
- Code/browser execution belongs to lane 06 (F-54). Dispatch is subject to PAUSE-01 state; I did not change it.
- Live UI reload stays owner-gated.
