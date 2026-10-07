# Agent 04 Round Two: State spine implementation report

**Date:** 2026-10-07
**Branch:** `research/agent-04-state`
**Inputs:**
- coordinator integration plan `agent-01-integration.md`
- ADR-0001, ADR-0002, ADR-0004
- frozen contracts v1.0.0 (`origin/research/agent-01-coordinator` @ `acb6f3b`)

Tags: **FACT** · **INFERENCE** · **RECOMMENDATION** · **UNKNOWN**.

## 1. What was built (all FACT, verified by the test suite on this host)

| Requirement | Implementation | Test |
|---|---|---|
| Tables: items, action_requests, approvals, receipts, provenance, outcomes, outbox, policy, budget_ledger, lessons | `state/migrations/0001`–`0004` | all files |
| Append-only approvals / provenance / receipts (plus outcomes, lessons, policy, budget_ledger) | `BEFORE UPDATE OR DELETE` and `BEFORE TRUNCATE` triggers (these fire even for the owner and superuser), and no UPDATE/DELETE grants to any role | `test_immutability.py`: 7 tables × {owner, superuser} × {UPDATE, DELETE, TRUNCATE} → `MB001`, and 7 × 5 agent roles → `42501` |
| Prefixed ULID public IDs | `mbos.new_id()` in SQL and `mbos_state.ids` in Python, same format; CHECK on every id column | `test_ids_python_and_sql_agree` |
| Monotonic receipt seq | `seq = head + 1` under a transaction advisory lock; `UNIQUE(seq)`, `UNIQUE(prev_hash)` | 8 concurrent writers × 15 transitions: gapless, `count = max(seq)` |
| prev_hash / row_hash | the trigger computes both, and the writer cannot choose them; `row_hash = sha256(canonical)`, and `canonical` (stored) includes `prev_hash` | `test_writer_cannot_choose_chain_fields` |
| verify_chain | `mbos.verify_chain(from_seq, anchor_seq, anchor_hash)` checks 5 things: seq gaps, linkage, hash, column-vs-canonical, anchor. There is also an offline verifier over a JSONL export | 9 chain tests |
| Tamper detection | detects a column edit, a canonical edit, a consistent single-row rewrite, a deleted row, a single-byte flip, and tail truncation (with an anchor). The offline export detects edits and truncation | `test_tamper_detected[*]`, `test_single_byte_flip_detected`, `test_tail_truncation_needs_anchor`, `test_offline_export_verify_and_tamper` |
| State change + receipt + outbox in ONE transaction | API functions write state and receipt, the receipt trigger writes the outbox row, and **deferred constraint triggers refuse COMMIT** for any state row that has no same-transaction receipt (`tx_id = pg_current_xact_id()`) | `test_atomicity.py` (11 tests) |
| Transactional failure → both or neither | rollback after the transition; receipt failure; direct UPDATE without a receipt; a receipt for another item; a receipt from an earlier transaction; backend killed mid-transaction | same; plus a SIGKILL crash drill (RUNBOOK §3) |
| Least-privilege roles | 6 group roles plus `mbos_owner`; login roles 1:1; column-level UPDATE grants; **per-edge role allow-list** on ActionRequest status | `test_role_boundaries`: agents cannot classify, approve or publish policy; the gateway cannot approve; the approver cannot execute; the relay cannot read receipts |
| Postgres is the source of truth | no other store; `items.doc` reference arrays are derived from the ledger in a view, never stored; the CRM (if any) is fed from the outbox | — |
| Migration and bootstrap for the EliteDesk | `migrate.py` (checksummed, receipted, advisory-locked), `roles.sql`, `bootstrap.sh` (idempotent), `pg-local.sh`, systemd user units, Quadlet units, backup and restore-drill scripts | `test_every_migration_is_receipted`, `test_migrate_is_idempotent_and_detects_drift`; bootstrap was run twice on a scratch cluster |
| No competing workflow state machine | there are no resume or step-position tables. The Item and ActionRequest machines are **business** state from ADR-0004; DBOS gets its own database `mbos_dbos` | — |

**Test result (FACT):** `state/.venv/bin/python -m pytest`, with **93 passed** against PostgreSQL 16.2 on
`caoscare1-hp-elitedesk`.

**Acceptance coverage:**

| Test | Status | Covered by |
|---|---|---|
| A1 | covered | atomicity |
| A2 | covered | immutability |
| A3 | covered | chain |
| A4 | covered | provenance resolution: CHECK, plus receipt ids must exist |
| A6 | partial: storage semantics | YES/NO/MODIFY/HOLD rules |
| A7 | covered | CHECK constraint plus the `v_a7_live_effects` audit view |
| A10 | covered | stored receipt, provenance, action-request, approval and outcome documents, and the item envelope, validate against the vendored frozen schemas |
| D1 | partial: same-host restore | |
| D2 | documented with crash-drill evidence | linger is not yet enabled |

## 2. Round-two gap list (integration plan §10, row 04)

1. **Receipt v1 field names, prefixed ULIDs and `seq`.** Adopted verbatim. Receipt columns match the
   contract one-to-one. The internal-only columns are `canonical` and `tx_id`, and neither is hashed or
   exported.
2. **DDL for approvals, outcomes, lessons, action_requests, policy and budget_ledger.** Done (0002).
   Contract `allOf` rules are CHECK constraints, including:
   - irreversible / money / untrusted ⇒ tier 0
   - MODIFY needs a successor
   - HOLD needs `hold`
   - NO needs a reason
3. **Twenty projection mapping** (RECOMMENDATION; not built in wave one, per ADR-0006 "optional"):

   | Twenty object | Source | Direction | Key |
   |---|---|---|---|
   | Opportunity | `items` (+ `v_item_documents`) | PG → Twenty only | `item_id` in a custom field |
   | Stage | `items.state` mapped to Twenty pipeline stages | one-way | — |
   | Note / Timeline | `outbox` topic `receipt.*` (intent, ts, actor) | one-way | `receipt_id` |
   | Person / Company | parties (lane 06 consent ledger, not yet built) | one-way | `party_id` |

   **Rebuild procedure:**
   1. Truncate the Twenty workspace.
   2. Replay `v_item_documents` plus all receipts in `seq` order. The projector is idempotent on `receipt_id`.
   3. Compare counts and stages with `v_pipeline_by_lane`. Zero drift is D4.

   Edits made in Twenty are ignored or overwritten. Twenty is never read back.
4. **Reporting views.**
   - `v_pipeline_by_lane`
   - `v_pnl_by_item`
   - `v_approval_latency`
   - `v_hold_backlog`
   - `v_budget_reservations`
   - `policy_current`
   - `v_a7_live_effects`
5. **RPO/RTO proposal.** RPO 15 min, RTO 4 h once pgBackRest is shipping WAL off-box. Today: 0 for a crash,
   24 h for host loss (RUNBOOK §7). This is Michael's decision.
6. **1-week plan:** see §4.
7. **Custom "resume position" tables removed.** None exist. DBOS owns durability.

## 3. Items for coordinator review (Agent 01 / 05) — Agent 04 interpretations, not self-accepted

1. **ID prefixes not in ADR-0004:**
   - `lsn_` (lessons)
   - `pol_` (policy)
   - `bud_` (budget entries)
   - `obx_` (outbox)

   Please register them or rename them.
2. **Item edges added** (`item_state_transitions`, data rather than code, so they can be changed by migration):
   - `HELD→AWAITING_APPROVAL` (wake)
   - `HELD→REJECTED`
   - `ACTED→AWAITING_APPROVAL` (follow-up action on the same item: buy, then list)
   - `RECOMMENDED→RESEARCHING` (MAYBE)
3. **Receipt vocabulary gaps:**
   - There is no `ITEM_UPDATED` event. Non-state document edits (normalize, research, sources) use
     `ITEM_STATE_CHANGED` with an unchanged state, or `SCORE_RECORDED` / `RECOMMENDATION_RECORDED`.
     Proposal: add `ITEM_UPDATED` in v1.1.
   - There is no `ACTION_EXPIRED`. Expiry is receipted as `POLICY_DECIDED` (status `expired`).
     Proposal: add it.
   - `ACTION_EXECUTED` requires `approval_id`, so a tier ≥ 1 `auto_approved` execution cannot be receipted
     as specified. That does not matter in wave one (everything is tier 0) but must be fixed before
     delegation (MICHAEL_DECISIONS #5).
4. **Contract `item.sources[].provenance_id` is required, and `create_item` does not enforce it.** The
   envelope check passes because 02 supplies it. A10 validation of full items (with 03 economics) belongs
   to lane G.
5. **Payload hash canonicalization is unspecified in the contract.** RECOMMENDATION: either everyone uses
   `mbos.payload_hash(jsonb)`, which is sha256 of Postgres jsonb text, or the contract adopts RFC 8785.
   `propose_action` computes the hash when it is omitted. It does not overwrite a supplied hash.
6. **DB-level guards (defense in depth behind 05's gateway):**
   - `approved` and `executing` require a current, unexpired YES on the exact `payload_hash`
   - money or irreversible YES requires `step_up`
   - a `standing_rule` requires `step_up`
   - policy can never `allow` money, purchase or external commitment
   - a budget with no cap means deny

   05 should confirm these match the guard.
7. **Receipt partitioning (monthly) is deferred.** INFERENCE: it is unnecessary at solo volume, and a
   partitioned parent complicates the `UNIQUE(seq)` / `UNIQUE(prev_hash)` invariants. Revisit when 02
   supplies volume per day.

## 4. Next week (lane D)

| Day | Work |
|---|---|
| 1 | Agent 01 wires DBOS `@transaction` steps to the `mbos.*` functions. 04 pairs on it and adds a DBOS-path A1 test |
| 2 | State MCP server (narrow intent tools over `StateStore`, `mbos_state_mcp` login): the only agent write path |
| 3 | Artifact store (sha256 content-addressed, local FS) plus an `artifacts` table referenced by `artifact_hashes` |
| 4 | pgBackRest to an off-box repo (needs a target: UNKNOWN), PITR drill, fresh-host restore (D1 full) |
| 5 | pgvector rebuildable index plus D3 (drop/rebuild → identical results) |
| 6 | Twenty projector from the outbox plus D4 (optional, if Michael wants a CRM UI) |
| 7 | Quadlet cut-over once Podman is installed; reboot test D2 with linger enabled |

## 5. Constraints observed

- Nothing was installed system-wide and no host settings were changed (no apt, no linger).
- Postgres ran only as throwaway clusters in scratch and temp directories, on ports 55433 and 55499. All
  are stopped.
- No contact with any external service, CAOSCare, or another agent's branch.
- All effector receipts are `dry_run=true`, and the database rejects anything else.
