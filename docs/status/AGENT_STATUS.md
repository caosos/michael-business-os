# Agent Status

Agent: 04
Role: Postgres / State / Receipts (lane D: durable business state, receipts, provenance; sole ledger owner per ADR-0010)
Branch: research/agent-04-state
Worktree: /home/michaelos/business-os-worktrees/agent-04-state
State: CLOSED (D-31 done; handoff: docs/handoff/LANE_04.md)
Claimed: none
Done: D-01 @ a0d1fbe
Done: D-02 @ a0d1fbe
Done: D-03 @ ca59e3c
Done: D-05 @ 797a4e5
Done: D-04 @ 14bd690
Done: D-06 @ 012c141
Done: D-07 @ 215a861
Done: D-08 @ d668386
Done: D-13 @ ffb9e24
Done: D-11 @ 341c5d2
Done: D-14 @ 80bb135
Done: D-15 (helper delivered @ a08dd9f; 01 to adopt in its e2e for final acceptance)
Done: D-17 @ 77d1f17
Done: D-18 @ e2c3f1b (capital ledger; see docs/receipts/2026-10-07-d18-capital-ledger.md)
Done: D-09a (PITR mechanics against a local dir; see docs/receipts/2026-10-07-d09a-pitr-mechanics.md) (ACCEPTED by Agent 03, docs/receipts/2026-10-07-d17-acceptance-review.md @ 6a20b91, who tested as each real login role)
Done: D-16 @ 3a1b004
Done: P-06-19 @ 0dbddaa (0018: UI role records human outcomes; see docs/receipts/2026-10-07-p06-19-human-outcome-ui.md)
Done: D-23 @ 39581bd (0019: human-only capital/mission in DB; campaigns; see docs/receipts/2026-10-08-d23-campaigns-human-capital.md)
Done: D-24 @ aa86cc6 (0020: human actor required on all five owner paths for every session incl. mbos_dbos; see docs/receipts/2026-10-08-d24-human-only-owner-paths.md)
Done: D-28 @ 4a0148a (PANIC release owner-only + human outcome needs owner channel, migration 0023; docs/receipts/2026-10-08-d28-panic-release-owner-only.md)
Done: D-29 @ fb6f36c (record_attestation for the owner UI login + agent_write attestation guard, migration 0024; docs/receipts/2026-10-08-d29-record-attestation.md)
Done: D-30 @ 01e4e5f (mbos.record_human_input for scope_override/quote + guard on those entry prefixes, migration 0025; docs/receipts/2026-10-08-d30-record-human-input.md)
Done: D-31 @ ba7fb89 (mbos.record_acquisition: owner UI login records an off-system purchase -> dry-run BUDGET_COMMITTED -> capital deploy; duplicate closing outcome refused, migration 0026; docs/receipts/2026-10-08-d31-record-acquisition.md)
Done: D-27 @ f6c4e15 (item APPROVED edge needs a YES/MODIFY approval receipt + approver/gateway/owner role, migration 0022; docs/receipts/2026-10-08-d27-item-approved-gate.md)
Done: D-26a @ 40a7da2 (mbos_dbos = agent_write + gateway only; provision() returns owner_app_url for mbos_operator_ui; see docs/receipts/2026-10-08-d26a-workflow-login-no-approver.md)
Done: D-25 @ cd52d6e (0021: owner_channel role, held only by mbos_operator_ui, gates the five owner paths; F-81 campaign validation; F-83 no resurrection; see docs/receipts/2026-10-08-d25-owner-channel.md)
Blocked: D-09b (off-box destination + drill) on Michael: docs/state/OWNER_QUESTION_BACKUPS.md
Blocked: D-10 (final acceptance) on A-01 phase 2. The DDL is delivered @ 6533334.
Current phase: ROUND TWO: foreman loop (READY_QUEUE)
Started: 2026-10-06
Last updated: 2026-10-07 (P-06-19)

## Current objective
**CLOSED.** A fresh bounded worker takes this lane from `docs/handoff/LANE_04.md`.
- **Outstanding:**
  - D-10 final acceptance waits on Agent 01's A-01.
  - D-12 waits on ADR-0009.
  - D-09b waits on Michael (`MICHAEL_DECISIONS` #11).
- **Agent 01 accepted my D-18 design points:**
  1. Impairment is repaired first.
  2. Capital movement is approver-only.
  3. The ledger stays inactive until funded.
  4. The entry points I listed are the ones the UI/CLI port will use.

### Interface notes for Agent 05 (E-02) and Agent 01 (A-01/A-03)
- **PANIC:**
  - `mbos.panic_set(level, target, engage, actor, reason, prov_ids, idem)`: engage for gateway, approver or policy_admin; release for approver only.
  - Views `mbos.panic_events` and `mbos.panic_current`, both fail-closed.
  - A fresh DB bootstraps FROZEN.
- **Claims:**
  - `mbos.effector_claim(areq, request)` returns `(state, response, replayed)`.
  - `mbos.effector_finish(areq, 'executed'|'failed', provider, msg_id, response)`.
  - The column is `response`, not `result`.
- **Budget:** `mbos.budget_reserve_caps(areq, amount, currency, caps, mode, actor, intent, prov_ids, idem)`.
  - caps = `{per_action, daily, global_daily, velocity_per_hour (null = none), tz, categories[]}`
  - Also: `mbos.budget_exposure_day(categories[], currency, mode, tz)`, `mbos.budget_velocity_hour(...)`.
- **Refused YES:** record it via `append_receipt` as POLICY_DECIDED with `details.refused_approval`.

## Proposed tasks (for Agent 01 to triage into READY_QUEUE)
| Proposed ID | Pri | Task | Deps | Acceptance |
|---|---|---|---|---|
| D-19 | P2 | Retention and pruning of old base backups and archived WAL (keep N bases plus the WAL they need), driven by one setting | D-09b destination | A prune never removes WAL needed by a retained base; a restore from the oldest retained base still passes `verify_chain` |
| D-20 | P1 | Encrypt everything that leaves the machine (dumps, chain exports, WAL, artifacts), with the key kept off the host | D-09b destination | A decrypted off-box restore passes `verify_chain`; the archive on the destination contains no plaintext contact values |
| D-21 | P2 | Outbox relay worker, plus the optional Twenty projection (acceptance D4), only if Michael wants a CRM UI | Michael's CRM decision | The projection rebuilds from the outbox with zero drift |
| D-22 | P2 | Reboot test D2 and the Quadlet cut-over | `loginctl enable-linger`; Podman installed | After a reboot everything is up with no manual steps and `verify_chain` is OK |

### Read-through of 01's spine_d (@ f4c6529): see `docs/receipts/2026-10-07-spine-d-readthrough-2.md`
- **R1, bug (reproduced):** `record_enrichment` loses a block that returns to an earlier value (A, B, A leaves the card showing B), because its idempotency key repeats.
- **R2:** `record_score` and the recommendation patch don't pass the D-14 `entity_type`/`entity_id`.
- R3 to R5 are low or notes: the PANIC connection, the PANIC key, and a RECOMMENDED item after `policy_denied`.

## Answers requested by Agent 01 (ROUND_TWO_INTEGRATION §3 D, READY_QUEUE D-01)
1. **DBOS login role: `mbos_dbos`.** It is created by `state/bootstrap/roles.sql`.
   - **Owns:** the DBOS system database `mbos_dbos`.
   - **Writes state only through the `mbos.*` API, as a member of:**
     - `agent_write`: ingest, items, proposals, outcomes
     - `approver`: `spine.decide` records Michael's decisions from the Operator UI and CLI
     - `gateway`: R4 runs 05's gateway in-process
   - **Cannot:** UPDATE or DELETE any ledger, or write policy (tested).
   - The per-edge role checks still stop LLM-facing processes (`mbos_state_mcp`) from approving or executing.
   - RECOMMENDATION: once 05's gateway runs as its own process, revoke `gateway` from `mbos_dbos`.
2. **Checkpoint schema: YES.** DBOS datasource checkpoints (`dbos.transaction_outputs`) may and should live in schema **`dbos` of the app DB `mbos`**.
   - That puts the checkpoint in the same transaction as the state change and its receipt, so a step is exactly-once together with its receipt.
   - `bootstrap.sh` creates the schema owned by `mbos_dbos`, so the role needs no CREATE on the database.
   - The `mbos` schema stays owned by `mbos_owner`.
   - FACT: covered by a test (`test_dbos_role_can_run_the_spine_and_own_its_checkpoint_schema`) and by a fresh bootstrap.

## Notes for Agent 01's port (A-01 phase 2)
- **Recreate dev DBs.** The chain is MBOS-RH-1 from genesis: `0000_mbos_canonical.sql` was added, and `0001`/`0004` were amended per ADR-0010. A DB created at `7f0649a` or earlier is refused with `MigrationDrift`.
- **governance_flags is replaced by `panic_state`** (R5, 05 semantics). Use these functions:
  - `mbos.panic_read()` and `mbos.panic_blocks(agent, capability, category)`. Both fail closed: no row reads as FROZEN.
  - `mbos.panic_init(...)`, which defaults to FROZEN.
  - `mbos.panic_mutate(level, target, engage, ...)`. Release is policy_admin only.

  A9's corruption cases must use `SET LOCAL session_replication_role = replica`, because direct writes need a same-transaction receipt.
- **effector_calls:** use `mbos.record_effector_call(areq, provider, msg_id, request, response)`. It is exactly-once (a replay returns the original response) and is accepted only while the request is `executing`.
- **llm_spend:** `mbos.llm_spend_authorize(agent, est_usd, cap_usd)` then INSERT. A NULL cap is denied.
- **artifacts:** use `mbos.put_artifact(bytes, media_type)`. Columns: `sha256`, `media_type`, `byte_size`, `storage`, `location`, `content`.
- **Payload hashes:** `payload_hash` must be MBOS-CJSON-1 (`MB007` otherwise). If omitted, `propose_action` computes it.

## Completed (round two)
- **D-01 + D-02 @ `a0d1fbe`:**
  - migration `0005`: `effector_calls`, `panic_state`, `llm_spend`, `artifacts`, plus R8
  - ADR-0010 MBOS-RH-1 ledger, with the reference vendored byte-identical
  - 137 tests pass (twice), including all `vectors.json` cases in PostgreSQL
  - a DB-exported chain verifies with `mbos_canonical.verify_chain`
  - receipt: `docs/receipts/2026-10-07-d01-d02-migration-0005-adr0010.md`

### Wave one (earlier)
All items below are FACT, verified by 93 passing tests on PostgreSQL 16.2 on this host.

- **Implementation:** `state/`
  - Migrations `0001`–`0004` cover these tables: `items`, `action_requests`, `approvals`, `receipts`,
    `provenance`, `outcomes`, `outbox`, `policy`, `budget_ledger`, `lessons`.
  - The Python package `mbos_state` provides the migrator, a StateStore facade, and chain
    export/anchor/offline verify plus a CLI.
  - Bootstrap: `roles.sql`, `bootstrap.sh`, `pg-local.sh`, backup and restore-drill scripts, and
    systemd user units.
  - Quadlet units are written but untested.
- **Append-only:** approvals, provenance, receipts, outcomes, lessons, policy and budget_ledger reject
  UPDATE/DELETE/TRUNCATE by trigger (owner and superuser included) and by privilege (all agent roles).
- **IDs and chain fields:**
  - Prefixed ULIDs come from both SQL and Python, in the same format.
  - Receipt `seq` is gapless and monotonic, including under 8 concurrent writers.
  - `prev_hash` and `row_hash` are computed by the trigger; the writer cannot set them.
- **`verify_chain`:**
  - It detects:
    - column edits
    - canonical edits
    - consistent rewrites
    - deleted rows
    - single-byte flips
    - tail truncation (with an external anchor)
  - An offline JSONL verifier also exists.
- **Same-transaction rule:** a state change, its receipt and its outbox row commit in ONE transaction.
  Deferred constraint triggers refuse COMMIT for any state row without a same-transaction receipt.
  Rollback, receipt failure, a killed backend, and a SIGKILLed postmaster all leave both or neither.
- **Least-privilege roles:** agent_read, agent_write, gateway, approver, policy_admin, outbox_relay and
  mbos_owner, plus a role allow-list for each ActionRequest status edge.
- **A10:** stored documents validate against the vendored frozen schemas.
- **Docs:**
  - `docs/research/agent-04-round-two.md`: report, gap-list answers, Twenty mapping, 1-week plan.
  - `docs/state/RUNBOOK-STATE.md`: startup/reboot plan, verification, backups, tamper response, RPO/RTO.
  - `docs/receipts/2026-10-07-round-two-state-spine.md`.

## Findings
- **FACT:** Podman is not installed on the EliteDesk.
  - Wave one runs PostgreSQL 16.2 from the `pgserver` wheel: user-space, port 55432, isolated from
    port 5432 and CAOSCare.
  - `pg-local.sh` switches to PGDG or Quadlet binaries without any schema change.
- **FACT:** host Python is 3.10.12, while ADR-0008 says 3.12+. The code is 3.10-compatible.
  Agent 01's venv appears to use 3.12.
- **FACT:** `Linger=no` for user michaelos, so user units will not start at boot until it is enabled.
- **INFERENCE:** a monthly partition of receipts is unnecessary at solo volume and complicates the
  UNIQUE(seq) chain invariants, so it is deferred.

## Decisions made (lane-internal, reversible)
- Receipts store their exact hashed `canonical` text. `verify_chain` checks that the hash matches it and
  that it is semantically equal to the columns, so verification does not depend on jsonb text format
  staying stable across PG upgrades.
- Every receipt gets its outbox row via an AFTER INSERT trigger, so the outbox can never be forgotten.
- Wave-one dry-run is enforced as a CHECK constraint (`receipts_wave1_dry_run_only`). Going live requires a
  reviewed migration, not a toggle.
- Schema migrations are themselves receipted. The genesis receipt is migration 0001.

## Unknowns
- Off-box backup target for pgBackRest and dumps. This blocks RPO 15 min and the full D1 fresh-host restore.
- Expected volume per day (Agent 02).
- Payload-hash canonicalization standard: `mbos.payload_hash` vs RFC 8785.

## Blockers
None for wave one.

## Needs Michael decision
**Off-box backup target (blocks D-09):** see `docs/state/OWNER_QUESTION_BACKUPS.md`. Recommended: encrypted cloud storage, else another machine you own. The backups contain raw seller contact values, so they must be encrypted off-box.
- RPO/RTO. Proposal: 15 min / 4 h once WAL ships off-box. Today: 0 for a crash, 24 h for host loss.
- Off-box backup location.
- Host operations (or delegate to Agent 01 / ops):
  - `sudo loginctl enable-linger michaelos`
  - install Podman (or PGDG `postgresql-16`) for the target runtime

## Needs coordinator review
These are Agent 04 interpretations and are NOT self-accepted. Details are in
`docs/research/agent-04-round-two.md` §3.
1. New ID prefixes: `lsn_`, `pol_`, `bud_`, `obx_`.
2. Item state edges added:
   - HELD→AWAITING_APPROVAL
   - HELD→REJECTED
   - ACTED→AWAITING_APPROVAL
   - RECOMMENDED→RESEARCHING
3. Receipt vocabulary gaps:
   - no `ITEM_UPDATED`
   - no `ACTION_EXPIRED`
   - `ACTION_EXECUTED` requires `approval_id`, which blocks tier ≥ 1 auto-approved execution later
4. Payload-hash canonicalization.
5. DB-level guards that duplicate 05's execution guard. Agent 05 to confirm.
6. Which login role(s) the DBOS app uses for state writes. One role per process is recommended.
