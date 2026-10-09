# Receipt: F-35 `/assets` figures form (lane 06, DRY-RUN)

- **What:** a "Your rough figures" form on `/assets/<id>` (owner channel: CSRF + PIN, server-set author). Low/high ranges for as-is value, rehab cash (minimal, themed, convert, keep), own hours, finished resale ranges, personal-use value, days to cash, plus tailgate months. Each figure is kept as a typed record `{"low","high"}` on the draft (`figures`) and handed to `mbos_economics.owned_asset.compare_paths` as an `owned:<key>` research entry, so the five paths compute and one is recommended.
- **Wording / basis (INFER):** figures are Michael's estimates: engine basis `INFER`, `entered_by` = the server-set operator, deterministic DRY-RUN `prov_` id (not a receipt). The card says "Based on your own estimates (INFERENCE, not verified)"; nothing is marked verified.
- **Validation:** plain finite numbers, 0 <= low <= high < 1e7 (one box = a single number); months 1-12; any error refuses the whole save. Clearing both boxes removes the figure, so the engine names it UNKNOWN again.
- **Files:** `operator_ui/assets_view.py`, `tests/test_assets_f35.py`.
- **Provenance:** engine input names from `mbos_economics/owned_asset.py` (economics `3dc8a49`, C-30); A-47 dependency DONE. Example ranges are illustrative test values, not Michael's numbers.
- **UNK:** convert and keep:cash/hours are asked explicitly (engine needs them); sell-as-is cash is a structural zero in the engine when left blank.
- **No side effects:** nothing sent, published, spent, verified; no CAOSCare contact.
