# Receipt — READY_QUEUE C-04 (lane B support): sold-comps sources

- **Date:** 2026-10-07 · **Actor:** Agent 02 (support). **Lead:** Agent 03 (C-04 DONE @ `882c726`).
- **Coordination:** proposal and amendments by cross-session messages between Agent 02 and Agent 03, both recorded in AGENT_STATUS.
  - `price` only
  - add `fetched_at` and `raw_ref`
  - 03 assembles the bundle
  - source names `manual` and `ebay_marketplace_insights`
- **External effects:** none.
  - No call to eBay. Marketplace Insights runs from hand-built fixtures; it is Limited Release and not approved.
  - Docs read: developer.ebay.com Marketplace Insights overview and release notes (via search).
  - Agent 03's engine was installed read-only from `git archive 882c726`; nothing merged.

## Acceptance: "A 02-fixture flip with comps advances RESEARCHING → SCORED with FACT-tagged comp provenance" — MET (FACT)
- `tests/test_c04_comps.py`, end to end with Agent 03's real `research_step`:
  - 7 candidates; 2 rejected for vocabulary conflict (5x8, 7x14); 5 selected
  - estimate `estimated`; state → SCORED; verdict MAYBE
  - selected comp provenance is all FACT
- Source side (7 tests):
  - shape and provenance
  - dedup and corrections keep identity
  - Insights gating and restricted scope
  - shared gate (PANIC, 429 freeze)
  - pre-filter is deterministic and order-independent
  - comps never become Items

## Pin bump (2026-10-07)
- Agent 03 @ `1044ed5` (engine 0.3.0, config 2026.10.1 shipped as package data; C-05 `pass_on_priors` added).
- Removed `tests/fixtures/econ_config_882c726` and the `cfg=`/`priors=` workaround.
- The acceptance test still passes and the suite is 122 green.
