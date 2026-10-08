# Receipt: D-26a (workflow login loses `approver`; provision() creates the owner login)

- Timestamp: 2026-10-08
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue row D-26a (ruling by 01); `state/bootstrap/roles.sql`, `state/mbos_state/provision.py`, migrations 0007/0017/0018/0021.
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only; nothing persistent, nothing contacted.

## Built
- `roles.sql`: `mbos_dbos` is granted `agent_write, gateway` only; `REVOKE approver, owner_channel FROM mbos_dbos` makes existing clusters converge on re-run. No migration needed (role membership, not DDL).
- `provision.py`: `Provisioned` now also carries `owner_login` (`mbos_operator_ui`), `owner_app_conninfo`, `owner_app_url`; new `owner_password` argument. CLI `provision` prints `owner_login` and `owner_app_url`.
- Tests: new `test_workflow_login.py` (3 facts below); lane-D tests that approved/closed/decided as `mbos_dbos` now do so as the owner login (`test_capital_ledger` human closes, `test_d13_review`, `test_r1_integration`, `test_provision` panic release).

## What the workflow path needs, and how it works now
| Operation | Before | Now |
|---|---|---|
| `decide` / `record_approval` (YES/NO/MODIFY/HOLD) | mbos_dbos (approver) | owner login only; mbos_dbos gets 42501 |
| operator note (`record_operator_note`) | mbos_dbos | owner login only |
| capital fund/withdraw, mission, set/cancel campaign | owner_channel (D-25) | unchanged: owner login only |
| PANIC release (`panic_set` engage=false) | mbos_dbos | owner login only. PANIC engage still works for mbos_dbos via `gateway` |
| human outcome close with realized capital | mbos_dbos | owner login (`Cap.close` in tests). mbos_dbos still records agent outcomes (`agent_write`) |
| gateway/effector settlement (`set_action_status` executing/executed, item ACTING/ACTED, budget_*) | gateway | unchanged, as mbos_dbos |
| ingest, items, propose_action, outcomes (agent) | agent_write | unchanged |
Workflow design consequence (FACT): a DBOS workflow waiting on Michael must receive the decision from a call made by the owner login (Operator UI/CLI), then continue and settle as mbos_dbos; it can no longer record the decision itself.

## Acceptance
- FACT: as the real `mbos_dbos` (provision()): `record_approval`, `record_operator_note`, fund, withdraw, set_mission, set_campaign, cancel_campaign refused 42501; panic release refused; as `mbos_operator_ui` approval, note, fund and set_campaign work; with that approval `mbos_dbos` settles executing -> executed (verify_chain OK).
- FACT: role sets exactly `mbos_dbos = {agent_write, gateway}`, `mbos_operator_ui = {approver, owner_channel}`; `provision()` returns both URLs and the owner URL connects.
- FACT: health `cd state && .venv/bin/python -m pytest`: 282 passed, 1 skipped, 0 failed.

## Limits / findings
- FINDING (not fixed, out of scope): item edge `AWAITING_APPROVAL -> APPROVED` has `allowed_roles = NULL` (0002), so `transition_item` to APPROVED is not role-gated; any agent_write/gateway login can move the item state (the action request still needs a real approval to execute). Propose a follow-up to gate it to approver.
- INFER: existing clusters must re-run `roles.sql` (or `provision()`) to drop approver from mbos_dbos. A live DBOS app that records decisions itself (01's `spine_d.decide`) will now get 42501 by design and must use the owner login.
