# Receipt F-49: demo items off every non-demo page; local ZIP/city gazetteer (DRY-RUN)

- **Action:** code change only; nothing sent, bought, published or deployed. No network, no geocoder.
- **Provenance:** F-49 queue row (coordinator READY_QUEUE); owner report that live :8766 `/mission` and `/summary` still listed '55 inch LED TV'.
- **FACT:** `/mission` showed the plan file's demo leg (F-48 filtered only the Today header); digest/summary/holds/outcomes/ledger read the store unfiltered.
- **Change:** `landing_fix.live_only` now also drops validation errors that echo a removed id; `landing_fix.LiveStore` (read-only proxy) hides demo items from `items_in_states`, `held`, `outcomes`, `receipts`; wired into `/mission`, `/digest`, `/summary`, `/holds`, `/outcomes`, `/ledger`. New `operator_ui/gazetteer.py` + `data/gazetteer_us.csv` (zip,city,state,lat,lng) locate a ZIP or city from a local file (`MBOS_GAZETTEER_FILE` overrides); `parse_origin` uses it; unlocated origins say so plainly ("No network lookup is made").
- **INFER:** gazetteer rows are hand-entered approximate town centroids (a few miles). 72032 = Conway, AR (35.0887, -92.4421). Add the Census ZCTA file via `MBOS_GAZETTEER_FILE` for full US coverage.
- **UNK:** the live :8766 needs a restart/reload to pick this up; I did not touch it.
- **Tests:** `tests/test_live_only_f49.py` walks every NAV route with a demo item in every reader: zero TRAIN-/example.invalid/55 inch/LED TV; ZIP 72032 located, 00000 truthfully unlocated.
