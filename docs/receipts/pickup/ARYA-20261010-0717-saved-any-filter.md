# Pickup receipt: ARYA-20261010-0717-saved-any-filter (Agent 01, docs only, dry-run)

## Done
- READY_QUEUE F-58 amended (items 7 and 8) rather than a new worker: saved any-term filter must survive Save/reopen/restart or be refused, never silently widened (`save_form` drops `q['any']`, `criteria_to_query` hardcodes `any=''`); targeted real-form regression plus saved-criteria and visible-known-ID checks. Still READY on lane 06 (code lane, not done here).
- Acceptance matrix: B16 PASS -> PARTIAL (all-`.mk-g` count rejected); totals now PARTIAL 6 / PASS 40 of 46.
- Future timestamps corrected: closeout receipt header "~07:30Z" and matrix header "~07:20Z" replaced by the actual commit time 07:15:50Z (206e484, from git log).

## Not done (needs code lane)
- The fix, regression, and Back/Forward visible-known-ID evidence belong to the F-58 lane-06 worker. No live reload, restart, spend or contact.

## Tests
None run (docs only); counts quoted are from existing records (380 passed / 1 failed unresolved resale_f39).

## Blockers
F-58 worker completion. Live reload remains owner-gated.
