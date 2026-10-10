# Receipt: F-59 saved "any of" focus terms (DRY-RUN)

Provenance: queue row F-59 (P0, from ARYA-20261010-0717). F-58 (`8e2c667`) did NOT fix it (checked: `save_form` still omitted `q['any']`, `criteria_to_query` still hardcoded `any=''`). No contact, spend, publish, deploy or credentials.

## Fix (minimal)
- `operator_ui/market_view.py` `save_form`: the any-terms ride in `nice_to_have` as `any:a>b` (same mechanism as `cat:`/`rows:`; `>` inside a term becomes a space).
- `operator_ui/market_search.py`: `any:` added to `META`; `criteria_to_query` restores `any` from it and always sets the key, so an empty focus stays empty and never falls back to the default focus (no silent broadening). Older saved searches reopen as before (focus none).

## Evidence (code `bfc0b47`, real Chrome, isolated STUB-store server; database persistence NOT proven)
- `tools/accept_save_restart.py` (+ `tools/accept_serve.py`, copied from the coordinator branch so the command runs here): exit 0 in scenario A and B. Applied mode "repairable trailers/equipment focus: trailer, equipment" identical before Save, after reopen, after a real process restart; visible known-ID set identical. `docs/receipts/f59-evidence/scenario-{A,B}/`.
- `tests/test_market_f59.py` (render, POST exactly the Save form's fields, reopen, fresh app over the same campaigns file; chips + visible known-ID set equal): 2 pass with the fix, both fail without it.
- B16: `tools/f54_browser.py` now compares visible known-ID sets (outside `#unchecked-section`) + chips across search A, B, Back, Forward: Back == A, Forward == B (`f59-evidence/b16-back-forward.json`). Limit: A and B show the same 5 visible IDs on this fixture, so the chips are what distinguish them.
- Matrix rows A17 and B16 updated.

## Tests
Market files `tests/test_market_f5*.py`: 59 passed / 0 failed. Reference suite (`pytest tests`, `test_resale_f39.py` deselected: known combined-run socket timeout, passes alone): 380 passed / 0 failed. Lane D+E (`MBOS_UI_LANE_D=1`): 105 passed / 2 failed, the known F-32 baseline pair (`test_inputs_f32`), unrelated.
