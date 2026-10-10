# F-136 receipt: selectable states alongside distance (DRY-RUN, no live reload)

Provenance: queue row F-136 (ARYA-20261010-1817/1818); owner-reviewed GSA reference. Code commit `48d27b9` (first `ce696bd`). No provider, scraping or fetch; state comes only from the cached lot's `location.state` (valid 2-letter code or UNKNOWN). No legal-eligibility claim. :8766 was NOT touched.

## Code
- Location panel in the filter card (`market_view.location_panel`): By Distance / By State radios, ZIP + radius kept, searchable state list (server-side "Find a state", no JS under CSP; selected states always stay listed), multi-select checkboxes, removable chips (GET links), scope sentence always visible.
- Semantics: By Distance = existing radius behaviour (Conway / 150 mi default unchanged), states not applied. By State = state filter only; the radius is NOT applied unless "also keep the radius" is ticked, then a labelled intersection (state AND radius). Both stated in the chip and the panel.
- Unknown state (or, with radius on, unknown distance) fails the strict filter: listed only in the existing "could not be checked" section, never counted local. Invalid code or empty selection in By State = visible error, no search run.
- Persistence: saved campaign `nice_to_have` meta `locmode:`/`states:`/`alsorad:` (frozen schema untouched), remembered-prefs keys `state`, `loc_mode`, `also_radius`, `state_find`. Search Now still in the filter card and, on desktop 1648x1000 and mobile 390x844, in the first viewport (state picker closed unless searching).
- No county precision invented.

## Tests (reported separately from staging)
`tests/test_market_f136.py`: 15 passed (mode switch, multi-state, chip removal, search, invalid/unknown state, strict conjunction with price + radius, empty selection, saved roundtrip incl. restart, real-cache). Market + landing files: 104 passed / 0 failed. Full lane run: reference 407 passed / 1 failed (known test_resale_f39 timeout); lane D+E 105 passed / 2 failed (known F-32).

## Staging evidence
`docs/receipts/f136-state-location-screenshots/` (desktop + mobile, first viewport and full page, 5 scenarios, `state-evidence.json`): URL, viewport, filters, UTC capture time, cache sha256 + as-of 2026-10-10T00:19:23Z, store = STUB (no database), code sha 48d27b9, tree clean at capture. Script `tools/f136_state_shots.py` (isolated loopback port, COPY of the cache).
