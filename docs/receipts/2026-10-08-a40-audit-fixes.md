# Receipt: A-40 audit fixes, wave 1 (F-88, F-89, F-91, F-92, F-96, F-101, attestation)

- **Task:** A-40 (P0), lane 01, branch `worker/a-40-audit-fixes`. DRY-RUN only; no network, no contact, no spend. Frozen contracts untouched.
- **Provenance:** lane D (Agent 04) `capital_position_document`, `panic_current`, `append_item_research` as shipped on `origin/research/agent-04-state`; lane C `mbos_economics` (`score_item`, `research_step`) as installed. Nothing in them changed.
- **Change:**
  - F-88 `tools/bootstrap_dev.py` prints the UI command with the one canonical variable `MBOS_OWNER_DATABASE_URL` (written by `var/owner.env`).
  - F-89 bootstrap releases the initial global freeze as the OWNER login (receipted by lane D, dev only) and prints it; `--keep-frozen` leaves it and says so.
  - F-91 `spine_d.record_lane_provenance` is idempotent for identical content (timestamps compared as instants); different content under one id raises. A second `mbos recheck` is clean.
  - F-92 `src/mbos/inbox.py` `InboxWatcher`; `mbos worker` ticks it every 60 s (first tick counts files already present) and re-checks the RESEARCHING items itself.
  - F-96 `src/mbos/adapters/ledger.py` `LedgerContext` reads `capital_position_document('dry_run')`; scorer and researcher put `economics.context.available_to_deploy` into the scored Item (explicit value wins; unfunded ledger = UNKNOWN, never 0). The card's `current_cash_context` falls back to the ledger figure (FACT) when Michael's profile states none.
  - F-101 `tools/sync_lanes.find_uv()`: `.tools/uv`, then PATH, then the venv's, else `pip install uv` into the venv.
  - `spine_d.record_attestation(conn, item_id, evidence_key, note, entered_by)`: Item research entry `attestation.<key>`, basis FACT, source `human:<who>`, provenance actor_type human; idempotent; atomic via 04's `append_item_research`.
- **Evidence (real PG16, lane D provisioned with split logins):** `tests/integration/test_a40_audit_fixes.py` (4), `test_bootstrap_dev.py` (2: RUNNING after bootstrap; `--keep-frozen` stays FROZEN), `test_comps_wiring.py::test_worker_inbox_watcher_moves_a_parked_item_without_a_command`.
- **Known limits / for C-25, F-29:**
  - Lane D grants `append_item_research` to `agent_write` only, so `record_attestation` must run on a WORKER-login connection; the owner login gets permission denied. The human identity is therefore asserted by the calling process (the UI), not enforced by the DB login. Recommend 04 grant it to `approver`, or the UI calls through a service function (F-29 decision).
  - Lane C's config `operator_context.current_cash` is the single source for the stated cash inside the engine and `economics.context.current_cash` is rejected by lane C, so the stated profile cash reaches the CARD (profile, else ledger) but not the engine score.
