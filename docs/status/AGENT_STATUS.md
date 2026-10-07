# Agent Status

Agent: 06
Role: Communications + Operator UI / Approval UX (build lane F)
Branch: research/agent-06-communications
Worktree: /home/michaelos/business-os-worktrees/agent-06-communications
State: WAITING
Claimed: none
Done: F-01 @ 190bb9b (+ notify_decision follow-through @ e2e42f8) · F-02 @ fc31896 · F-03 @ cb787dd · F-05 @ acb7c52 · F-06 @ 5abf51e · F-07 @ 36ce9a4 · F-08 @ 9d75e44
Blocked: F-04 on A-03
Started: 2026-10-06 (Round One) · 2026-10-07 (Round Two)
Last updated: 2026-10-07

## Current objective
WAITING. No READY task for 06 or ANY remains (checked READY_QUEUE after F-08). **F-04** is BLOCKED on **A-03**. Proposed next: P-06-8 (lane A `propose_followup` API, then a lane-F UI button).

## Done
- **F-08 @ `9d75e44`:** `plan_followup` / `plan_offer` / `plan_quote` each draft their own ActionRequest.
  - Binding drafts use `offer.<channel>.send`, so the spine classifies them as category `offer` (tier 0, irreversible, step-up). An offer is never drafted above the ask.
  - The effector blocks binding drafts under `comms.*`.
  - On the spine, YES without step-up is refused, and there are 0 effector calls (nothing auto-sends).
  - 85 tests pass. Receipt: `docs/receipts/2026-10-07-f08-followup-and-binding-drafts.md`.
- **F-07 @ `36ce9a4`:** consent ledger + DNC scrub store.
  - Schema `mbos_comms` is insert-only and PROPOSED for lane D. Raw contact values live only in `contacts`.
  - Each consent, revocation or STOP, and DNC scrub is written in one transaction with provenance and a chained receipt.
  - `ConsentLedger` lookups fail closed.
  - **On the real spine, E2 is graded PASS and E4 PASS**; without consent the send is blocked → ACTION_FAILED.
  - A-13 is verified: the shim is removed. 72 tests pass.
  - Receipt: `docs/receipts/2026-10-07-f07-consent-ledger-dnc-store.md`.
- **F-06 @ `5abf51e`:** `comms_spec/effector.py` `CommsDryRunEffector`.
  - Exactly once (it replays before evaluating) and sends only the frozen `payload.comms` draft.
  - Fail-closed checks: template integrity, E1 disclosure, E3 window, rate limits and DNC. Consent is recorded as `not_evaluated`.
  - Blocked attempts are recorded with `status=blocked`.
  - On a spine run, `audit()` grades E1/E3/E6/E7 PASS, E2 DRY_RUN_EXEMPT and E5 not testable. A7 has 0 exceptions.
  - Receipt: `docs/receipts/2026-10-07-f06-comms-dry-run-effector.md`.
- **F-05 @ `acb7c52`:** `comms_spec/planner.py` `CommsActionPlanner`. It drafts first contact only, carries a `comms` block (template_id, MBOS-CJSON-1 template_hash, rendered draft, constraints) and sanitizes listing text. Contract-valid flip and service proposals. **A-13 must merge `payload_extension(pa)` into the payload.** Receipt: `docs/receipts/2026-10-07-f05-comms-action-planner.md`.
- **F-01 follow-through @ `e2e42f8`:** the UI now calls the spine's `mbos.workflows.notify_decision` (A-07, which closes P-06-1). The spine is re-pinned to `bf215b2`, and a new test covers R12: a YES on a HELD item re-presents it, then executes once. 42 tests pass.
- **F-03 @ `cb787dd`:** comms dry-run spec as data in `comms_spec/`:
  - a template registry with ADR-0010 content hashes and binding flags; every template is a draft pending Michael;
  - Q&A for all 10 flip and all 9 service categories;
  - send-window, rate, consent, DNC and opt-out policy;
  - E1–E7 thresholds;
  - pure checks and a receipt auditor.

  There is no send path, and a test enforces that. Spec: `docs/research/agent-06-comms-spec.md`. Receipt: `docs/receipts/2026-10-07-f03-comms-spec-data.md`.
- **F-02 @ `fc31896`** (ADR-0010):
  - `operator_ui/mbos_canonical.py` is a byte-identical copy of the reference.
  - The card verifies `payload_hash` independently, and offers YES only on a match.
  - The ledger re-verifies the chain with MBOS-RH-1 in Python.
  - **Interop row 06 = 10/10 CONFORMS** (with row 06 repointed; see coordinator review).
  - The spine is re-pinned to `99e9ec0`. 15 tests pass. Receipt: `docs/receipts/2026-10-07-f02-adr0010-conformance.md`.
- **F-01 @ `190bb9b`** (ruling R10): the Operator UI runs on the spine.
  - Every YES/NO/MODIFY/HOLD is `mbos.spine.decide(channel="web")` in one transaction, plus a DBOS wake.
  - HOLD timers live in the item workflow. "Wake now" sends `michael_ping`.
  - The UI's own gateway, `tick()`, SQLite ledger, mock effector and seed data are removed. A test guards against them coming back.
  - Kept: cards, CSRF, loopback-only, Host check, PIN step-up, HOLD presets.
  - **11 tests pass against the real spine** (DBOS + pgserver Postgres 16; `mbos` pinned at `bed7609`, installed, not merged).
  - Receipt: `docs/receipts/2026-10-07-f01-operator-ui-on-spine.md`. Spec: `docs/research/agent-06-operator-ui.md`.
- Wave one (`3e51ba4`): first UI with a SQLite stand-in, 29 tests. Superseded by F-01.
- Round One: comms research, ADR-001/002, receipts 01–04.

## Findings (F-01)
- FACT: `notify_decision`, named in R10, does not exist in the spine at `bed7609`. The UI uses the same wake as `mbos decide` (`DBOSClient.send(item:<id>, …, topic="decision")`).
- FACT: the item workflow acts on `hold_until`, `escalate_after`, `renotify_after` and `michael_ping`, but **not** on `new_info`, `price_change` or `auction_ending` in `wake_on`.
- FACT: the spine always archives after NO, so the UI's "archive?" checkbox was removed.
- INFERENCE: `SpineBackend.components` must equal the worker's `Components`, because `spine.decide` classifies MODIFY successors with the PDP. This matters once A-03 wires 05's PDP.

## Blockers
None.

## Needs Michael decision
None. Live comms stay disabled (MICHAEL_DECISIONS #4).

## Needs coordinator review
- Resolved in `bf215b2`: interop row 06 now points at the vendored reference. P-06-1 became A-07 (DONE), P-06-2 became A-08 (READY, lane A), and P-06-3 became F-04 (BLOCKED on A-03).
- **A-13 requests (from F-05/F-06):**
  1. `_propose` merges `payload_extension(pa)` into the payload before hashing.
  2. `finish_act` maps `effector_response.status=="blocked"` to ACTION_FAILED.
  3. Optionally, merge `effector_response.comms` into `details`. F-06's acceptance text says the checks belong in `details`; the gateway at `0d107df` builds `details` itself, so they ride in `effector_response.comms` today, and `audit()` reads either location.
- **FINDING (spine @ `aa88e7a`, lane A):** receipt `seq` comes from `nextval()` in `mbos.receipts_chain()`. A rolled-back receipt transaction (including A1 fault injection) therefore leaves a seq gap. `mbos.verify_chain()` checks links only and stays ok; the ADR-0010 reference `verify_chain` reports `gap before seq N`. Pinned by `tests/test_operator_ui.py::test_finding_spine_seq_gap_after_rollback_is_flagged_only_by_the_reference`. R1 (lane D's gapless chain) should close it. Until then the two verifiers disagree.
- **F-07 DDL:** `comms_spec/sql/0001_comms_ledger.sql` (schema `mbos_comms`) is PROPOSED for lane D to adopt or port (R1: 04 owns DDL).
- **ADR-0009 request:** add receipt types CONSENT_RECORDED / CONSENT_REVOKED / DNC_SCRUB_RECORDED. Under v1.0.0 these events use GRANT_CREATED/GRANT_REVOKED with `entity_type` `consent` or `dnc_scrub`.
- The comms policy values in `comms_spec/data/comms_policy.v1.json` are PROPOSED (conservative). Loosening any of them is a version bump.

## Proposed tasks
- P-06-4 became F-05 (DONE) and P-06-5 became F-06 (DONE).
- P-06-6 became F-07 (DONE).
- P-06-7 became F-08 (DONE).
- **P-06-8 (lane A, then F):** a public `spine.propose_followup(conn, item_id, proposed_action)` plus an approval-gate workflow for follow-up requests on an existing item (the R12 edge ACTED → AWAITING_APPROVAL exists, but there is no API). F-08's tests use the internal `_propose`. Lane F would then add "Draft follow-up / offer / quote" on the UI card.
- **P-06-9 (lane A, small):** `finish_act` reads `response.get("blocked")` for the reason text, but the F-06 effector reports `comms.blocked_reasons`. The reason falls back to "see details", so a one-line read of `response["comms"]["blocked_reasons"]` would make ACTION_FAILED intents self-explanatory.

## Files (Round Two, current)
- `operator_ui/` (`backend`, `ux`, `views`, `server`, `__main__`, `mbos_canonical`), `comms_spec/` (+ `planner.py`, `effector.py`, `data/*.v1.json`), `tests/` (conftest, test_operator_ui, test_comms_spec, fixtures/illustrative.json)
- `docs/research/agent-06-operator-ui.md`, `docs/decisions/ADR-06-003-operator-ui-stdlib.md`, `docs/receipts/2026-10-07-*.md`
- `docs/research/contracts/` (byte-identical frozen v1.0.0)
