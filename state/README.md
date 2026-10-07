# MBOS state spine (Agent 04, lane D)

PostgreSQL is the source of truth (ADR-0001). This directory holds the DDL, the receipted write API,
chain verification, bootstrap scripts for the EliteDesk, and the tests.

**Core law, enforced by the database rather than by convention:**
- *No action without a receipt.* Deferred constraint triggers on `items`, `action_requests`, `approvals`,
  `outcomes`, `lessons`, `policy` and `budget_ledger` refuse to COMMIT unless the same transaction
  (`receipts.tx_id = pg_current_xact_id()`) wrote the matching receipt.
- *No receipt without provenance.* `receipts.provenance_ids` needs at least one id, every id must exist,
  and every provenance row must resolve to a source, a model, a human approval, or a tool (contract anyOf).

```
state/
  migrations/0001_foundation.sql   ULIDs, provenance, receipts (hash chain), outbox, verify_chain
  migrations/0002_domain.sql       items, action_requests, approvals, outcomes, lessons, policy, budget_ledger
                                   + state machines + same-transaction receipt invariant
  migrations/0003_api.sql          mbos.* write functions (state + receipt + outbox in one call)
  migrations/0004_views_grants.sql contract-document views, reporting views, least-privilege grants
  bootstrap/roles.sql              group + login roles (cluster level)
  bootstrap/pg-local.sh            wave-one user-space PG16 cluster (port 55432, loopback only)
  bootstrap/bootstrap.sh           idempotent: roles, DBs, passwords, migrations, verify_chain
  bootstrap/systemd/               user units: postgres, hourly chain verify + anchor
  bootstrap/podman/                Quadlet units for the target runtime (UNTESTED: no Podman on host yet)
  mbos_state/                      Python: migrate, StateStore facade, chain export/anchor/offline verify, CLI
  tests/                           93 tests; vendored frozen contracts v1.0.0 in tests/contracts-v1.0.0/
```

## Tables

| Table | Kind | Notes |
|---|---|---|
| `provenance` | append-only | contract anyOf as a CHECK |
| `receipts` | append-only, hash-chained | gapless `seq`, `prev_hash`, `row_hash = sha256(canonical)`; trigger computes the chain; writes the outbox row |
| `outbox` | queue | one row per receipt, same transaction; only delivery columns may change; pruned only after dispatch |
| `items` | current state | state machine in `item_state_transitions`; never deleted (ARCHIVED); `version` = optimistic lock |
| `action_requests` | current state | payload frozen at insert; status machine + allowed role per edge in `action_request_transitions` |
| `approvals` | append-only | YES/NO/MODIFY/HOLD rules; `payload_hash_seen` must equal the frozen payload hash |
| `outcomes`, `lessons` | append-only | LEARN inputs |
| `policy` | append-only, versioned | `policy_current` view; no row = deny; money/purchase/commitment can never be `allow` |
| `budget_ledger` | append-only | reserve → commit/release; cap checked under an advisory lock; no cap = deny |

There are deliberately **no workflow-resume tables**: DBOS owns workflow durability (ADR-0002) in its own
database (`mbos_dbos`).

## Write API (SQL; `mbos_state.store.StateStore` wraps it)

`create_item`, `transition_item`, `update_item_doc`, `propose_action`, `set_action_status`,
`record_approval`, `record_outcome`, `record_lesson`, `publish_policy`, `budget_reserve`, `budget_settle`,
`record_provenance`, `append_receipt`, `verify_chain`, `chain_head`, `outbox_claim`, `outbox_mark`.

Each function writes the state change and its receipt in the caller's transaction, and the receipt
trigger adds the outbox row, so one call is atomic by itself and several calls compose inside one
transaction. They work the same from psycopg, SQLAlchemy or a DBOS `@DBOS.transaction`
(`SELECT mbos.transition_item(...)`). Every function takes an idempotency key, and replaying it returns the
original result.

SQLSTATEs: `MB001` immutable · `MB002` provenance · `MB003` missing receipt · `MB004` illegal transition ·
`MB005` approval invalid · `MB006` budget · `MB404` not found · `MB409` conflict / stale version.

## Roles

| Group role | Login | May |
|---|---|---|
| `agent_read` | `mbos_reader` | SELECT |
| `agent_write` | `mbos_state_mcp` | items, proposals (`drafted`), outcomes, lessons, provenance, receipts |
| `gateway` | `mbos_gateway` | classify / execute / fail / freeze action requests, item state, budget |
| `approver` | `mbos_operator_ui` | approvals (Michael's decisions), MODIFY successors, item state |
| `policy_admin` | `mbos_policy` | policy versions |
| `outbox_relay` | `mbos_relay` | outbox delivery columns only |
| `mbos_owner` | `mbos_migrator` (SET ROLE) | owns objects. The append-only triggers still stop it |

Nobody is granted UPDATE, DELETE or TRUNCATE on a ledger table.

## Run

```bash
python3 -m venv state/.venv && state/.venv/bin/pip install "psycopg[binary]>=3.1" pytest jsonschema pgserver
cd state && .venv/bin/python -m pytest          # spins up a throwaway cluster; nothing persistent
./bootstrap/pg-local.sh init && ./bootstrap/pg-local.sh start && ./bootstrap/bootstrap.sh
```

The operations side (startup, reboot, verification, backups) is in `docs/state/RUNBOOK-STATE.md`.
