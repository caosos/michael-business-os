# Receipt: P-06-18 outcome/note paths under the least-privilege UI role (lane 06)
- **Action:** added `tests/lane_d/test_p0618_ui_role_outcome_notes.py` (4 tests). A real HTTP server is backed by an engine that logs in as lane D's `mbos_operator_ui` (non-superuser, `approver` only). DRY-RUN; no credentials or grants changed.
- **Provenance:** lane D `origin/research/agent-04-state` migrations 0003/0004 (`record_outcome` EXECUTE granted to `agent_write` only), 0016 (`operator_notes` INSERT granted to `approver`); results from the test run.
- **Result:**
  - Operator note entered via `POST /item/<id>/note` as the UI role: SUCCEEDS (`entered_by=michael`).
  - Forbidden writes (capital ledger, receipts, items doc, budget ledger, note edit/delete) still refused (`permission denied`).
  - **FINDING (lane D, blocks half of the acceptance):** outcome entry as the UI role is REFUSED by the database (`permission denied for function record_outcome`); nothing is written and the item stays ACTED. Pinned as observed. It succeeds as the shared app role (`mbos_dbos`).
- **Fix needed (not mine):** lane D grants the human outcome path to `approver` (provenance human, actor `michael`) or provides a human-only wrapper; proposed P-06-19. Until then the UI must keep running on the shared engine for outcomes (do not set `MBOS_APPROVER_DATABASE_URL` for a deployment that records outcomes).
