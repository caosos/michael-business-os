# Receipt: P-06-12 least-privilege approver DSN (lane 06)
- **Action:** added `MBOS_APPROVER_DATABASE_URL` support (`operator_ui/__main__.py:ui_engine`), `tests/lane_d/test_least_privilege_p0612.py`, `docs/runbooks/OPERATOR_UI_LEAST_PRIVILEGE.md`. DRY-RUN; no credentials changed.
- **Provenance:** lane D `origin/research/agent-04-state` `state/bootstrap/roles.sql`, migrations 0004, 0015, 0017 (grants read directly); results from the test run below.
- **Result:** 9 tests connect as `mbos_operator_ui` (non-superuser) and assert the DB refuses capital ledger writes, receipt edits, enrichment/doc writes and spend.
- **Unverified:** whether outcome/note/follow-up UI paths work under this role (see runbook caveat).
