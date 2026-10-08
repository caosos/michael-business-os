# Receipt: F-25 /wanted on the spine campaigns (lane 06, DRY-RUN)

- **What:** `/wanted` create/pause/resume now call `mbos.set_campaign`, cancel calls `mbos.cancel_campaign` (migration 0019, D-23), as the approver login with actor `human:<id>` (server-set author, CSRF + PIN, per-form nonce as idempotency key `f25:campaign:<action>:<id>:<nonce>`). Each change is a CONFIG_VERSION_BUMPED receipt (entity_type campaign); the flash message shows the receipt id. The page reads `mbos.campaigns` (history = one row per revision).
- **Fallback:** a DB without 0019 (`to_regclass('mbos.v_campaigns_current')` null) or a non-lane-D store keeps the F-23 local JSON file.
- **Unchanged:** ASSISTED_DEAL / BOUNDED_AUTOPILOT are refused server-side with the E-17 reason before any call; the database CHECK is a second wall. Nothing is contacted.
- **Provenance:** FACT: tests `tests/lane_d/test_wanted_f25.py` (real `mbos_operator_ui` login: 4 receipts for create/pause/resume/cancel, human actors, `verify_chain` ok, refused levels store nothing, 5x8 matches the same 6 Items). Health: `tools/run_tests.sh` = 178 passed (reference), 95 passed (lane D + E), exit 0 · exit 0. Migration source: agent-04-state `39581bd`.
- **UNKNOWN:** D-24 (agent_write exemption in `_require_human_owner`) is lane 04's; not needed here.
