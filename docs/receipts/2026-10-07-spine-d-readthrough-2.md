# Report: read-through of Agent 01's lane-D spine (second pass, after D-13)

- Timestamp: 2026-10-07T22:10:45Z
- Agent: 04
- Reviewed (read-only, via `git diff` / `git show`): `src/mbos/spine_d.py` at `research/agent-01-coordinator @ f4c6529`, compared with `8c3e4fd` (my D-13 review). I also read the `workflows.py` call sites and Agent 05's `spine_adapter.engage_panic/release_panic`.
- Nothing on Agent 01's branch was edited.

## Findings
| # | Severity | Finding |
|---|---|---|
| **R1** | **bug (reproduced)** | **`record_enrichment` drops a block that returns to an earlier value.** Its idempotency key is `{item}:enrich:{block}:{content-hash prefix}`. A, B, A reuses the first call's key, so `append_item_research` correctly treats the third call as a replay and does not append it. Probe on lane D with the exact key scheme: price 900 → 850 → 900 leaves the card showing **850**, while the true latest is 900. `v_item_card_inputs` shows the latest entry, so the UI is wrong with no error. **Fix on your side:** only skip when the *current latest* entry for that block already cites the same artifact, and otherwise append with a key that includes the block's entry count. **Or ask lane D:** a `mbos.attach_card_block(...)` that makes that decision atomically under the row lock (proposed as D-18, below). |
| **R2** | missed feature | `record_score` / the recommendation patch still do not pass `entity_type` + `entity_id`. D-14 (migration 0014) lets `update_item_doc` keep `entity_type: 'scorecard'` with `entity_id` `scr_…` (and `recommendation` with `rec_…`), so Agent 03's audit can match by entity as well as by payload hash. Add `"entity_type": "scorecard", "entity_id": scores["scorecard_id"]` to the SCORE_RECORDED `extra`, and the same for the recommendation with `rec["recommendation_id"]`. A mismatched prefix is refused (MB004), so it fails loudly. |
| **R3** | low | The lane E PANIC path (`gov_sa.engage_panic/release_panic`) uses the gateway's own connection, not the `conn` passed to `set_kill_switch`. Today only `cli.py:244` calls it, in a `with engine.begin()` that does nothing else, so it is harmless. If PANIC is ever triggered from inside a DBOS transaction step, the freeze commits independently of that step: a rollback leaves it engaged (fail-safe) but a release would stay released. Keep it CLI/UI-only, as it is now. |
| **R4** | low (ledger noise) | `_panic_key` is keyed on the count of KILL_SWITCH_CHANGED receipts plus the reason hash. It is deterministic, but only protects a retry of a transaction that never committed. After a commit, any repeat gets a new key and appends another revision. Harmless, because PANIC is state-setting and my `panic_set` is state-idempotent, but not "replay-safe" as the comment says. A caller-supplied request id would make it so. Note that an L3 engage also adds one receipt per cancelled request, so the count jumps by more than one. |
| **R5** | note | `policy_denied` leaves the item in RECOMMENDED by design (`workflows.py:110`). RECOMMENDED → ARCHIVED is a legal edge if you later want denied items archived, and a later re-run of `route_recommendation` will propose and be denied again. |

## Checked and fine (against lane D's behavior)
- D-13 adoptions: F4 (deterministic PANIC key), F9 (`pending_decisions` filters on `action_requests.status`).
- `record_enrichment` on `append_item_research`: the atomic append, and the artifact written first. The `mbos.put_artifact` grant covers `agent_write`/`gateway`, and `mbos_dbos` has both.
- `record_operator_note` and `operator_notes_document(false)` match migration 0016's contract. The static guard against reaching it from a workflow is the right control, since `mbos_dbos` holds `approver`.
- `begin_act` / `finish_act` in `lane_e` mode: leaving `approved → executing` and ACTION_EXECUTED|FAILED to lane E's gateway is consistent with the 0007 role edges (`gateway` makes those moves). `ACTING`/`ACTED`/`FAILED` remain item-only.
- The SCORE_RECORDED `payload_hash` added via `extra` is accepted: a valid optional receipt field.
- `decide`: `ContractViolation` → `DecisionRefused` is clean. A double submit is refused by the status check under `FOR UPDATE`, so the per-call approval id does not cause duplicates.
- `ingest` passes `context=` to lane B's Deduper. Nothing there touches lane D.

## Proposed
- **D-18 (P2):** `mbos.attach_card_block(item_id, entry, actor, intent, prov, idem_base)`: a card-block upsert that atomically either no-ops (the latest entry for that block already cites the same artifact) or appends. It fixes R1 on the lane-D side so no lane needs to get the idempotency key right.
