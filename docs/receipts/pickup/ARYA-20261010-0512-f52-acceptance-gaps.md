# Pickup receipt: ARYA-20261010-0512-f52-acceptance-gaps

- Stage: COMPLETED as coordination (all four items need code; routed to a queue row; no code, restart, spend, contact or other projects)
- Source: `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARYA-20261010-0512-f52-acceptance-gaps.md`

## What was done
1. Read the instruction, START_HERE.md and COORDINATION.md (coordinator branch) and the existing F-52 row, matrix and staging receipt.
2. Verified read-only against `origin/research/agent-06-communications`:
   - `operator_ui/market_routes.py:29` defines `_remembered(app, qs)` (in-memory); `operator_ui/market_prefs.py` persists only the preference/feedback file `var/market_prefs.json` (override `MBOS_MARKET_PREFS_FILE`). Whether filter/category/order choices survive restart: not shown by any evidence I found; treated as the gap the review states.
   - Screenshots exist at `docs/receipts/f52-screenshots/01-gallery-default.png` .. `06-mobile.png` on lane 06. I did not view them or re-measure the ~1600px claim.
   - The staging receipt (`docs/receipts/2026-10-10-f52-staging-verification.md`) states full-run results were taken before two test-wording fixes and were not all green (338 passed / 3 failed reference; 105 passed / 2 failed lane D+E), so a final full-gate run is genuinely outstanding.
3. Queue: marked F-52 "DONE as code delivered, NOT ACCEPTED" and added **F-53** (lane 06, READY, after F-52): the four gaps in the instructed order (browse-first layout, restart persistence on an isolated instance, final-resolved-value validation incl. sliders, final gates plus matrix PASS/FAIL/NOTRUN on the same artifact). No parallel worker; DealSniffer not paused.
4. Matrix: untouched. All cases stay NOT RUN until F-53 runs them; I ran none.

## Tests
None run (docs-only). No numbers claimed.

## Remaining blockers / next START
- Next START: F-53 on lane 06 (dispatcher picks up READY row). Bounded closure = matrix cases recorded on the final artifact plus final full-gate numbers.
- Owner decisions: none. Live UI reload (F-49..F-53) remains owner-gated and unperformed.
