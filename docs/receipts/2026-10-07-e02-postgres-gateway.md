# Receipt: E-02, the gateway and PANIC on lane D's Postgres (Agent 05)

- **Date:** 2026-10-07
- **Task:** E-02 (P0, critical path). It was claimed on `0d107df`, blocked on D-04 (my requirements were not in 0005), and resumed on Agent 04's 0007.
- **External effects:** none. Dry-run only.

## Inputs (provenance)
- Lane D schema `origin/research/agent-04-state @ 14bd690` (migrations 0000–0007, roles.sql, migrator).
  - It is vendored **test-only** and byte-identical into `tests/vendor/agent04_state/`.
  - sha256 values are pinned in `MANIFEST.sha256` and checked by `test_vendored_lane_d_schema_is_pinned`.
- Rulings R1, R2, R4 and R5 (`ROUND_TWO_INTEGRATION.md`), ADR-0010, and my `docs/integration/05-requirements-for-04-migration-0005.md`. Agent 04 implemented the last as 0007.

## History (FACT)
- `a0d1fbe` (0005) did not contain lane E's requirements: the status edges, the claim lifecycle and the multi-cap budget. The queue's "D-04 DONE" was premature.
- I reported it, Agent 04 re-opened D-04, and I built **no workarounds** on 0005 (agreed with 04).
- Two refinements I asked for landed in 0007:
  - bucket aggregation (`caps.categories`)
  - `velocity_per_hour: null`

## Built
- **`store_pg.py`.**
  - `PgGovernanceStore` has one connection per role per thread (`agent_write` / `gateway` / `approver` / `policy_admin`). It calls only `mbos.*`: `propose_action`, `set_action_status`, `record_approval`, `append_receipt`, `record_provenance`, `effector_claim`/`effector_finish`, `budget_reserve_caps`/`budget_settle`/`budget_lock`, `panic_set`, and `verify_chain`.
  - `PgPanicStore` reads `mbos.panic_read()`. Any failure means FROZEN.
- **Gateway rewritten on the store.** The 8 guard checks are unchanged in meaning.
  - propose: drafted → classified → pending_approval or rejected.
  - An invalid YES is refused before lane D and recorded as `POLICY_DECIDED.details.refused_approval`. Lane D's own trigger would also refuse it.
  - execute: `approved→executing` plus `effector_claim` in one transaction with the row locked. A late PANIC read follows. Then `effector_finish` with the receipts, and the budget is committed or released.
  - The new lane D edges are used: `approved→expired`, `approved→failed`, `executing→cancelled_by_freeze`.
  - Lane D refusals (`MB*`) are turned into `GatewayRefused`.
- **PANIC.**
  - Engage goes through `mbos.panic_set` (role gateway), which on L3 cancels approved requests in the same transaction. The gateway also releases their budget reservations.
  - Release requires a policy approver, a readable policy, and **the `approver` role in the DB**.
  - Hooks (E-03) run after commit and are receipted.
- **SQLite and the JSON PANIC file are removed from the code** (`store.py` deleted, file `PanicStore` deleted). `mbos-gov` connects with `--dsn`, `MBOS_GOV_DSN` or `MBOS_GOV_DSN_<ROLE>`.

## Verification (FACT)
- **pytest: 211 passed on PostgreSQL 16.2** (pgserver 0.1.4, psycopg 3.3.6, Python 3.12). Each test runs on a fresh database cloned from a template migrated with lane D's migrator. Every role uses its own login.
  - The concurrency, crash, freeze-race and double-delivery tests were run 3 extra times and passed each time.
- **Acceptance:**
  - (1) **05's suite passes on Postgres via 04's API: yes.**
  - (2) **No SQLite on the production path:** `test_no_sqlite_on_the_production_path` checks this. Its scope is the `mbos_governance` package's own storage; DBOS's own system database in the E-03 test is DBOS's business.
  - (3) **R4:** only the gateway login moves action statuses (`test_agents_cannot_move_action_status`), and the execution receipts are the gateway's.
- **Notable results on the real schema:**
  - 100 approvals from 20 concurrent workers against a $1,500 bucket execute exactly 37 at $40 each. Total spend never exceeds $1,500.
  - Agents cannot engage or release PANIC, and the gateway login cannot release it. Postgres raises `InsufficientPrivilege` in both cases.
  - An empty, wrong-schema or tampered `panic_state`, or an unreachable DB, means G7 refuses everything.
  - Lane D's chain verifies with **05's** MBOS-RH-1 reference code (`test_lane_d_chain_verifies_with_05_reference_code`).
  - `PanicState.blocks` (Python) agrees with `mbos.panic_blocks` (SQL) on every case tested.
  - A payload tamper (trigger bypass) is refused by G3 and moves `approved→failed`. A receipt tamper fails `mbos.verify_chain`.
  - A7: the lane D audit view `v_a7_live_effects` is empty after every flow.
- `check_no_bypass`: PASS.

## Behaviour changes worth knowing (vs SQLite wave one)
- **Payload-hash mismatch at proposal** becomes `GatewayRefused`. It is never stored (lane D's MB007).
- **An invalid YES is not stored as an approval.** Before, it was stored and could not execute.
- **MODIFY** needs the successor request (`derived_from`) proposed **before** the MODIFY is recorded (lane D's check).
- **Effector invariant violation.** Lane D CHECKs `dry_run=true` on every stored response (A7). What the effector reported is kept verbatim in `details.effector_reported`, and L3 still trips.
- **A secret-refused proposal** produces an INJECTION_SUSPECTED receipt that has no `action_request_id`, because of the FK and because the request was never stored. The id is recorded in `details.proposed_action_request_id`.

## Open
- **Velocity semantics:** lane D's `velocity_per_hour` caps dollars per hour. Lane E's policy caps money **actions** per hour, checked by the gateway under `budget_lock`. I proposed a count-based velocity for a later 04 migration.
- **The policy is still the file `policy/policy.v1.json`.** Moving it to lane D's `mbos.policy` / `policy_current` is a candidate follow-up.
