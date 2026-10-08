# Receipt: G-19 re-verify of D-28 (04 0023) and F-27 (06) (DRY-RUN)

- Agent: 07 QA. Date: 2026-10-08. Task: G-19 (P0 safety). Deps: D-28, F-27 (DONE).
- Provenance (FACT): re-pinned in `qa/impl_lane_pins.json`, read via `git archive` only: 04 `4a11f1b` (schema = `4a0148a`, migration 0023), 06 `3090e51` (F-27 `7756448`); mbos stays `71d5cdb`, 05 `716098e`. Real PostgreSQL 16 (pgserver), real logins `mbos_dbos` (agent_write+gateway) and `mbos_operator_ui` (approver+owner_channel).
- F-85 FIXED (FACT): as `mbos_dbos` the combined bypass (human-claimed KILL_SWITCH_CHANGED receipt + direct RUNNING panic_state INSERT), each half alone (new test), and `panic_set`/`panic_mutate` release are all refused; state stays FROZEN. PANIC ENGAGE by `mbos_dbos` still works; owner login still releases.
- F-86 FIXED (FACT): forged human `record_outcome` from `mbos_dbos` refused, no receipt written; owner login still records a human outcome, chain verifies.
- F-84 FIXED (FACT): 16-thread concurrent `/wanted` create: all losers see 303 (5/5 runs); marker removed, test is now a plain assertion.
- Strict xfails F-85/F-86 flipped (assertions unchanged); `FINDING_STATUS` updated.
- QA harness fix (FACT): `_split_e2e.py` read the item state once right after the request settled and raced the workflow's ACTING->ACTED (failed ~50%); it now polls (bounded 60s) for ACTED. Assertion unchanged.
- Health: RC READY 105 passed / 3 skipped / 0 failed; card 671 passed / 0 failed; `run` completed; `tests/owner_channel` + `tests/numbers` 231 passed / 1 skipped / 0 failed (incl. split e2e).
- Not done: F-87 (two-process topology, 01 `fcf1bbe`) not re-attacked here; mbos pin not moved.
- No sends, spend, publish, credential change or CAOSCare contact. Writes only to throwaway PostgreSQL clusters under /tmp/a07pg-*.
