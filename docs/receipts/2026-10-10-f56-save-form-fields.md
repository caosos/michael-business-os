# F-56 receipt: real Save form now submits cat, row1-row4 and condition (DRY-RUN)

Provenance: queue row F-56 (ADDED BY 01, ARYA-20261010-0611). Base commit b0b5980 (fix is in this commit). Isolated staging, stub store, copy of the real GSA cache; no live reload, no credentials, no contact.

## Reproduction (FACT)
`operator_ui/market_view.py` `_save()` built hidden fields only from keywords, base, radius, min_price, max_price, any, required, preferred, exclude (+broad). `save_form()` already serialized cat/rows/condition, so a real click lost them. `tests/test_market_f56.py` parses the REAL rendered page's `/market/save` form (not injected fields); on the old code all 3 tests fail, on the fix all 3 pass.

## Fix (minimal)
- `_save()` adds hidden `condition`, `cat` (comma-joined, only when categories are checked) and `row1`..`row4` (blank rows stay blank).
- `save_form()` splits a comma-joined `cat` (the POST parser keeps one value per name, so several checked boxes need one field). No filter was relaxed.

## Evidence
- pytest `tests/test_market_f56.py`: rendered form carries cat/rows/condition; posting exactly those fields saves `cat:trailers`, `rows:tools>trailers>>`, `cond:used`; reopen and a fresh App over the same campaigns file show the same chips, rows and condition; two categories survive.
- Real Chrome (`tools/f56_browser.py`, `docs/receipts/f56-browser/f56-browser.json`): the real Save click POSTs cat=trailers, row1=equipment, row2=trailers, condition=trailer; saved nice_to_have = min:0, cat:trailers, rows:equipment>trailers>>, broad:1, cond:trailer; reopen and restart each show 1 visible known-section lot whose ID equals the independent `ms.partition` result (visible `.mk-g` outside `<details>`; hidden unknown cards excluded; the check requires expected > 0, so an empty-equals-empty run cannot pass).
- Clean real-cache visual run, same F-55 script: `docs/receipts/f56-real-cache-screenshots/` (B19 fidelity PASS: 6 / 4 / 154 lots, all IDs, links, titles equal the cache). NOTE: captured with the fix uncommitted (`operator_ui_tree_dirty: true` in the metadata) at base b0b5980.
- Tests: reference 375 passed / 0 failed excluding `tests/test_resale_f39.py` (4 deselected; known pre-existing timeout, not re-run here); lane D+E 105 passed / 2 failed (known F-32 `test_inputs_f32.py`, unrelated).

## Matrix downgrades (never PASS without every substep)
- A17 (cat=trailers focus after Save): PASS for Save, reopen, restart on the field propagation. Not shown: that a saved search works as a live reload (owner-gated).
- B19: PASS on fidelity only; completeness rests on F-54's set-equality run.
- B01/B12/C08: stay PARTIAL as in F-54 (no new evidence). Earlier navigation checks that compared only counts of all `.mk-g` (which include hidden unknown cards) are DOWNGRADED to UNVERIFIED; this receipt's tool compares visible known-section IDs instead.
- The `sort`, `view`, `closing_by` fields are still not saved (documented in F-54; they apply to the run).

Live :8766 still needs the one owner-gated reload. Nothing was sent, spent or published.
