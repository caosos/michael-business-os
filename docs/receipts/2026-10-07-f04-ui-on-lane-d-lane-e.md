# Receipt: F-04, Operator UI on lane D with lane E's real Components

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-04` (unblocked by A-03; claimed in `d60a731`)
- **Intent:** the UI uses the worker's real Components (Agent 05's gateway, PDP and kill switch) on Agent 04's canonical store, as a human channel only (R14).
- **Effect:** this branch only. pgserver clusters exist only inside pytest temp dirs. No sends, no network.

## Provenance
| Input | Ref |
|---|---|
| Spine | `mbos` @ `ca6d056` (git archive, installed, not merged): `spine_d`, `adapters.governance.lane_e_components`, `adapters.state04.Pg04Ledger` |
| Lane D schema | `origin/research/agent-04-state:state/` via `git archive` (migrations 0000–0014, roles.sql), built with lane D's own migrator |
| Lane E | `origin/research/agent-05-governance` @ `101a7e6`: package installed from git archive; the **whole `policy/` directory** extracted (policy, schema, content rules, sandbox) |

## What changed
- `SpineBackend(engine, components, lane="reference"|"lane_d")`. On lane D, reads use lane D's contract-document views (`v_item/action_request/approval/provenance/outcome_documents`, `v_receipt_documents`), and system state comes from the sealed PANIC state (`mbos.panic_read()`: unreadable or FROZEN → FROZEN). Writes go only through `mbos.spine_d.decide` / `record_outcome`. The chain is checked by lane D's `verify_chain` and re-checked in Python with the ADR-0010 reference.
- `python -m operator_ui serve` with `MBOS_STATE_BACKEND=lane_d` (+ `MBOS_POLICY_PATH`, or unset to read lane D's `policy_current`) builds the UI with the SAME Components as the worker via `lane_e_components`, because `spine_d.decide` classifies a MODIFY successor with the PDP.
- Tests split in two processes (DBOS is a per-process singleton): `tests/test_*.py` (reference) and `tests/lane_d/` (`MBOS_UI_LANE_D=1`). `tools/run_tests.sh` runs both.

## Verification (FACT)
- Reference suite: `108 passed`. Lane D + lane E suite: `9 passed`, on a real DBOS runtime with `state_backend="lane_d"`, `gateway_mode="lane_e"`.
- The UI's Components are the lane-E objects. Cards, ledger, holds, outcomes, sources, summary and digest pages render on lane D.
- YES (with step-up): exactly one ACTION_EXECUTING and one ACTION_EXECUTED, both written by the gateway (R4). 1 effector call, 0 live. The frozen payload hash is unchanged, and the lane D and reference chain checks agree.
- NO needs a reason and archives. MODIFY's successor gets a POLICY_DECIDED receipt from Agent 05's PDP, and neither request executes until its own YES. HOLD → "Wake now" re-presents and never executes. Outcome entry records `mbos.web.outcome`.
- Global freeze before YES: the decision is recorded, the real gateway refuses, there is **0 effector calls**, and the item ends FAILED.
- `comms_spec.ledger.ensure_schema()` returns `skipped` on lane D (migration 0011 owns `mbos_comms`).

## Limits and findings
- **Superuser tests:** the pgserver user is a superuser, so these tests do not exercise lane D's role grants (approver vs gateway). Wiring the UI to a least-privilege approver DSN is still open, and R14 expects Michael's UI to use a human role.
- **FINDING (lane A/E, not changed here):** after a global freeze, a YES leaves the ActionRequest in status `approved` (receipt ACTION_FAILED, item FAILED). The reference gateway moved it to `cancelled_by_freeze`, and Agent 05's docs list that edge. Pinned as observed behaviour in `test_frozen_system_denies_at_the_real_gateway`.
- Consent GRANTED / DNC CLEAR on lane D need the gateway role (D-10). The UI records neither.
