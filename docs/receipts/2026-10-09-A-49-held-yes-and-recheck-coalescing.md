# Receipt: A-49 YES on a held request acts; Wake now from the UI process; rechecks coalesced per item (F-126, F-129)

DRY-RUN only. No external action, message, spend or credential change. No frozen contract or lane D schema changed.

Provenance: findings F-126 (P1) and F-129 (P2) from G-23 (`docs/qa/OPERATOR_AUDIT.md` on `research/agent-07-marketing` @ `9f276d7`); queue row A-49 on `research/agent-01-coordinator`.

## F-126 (a) YES straight from the HOLD list
Cause (FACT, reproduced by `test_a49_hold_and_recheck.py` against the unfixed code: TV stuck in `HELD` after YES): lane D's D-27 gate (migration 0022) lets an item reach APPROVED only with a YES/MODIFY `APPROVAL_DECIDED` receipt recorded AFTER the item last entered AWAITING_APPROVAL. A YES on a held request was recorded while the item was HELD; `begin_act` then moved HELD -> AWAITING_APPROVAL, so the YES predated the re-entry and APPROVED was refused (MB005).

Fix (`src/mbos/spine_d.py` `decide`): on YES for a `held` request whose item is HELD, the same owner transaction first records human provenance and moves the item HELD -> AWAITING_APPROVAL (actor michael, receipted), then records the Approval. FACT: the owner login (`mbos_operator_ui`) has no EXECUTE on `mbos.set_action_status` (tried: 42501), so the request itself moves held -> approved inside `record_approval`, as before. That is enough for D-27.

## F-126 (b) Wake now from the UI process
`mbos.workflows.ping` resolves the active gate (A-48 `gate_workflow_ids`) and falls back to a DBOSClient outside a runtime. Lane 06 switched to it in F-37 (DONE). The new test drives ping, HOLD and YES from a SEPARATE process with no DBOS runtime (`runner ui_act`), as `operator_ui.backend` does: HOLD -> Wake now -> YES -> ACTED.

## F-129 two inputs, two rechecks, duplicate provenance
Cause (INFER from the code, consistent with G-23): in one `mbos worker` loop round, a quote grows the item's research (ResearchWatcher) AND its human-input count (HumanInputWatcher). Both called `workflows.recheck`, so two `recheck:` workflows ran the same item at once. Both inserted the same lane C provenance ids (check-then-insert race): `provenance_pkey`.
Fix:
- `workflows.recheck` coalesces per item. If a `recheck:<item>:` workflow is queued or running, it is sent a `recheck` message and its id is returned. A new one is enqueued only when none is active, or when the active one finished during the send. `recheck_lifecycle` drains those messages after each pass and runs one more pass while the item is still parked.
- `record_research` and `record_lane_provenance` insert provenance inside a SAVEPOINT. A unique violation from a concurrent writer is treated as "already stored": `record_research` skips it as before; `record_lane_provenance` compares the stored content and raises only if it differs.
Residual window (INFER): a request that arrives after a recheck drained its messages but before its status turns SUCCESS is not re-run. The next input, the inbox watcher or `mbos recheck` covers it.

## Evidence (real PG16 via pgserver, lane D at `origin/research/agent-04-state`, split logins, real assembly: lane C engine + lane E gateway)
`tests/integration/test_a49_hold_and_recheck.py` (5 tests):
- TV: AWAITING_APPROVAL -> HOLD -> HELD -> YES -> ACTED, 1 `ACTION_EXECUTED`
- Drywall lead: quote $700 -> both watchers fire in one round -> ONE workflow id; two attestations -> AWAITING_APPROVAL -> HOLD -> Wake now -> YES -> ACTED, 1 `ACTION_EXECUTED`
- 2 recheck workflows in total, never concurrent; 0 ERROR workflows; 0 ERROR log records; 0 tracebacks; receipt chain ok (124 receipts)
- Same provenance inserted by two transactions at once: the second returns the id with no error. This fails with the guard removed (checked).

Observation (not changed here; proposed): ResearchWatcher absorbed the first attestation's growth as "its own re-check's entries" (round 2 queued nothing); the next round caught up.

Note: the lane venv is a symlink to the coordinator's (editable install of the coordinator worktree), so tests run with `PYTHONPATH=$PWD/src`.
