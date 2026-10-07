# Agent Status

Agent: 04
Role: Postgres / State / Receipts (lane D, durable business state, receipts, provenance)
Branch: research/agent-04-state
Worktree: /home/michaelos/business-os-worktrees/agent-04-state
State: COMPLETE (round-two wave one); awaiting coordinator review of the flagged interpretations
Current phase: ROUND TWO: implementation, Lane D (Postgres state spine)
Started: 2026-10-06
Last updated: 2026-10-07 (round two, wave one delivered)

## Current objective
Deliver the authoritative Postgres state spine per ADR-0001 and ADR-0004 and the frozen contracts
v1.0.0. **Done for wave one.**
Next step: wire it to Agent 01's DBOS app, then build the State MCP server (see the 1-week plan in
`docs/research/agent-04-round-two.md` §4).

## Completed (round two)
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
