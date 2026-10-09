# Receipt: C-29 LEARN groups by prior class (F-117)
Tags: FACT / INFERENCE. DRY-RUN; nothing applied.

- **FACT (provenance):** C-26 already gave `consumer_electronics` / `small_goods` non-zero `labor_hours` priors (priors 2026.10.5). The defect was in `learn.item_meta_from_docs`, which keyed an `other_asset` TV as `flip/other_asset/...`; that path's priors are 0, so `consider()` skipped it.
- **Change:** `item_meta_from_docs(docs, priors=None)` now resolves the category through `estimate.prior_category` (closed `flip_subcategories` vocabulary). A TV calibrates `flip.consumer_electronics.labor_hours.<cond>`.
- **Outcome fields:** `predicted_vs_actual` is free-field in Outcome v1 and read generically by `calibrate`; no producer exists in this lane, so nothing further to change. INFERENCE: the Outcome writer (04/06) should emit `rehab.labor_hours`, `rehab.parts_cost`, `resale.target_sell_price`, `rehab.repair_success_prob`, `resale.sale_prob`.
- **Test:** `tests/test_learn_tv_class.py` (2 outcomes, 0.25h predicted vs 0.75h actual -> tier-0 `drafted` proposal; priors file hash unchanged).
- **Health:** `PYTHONPATH=src:tests pytest tests -q` -> 396 passed, 22 skipped.
