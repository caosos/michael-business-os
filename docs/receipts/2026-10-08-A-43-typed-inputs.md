# Receipt: A-43 Michael's typed inputs (quote, scope override) and the worker re-check

DRY-RUN only. No external action, message, spend or credential change.

Provenance: READY_QUEUE row A-43; D-30 (`mbos.record_human_input`, migration 0025 on `origin/research/agent-04-state`); C-28 (lane C reads `quote:amount_usd`).

| Piece | Change | Evidence |
|---|---|---|
| Wrapper | `spine_d.record_human_input(conn, item_id, kind, key, value, note, entered_by)`: human provenance inserted first (like `record_attestation`), then D-30's function. Refuses blank fields, an unknown kind, bool, NaN, inf, non-numeric values in Python (`ValueError`); D-30 enforces ranges and key shape. Same input again is a no-op; a changed value is a new entry (latest wins). | `test_human_input_is_stored_with_human_provenance_and_the_workflow_login_cannot_forge_it` (owner login stores FACT/INFER entries with `human:michael`; the workflow login `mbos_dbos` is refused; D-30 refuses 0, negatives, bad keys) |
| Re-check trigger | `inbox.HumanInputWatcher` plus `cli._parked_human_input_counts`, wired into `mbos worker`'s loop: counts only `quote:`/`scope_override:` entries on RESEARCHING items and queues `workflows.recheck` when the count grows. It counts only entries a re-check never writes, so unlike `ResearchWatcher` there is nothing to absorb and an input made mid-re-check is not lost. | `test_worker_rechecks_a_parked_item_when_michael_enters_a_quote` (real SQL on PG16); `test_human_input_watcher_ignores_unrelated_growth_and_baselines_first_sight` |

Limits (INFER): the trigger covers items parked at RESEARCHING (where a MAYBE verdict lands and the only state `item_lifecycle` re-runs). An item first seen by the watcher is only baselined, so an input entered before the worker's first tick relies on the worker-start recovery, as for attestations. UI form is F-32 (lane 06).

Note: the lane venv is editable-installed from another worktree; run with `PYTHONPATH=$PWD/src:.`.

Health (real PG16 via pgserver, PYTHONPATH=$PWD/src:.): full suite 485 passed, 0 failed (was 482 + 3 new tests).
