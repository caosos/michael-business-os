# Agent Status

Agent: 04
Role: Postgres / State / Receipts (lane D: durable business state, receipts, provenance; sole ledger owner per ADR-0010)
Branch: research/agent-04-state
Worktree: /home/michaelos/business-os-worktrees/agent-04-state
State: WORKING
Claimed: D-03
Done: D-01 @ a0d1fbe
Done: D-02 @ a0d1fbe
Current phase: ROUND TWO: foreman loop (READY_QUEUE)
Started: 2026-10-06
Last updated: 2026-10-07 (D-01 + D-02 done; D-03 claimed)

## Current objective
**D-03:** reporting views over the ADR-0010 chain, plus restore drill D1 followed by `verify_chain`.

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
