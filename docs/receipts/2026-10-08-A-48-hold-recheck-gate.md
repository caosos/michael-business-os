# Receipt: A-48 HOLD wake / decision reach the recheck gate (F-120)

DRY-RUN only. No external action, message, spend or credential change.

Provenance: finding F-120 (queue row A-48, Agent 01 coordinator branch `research/agent-01-coordinator`).

Cause (FACT, reproduced by `test_a48_hold_wake_yes_reaches_acted_through_a_recheck_gate` against the unfixed code: item stuck in `HELD` after the ping): an Item that parked at RESEARCHING has a spent `item:<id>` workflow. After `mbos recheck` its approval gate runs in `recheck:<id>:<ms>-1` (the child `item_lifecycle` of the `recheck_lifecycle` parent). `ping`, `notify_decision`, `notify_event` and `record_decision` all sent to `item:<id>`, so a wake or decision never reached the waiting gate.

Fix (`src/mbos/workflows.py`): `gate_workflow_ids(item_id)` looks up the ACTIVE workflows for the item (prefixes `item:<id>`, `recheck:<id>:`), keeps the leaf (the child that waits, not its parent), and falls back to `item:<id>` if none is active. `_send_gate` sends through it (DBOS in a runtime, else DBOSClient) and replaces the four hard-coded sends. No new workflows are started, so no orphan gates. A second recheck while a gate is parked is skipped by `item_lifecycle` (state not NORMALIZED/RESEARCHING).

Test: comp saved -> recheck-started gate -> HOLD -> ping -> YES (step-up) -> ACTED with an `ACTION_EXECUTING` receipt, then no active workflow left for the item. The researcher is a small stand-in (park without comps, YES-scoring placeholder with comps) because a real YES from lane C needs four human attestations that the default state backend does not support; the test is about the gate.

Note: the lane venv is editable-installed from the coordinator worktree; run tests with `PYTHONPATH=$PWD/src`.
Health: full suite 486 passed, 0 failed (real PG16, PYTHONPATH=$PWD/src).
