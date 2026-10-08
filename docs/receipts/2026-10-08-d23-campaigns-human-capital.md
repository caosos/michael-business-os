# Receipt: D-23 (human-only capital/mission in the DB; campaign persistence)

- Timestamp: 2026-10-08
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): READY_QUEUE rows D-23, A-26, E-17 on `origin/research/agent-01-coordinator`; `campaign.schema.json` (blob `3aaa342`) and `trailer-wanted.example.json` (blob `886257d`) vendored into `state/tests/contracts-additive/`; migrations 0017/0018 of this branch.
- Mode: DRY-RUN. Throwaway pgserver PG16 databases only; nothing persistent, nothing contacted.

## Built
`state/migrations/0019_campaigns_human_capital.sql`, `state/tests/test_campaigns.py` (9 tests).
- (a) F-78: `mbos._require_human_owner` is called first in `set_mission` and `_capital_owner_receipt` (so `capital_fund` and `capital_withdraw`). A session that is not an `agent_write` member must pass actor `{type: human, id: <non-empty>}`, else 42501. Same rule as 0018.
- (b) `mbos.campaigns`: insert-only revisions, PK (campaign_id, revision); columns are CHECKed to equal the body; `campaign_active_only_up_to_recommend` CHECK (E-17 mirror); deferred receipt trigger. `set_campaign` / `cancel_campaign` (approver only, human actor, CONFIG_VERSION_BUMPED receipts with entity_type `campaign`, idempotent). Cancel appends a CANCELLED revision. View `v_campaigns_current` = latest revision per campaign.

## Acceptance
- FACT: as login `mbos_operator_ui`, agent / system / blank-id / id-less actors are refused for capital_fund, capital_withdraw, set_mission (and set/cancel campaign); no ledger rows; a human still works.
- FACT: set/revise/cancel produce receipts (create, update, update) and `verify_chain` is OK; the view shows revision 3 CANCELLED, history kept (3 rows).
- FACT: ASSISTED_DEAL and BOUNDED_AUTOPILOT cannot be stored ACTIVE (CHECK); they can be PAUSED; WATCH_ONLY/RECOMMEND ACTIVE work.
- FACT: agent_write / gateway / policy_admin / reader cannot call set_campaign or insert directly; updates/deletes are refused.
- Health (`cd state && .venv/bin/python -m pytest`): **255 passed, 1 skipped, 0 failed** (246 + 9 new).

## Limits
- INFER: the SQL body check is structural (required keys, enums, autopilot limits present); full JSON-Schema validation is done in tests against the vendored schema, not in the database.
- `agent_write` sessions (e.g. `mbos_dbos`) are exempt from the human-actor rule by the F-78 wording; they remain bound by the approver-membership check, and R14 keeps these paths out of workflows.
