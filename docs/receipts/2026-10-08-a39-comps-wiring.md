# Receipt: A-39 comps wiring + `mbos recheck`

- **Task:** A-39 (P0), lane 01, branch `worker/a-39-comps`. DRY-RUN only; no network, no contact, no spend.
- **Provenance:** lane B `mbos_discovery.comps` (`CompsStore`, `ManualCompsAdapter`, `candidate_comps`, `asking_comps_from_items`) and lane C `mbos_economics.comps_feed.research_step`, both as installed by `tools/sync_lanes.py`; nothing in them changed.
- **Change:**
  - `src/mbos/adapters/comps.py` `ProductionCompsSource`: re-reads, on every call, the persisted `comps.json` (`MBOS_COMPS_STORE`), the manual inbox (`MBOS_COMPS_INBOX`, normalized by lane B with human provenance) and asking comps from retained listings (`items.json` beside the store; kind `asking`, fenced INFER by lane C); `candidate_comps` selects per Item.
  - `production.build_components` wires `EconomicsResearcher(ProductionCompsSource)` and reports `research (comps)` REAL with the source, or `STAND-IN: none ...`.
  - `workflows.recheck_lifecycle` + `workflows.recheck()`; `mbos recheck [ITEM_ID]` (default: every RESEARCHING Item) enqueues on the `rechecks` queue, executed by the running worker (it holds the comps source). Own workflow id, since `item:<id>` is spent.
  - `tools/bootstrap_dev.py` writes `MBOS_COMPS_STORE`/`MBOS_COMPS_INBOX` into `var/dev.env` and creates `var/comps_inbox/`.
  - `fixtures/sources/no_economics.json` (listing without inline economics).
- **Evidence (real PG16 + DBOS, `tests/integration/test_comps_wiring.py`):** with an empty inbox the listing parks at RESEARCHING and the workflow returns lane C's gap text; after four manual comp files, `workflows.recheck` moves it through SCORED with lane C's scorecard, economics and a recommendation recorded.
- **Known limits:** lane C's `as_of` is the Item's own `updated_at`, so a comp dated after that is not selected; the Operator UI form that writes the inbox is F-28. A single comp file is not enough for lane C to estimate (it needs several; the card says so via the gap text).
