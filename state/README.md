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
  migrations/0000_mbos_canonical.sql  ADR-0010 reference (MBOS-CJSON-1 / MBOS-RH-1), byte-identical vendored copy
  migrations/0001_foundation.sql   ULIDs, provenance, receipts (MBOS-RH-1 hash chain), outbox, verify_chain
  migrations/0002_domain.sql       items, action_requests, approvals, outcomes, lessons, policy, budget_ledger
                                   + state machines + same-transaction receipt invariant
  migrations/0003_api.sql          mbos.* write functions (state + receipt + outbox in one call)
  migrations/0004_views_grants.sql contract-document views, reporting views, least-privilege grants
  migrations/0005_r1_integration.sql  R1 tables (effector_calls, panic_state, llm_spend, artifacts), R3/ADR-0010
                                   payload-hash check, R5 PANIC (05 semantics, fail-closed), R8 blocking dedup_key
  migrations/0006_r12_strict_item_edges.sql  R12: strict ADR-0004 item edges (== Agent 01 ITEM_TRANSITIONS)
  migrations/0007_lane_e_requirements.sql   D-04 / Lane E: panic_set + panic_events/panic_current (bootstrap
                                   FROZEN, release = approver, L3 cancels approved), effector_calls as execution
                                   claim, gateway edges, budget modes + bucket multi-cap reserve
  migrations/0008_mcp_calls.sql    D-06: append-only audit of every State MCP call; ok write rows must cite receipts
  mbos_state/mcp_tools.py          D-06: State MCP tool layer (identity/scope -> provenance, narrow intent tools)
  mbos_state/mcp_server.py         D-06: MCP server (mcp 2.x MCPServer, stdio): python -m mbos_state.mcp_server
  migrations/0009_artifact_fs.sql  D-07: fs artifacts indexed in mbos.artifacts; location forced to its canonical path
  mbos_state/artifacts.py          D-07: ArtifactStore (sha256/ab/cd/<hex>, atomic, read-only, re-hash on read)
  migrations/0010_vector_index.sql D-08: item_embeddings (pgvector in schema mbos_ext) + HNSW; rebuildable, never truth
  mbos_state/vector_index.py       D-08: refresh / rebuild / verify / search; HashEmbedder (deterministic, offline)
  migrations/0011_comms_ledger.sql D-10: 06's mbos_comms consent/DNC ledger under lane D (same names; same-tx receipts,
                                   fail-safe grant/revoke asymmetry, raw contact values readable by gateway only)
  migrations/0012_deferred_approval_provenance.sql  D-13: provenance->approval FK checked at COMMIT (MODIFY ordering)
  migrations/0013_velocity_actions.sql  D-11: optional caps.velocity_actions_per_hour (unreleased bucket reservations/h)
  mbos_state/mbos_canonical.py     ADR-0010 Python reference (byte-identical vendored copy)
  tests/canonical/vectors.json     ADR-0010 golden vectors (byte-identical vendored copy)
  bootstrap/roles.sql              group + login roles (cluster level)
  bootstrap/pg-local.sh            wave-one user-space PG16 cluster (port 55432, loopback only)
  bootstrap/bootstrap.sh           idempotent: roles, DBs, passwords, migrations, verify_chain
  bootstrap/systemd/               user units: postgres, hourly chain verify + anchor
  bootstrap/podman/                Quadlet units for the target runtime (UNTESTED: no Podman on host yet)
  mbos_state/                      Python: migrate, StateStore facade, chain export/anchor/offline verify, CLI
  tests/                           187 tests; vendored frozen contracts v1.0.0 in tests/contracts-v1.0.0/
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
| `effector_calls` | append-only | A5 idempotency anchor; `dry_run` CHECK; only while the request is `executing` (after its ACTION_EXECUTING receipt); gateway only |
| `panic_state` | append-only, receipted | 05 PANIC body per revision, sealed with `cjson_sha256`; `panic_read()`/`panic_blocks()` fail closed; release = policy_admin only |
| `llm_spend` | append-only | per-agent daily metering; `llm_spend_authorize()` serializes the cap check; no cap = deny |
| `artifacts` | append-only | sha256 content-addressed (`put_artifact`); inline now, `storage`/`location` for FS/Garage later |

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

Hashing follows ADR-0010: `row_hash = sha256(mbos.cjson(D))` (MBOS-RH-1), and `mbos.payload_hash = mbos.cjson_sha256`. `jsonb::text` is never hashed.

SQLSTATEs: `MB001` immutable · `MB002` provenance · `MB003` missing receipt · `MB004` illegal transition ·
`MB005` approval invalid · `MB006` budget · `MB007` payload hash not MBOS-CJSON-1 · `MB404` not found · `MB409` conflict / stale version.

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

## State MCP server (D-06, ADR-0003): the only agent write path

Agent processes get **no database write credential**; at most they get `mbos_reader`. They write only through
this server, which holds the `mbos_state_mcp` login (`agent_write`). One server process runs per agent
identity:

```json
{"mcpServers": {"mbos-state": {
  "command": "/home/michaelos/mbos/state/.venv/bin/python", "args": ["-m", "mbos_state.mcp_server"],
  "env": {"PYTHONPATH": "/home/michaelos/mbos/state", "PGPASSFILE": "/home/michaelos/.config/mbos/pgpass",
          "MBOS_DSN": "host=127.0.0.1 port=55432 dbname=mbos user=mbos_state_mcp",
          "MBOS_MCP_AGENT_ID": "agent-02-opportunity",
          "MBOS_MCP_SCOPE": "get_item,list_items,create_item,transition_item,patch_item"}}}}
```

**Tools by profile:**
- `agent` profile:
  - reads: `get_item`, `list_items`
  - writes: `create_item`, `transition_item`, `patch_item`, `propose_action`, `record_outcome`, `record_lesson`
- `operator` profile: adds `record_approval`. It is set with `MBOS_MCP_PROFILE=operator` and the `mbos_operator_ui` login, for the non-LLM Operator UI backend only. Never give it to an agent.

There is no SQL tool.

**Rules:**
- Caller identity and scope come from the server's environment. Each call writes a provenance row: `agent_name` = caller, `tool_name` = `mbos-state-mcp/<tool>`, and `inputs_used` holds the MBOS-CJSON-1 argument hash plus caller, profile and scope.
- Receipt `actor` and `proposed_by` are forced to the caller.
- Write tools accept `evidence` (inline source or model provenance; the identity is forced, and human or approval provenance is refused) and `evidence_provenance_ids`.
- Every call is logged in `mbos.mcp_calls`: reads, refusals and errors included.
- A successful write call commits its state change, its receipt(s) and its `mcp_calls` row in one transaction. The DB refuses an `ok` write row that doesn't cite existing receipts.
