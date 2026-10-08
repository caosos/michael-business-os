# Receipt: A-41 viable dry-run deal set (`fixtures/sources/training_examples.json`)

- **Task:** A-41 (P0), lane 01, branch `worker/a-41-fixtures`. DRY-RUN only; no network, no contact, no spend. Frozen contracts untouched.
- **Provenance:** Michael's three training examples as written in the queue row (the $30 TV that resells for $75-100, the older riding mower late in the season, the non-running Recon about $300). Every listing is INVENTED and labelled ILLUSTRATIVE (`example.invalid` URLs). Each economics assumption carries `basis` FACT / INFER / UNKNOWN and a note. Engine = lane C `mbos_economics` 0.14.0 and its config 2026.10.4 as installed; lane D at `origin/research/agent-04-state` (D-29 included) via `git archive`.
- **Deals and the verdicts the REAL assembly produces ($500 bankroll on the ledger):**
  | Deal | State / verdict | Why |
  |---|---|---|
  | TV $30 -> ~$95 | AWAITING_APPROVAL / YES | micro flip, 3 sold comps, EV $55.76, $85.78/h |
  | Recon $300, not running | RESEARCHING / MAYBE | fault not identified; cheapest decisive evidence `fault_identified -> YES` |
  | Riding mower $480 late season | ARCHIVED / PASS | "cash tied up $616.98 exceeds the cash you can fund (cap $500.00)"; evidence-backed (buy price and parts are FACT), so not a PASS on priors |
  | Drywall lead | RESEARCHING / MAYBE, then AWAITING_APPROVAL / YES | needs `scope_verified` + `customer_screened`; after Michael attests both (owner login) and a recheck it is a YES |
- **Change:**
  - `fixtures/sources/training_examples.json` (new) and `tools/bootstrap_dev.py`: the default fixture in the printed worker command, plus `fund_dev_bankroll` (`--bankroll`, default 500, 0 = unfunded): the owner funds the dry-run ledger, receipted, idempotent, so the engine and cards use a stated figure.
  - `spine_d.fund_bankroll` (owner login, 04 `capital_fund`).
  - **Fix found by this task:** `spine_d.record_attestation` wrote `attestation.<key>` but lane C reads `attestation:<key>`, so an attestation never reached the score. It now writes `attestation:<key>` through D-29's `mbos.record_attestation` (OWNER login only; the workflow login is refused; verified in the A-40 test).
  - **Fix found by this task:** after any new research (an attestation) `mbos recheck` failed with "provenance already exists with different content": lane C derives the enrichment provenance id from the scored inputs, so the same id comes back with a longer `derived_from`. `record_lane_provenance(..., lineage_may_grow=True)` (used only by the economics enricher) returns the stored id in that case; any other difference is still an error. Proposed for lane C: put `derived_from` into the key (not changed here).
- **Evidence (real PG16, lane D split logins, `production.build_components`, lane E gateway, DBOS):** `tests/integration/test_a41_training_examples.py` (6; runner mode `training_set`), `test_a40_audit_fixes.py`, `test_bootstrap_dev.py`. Each card passes `validate_card`; every datum basis is FACT / INFERENCE / RECOMMENDATION / UNKNOWN. Full suite: 467 passed, 0 failed.
- **Known limits:** the TV YES depends on the illustrative sell price ($95, INFER) and on the evidence flags set on the record (comps, condition, demand, seller screened); these are fixture assumptions, not market data. Running tests in this worktree needs `PYTHONPATH=src` because the venv's editable `mbos` points at the coordinator worktree.
