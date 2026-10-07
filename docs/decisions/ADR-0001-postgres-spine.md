# Decision

ADR-0001 — PostgreSQL as the single system-of-record "spine"

Status: ACCEPTED (2026-10-06, Agent 01, after cross-agent reconciliation — see "Ratification" below)

## Context
The core law is "no action without a receipt, no receipt without provenance." We need a datastore for a single self-hosted 24/7 server that holds relational state, flexible receipt payloads, vector memory, a job/queue substrate, and an append-only provenance/event log — operable by one person.

## Options considered
- **PostgreSQL** as one spine (+ pgvector, pg_cron, JSONB, LISTEN/NOTIFY, logical replication).
- Polyglot: separate relational DB + vector DB (Qdrant) + broker (Kafka/NATS) + event store (KurrentDB).
- SQLite/libSQL (single-writer) or DuckDB (OLAP) as primary.

## Recommendation
Adopt **PostgreSQL as the single system-of-record spine.** Receipts as JSONB; provenance/receipts/approvals as append-only tables (UPDATE/DELETE revoked); vector memory via pgvector; scheduling via the durable engine (fallback pg_cron); LISTEN/NOTIFY only as a wake hint. Add Qdrant/NATS/Debezium later only if scale demands. Any CRM is a projection, not a second source of truth.

## Evidence
- FACT: PostgreSQL License (OSI, BSD-like). pgvector (HNSW/IVFFlat), pgmq (SQS-like), pg_cron, JSONB, LISTEN/NOTIFY, logical replication are mature.
- INFERENCE: One transaction boundary lets the receipt and the state change commit atomically — the mechanical enforcement of the core law. One DB = one backup, one credential set, one thing to operate.
- FACT: KurrentDB relicensed to non-OSI Kurrent License v1; Kafka/Redpanda are heavy for one box. SQLite is single-writer (bad for concurrent agents); DuckDB is OLAP, not OLTP.
- Full detail: `docs/research/agent-01-coordinator.md` §1, §6.

## Risks
- Single-server SPOF (mitigate: pgBackRest off-box + tested restore).
- Vector or throughput scale could outgrow PG (mitigate: documented escape hatch to Qdrant/NATS).

## Reversibility
Moderate. Vector and queue concerns can be split out later with low churn; splitting the system-of-record itself would be expensive — but keeping everything in PG now preserves optionality.

Coordinator review required: YES (needs input from 03 scoring storage, 04 CRM/state).

## Ratification (2026-10-06, round-one reconciliation)
- **Agreements:** Agent 04 (ADR-04-0001) independently chose a single Postgres with the write, its receipt and the outbox committed in one transaction. Agents 05, 06 and 07 assume an owned data plane and raise no conflict.
- **Conflict C1, Agent 02 proposed SQLite (§11):** rejected at the hard gate. SQLite allows one writer at a time, and the design has 6+ agent processes plus the DBOS executor writing concurrently. INFERENCE: it would fail the same-transaction receipt invariant under concurrent writes. 02's schema is ported to Postgres as the `normalized` block of Item v1 (ADR-0004).
- **Additions from 04:** content-addressed artifact store (`sha256` refs, local FS → Garage/SeaweedFS, not MinIO CE); pgvector treated as a *rebuildable index*, not truth; pgBackRest + nightly `pg_dump`, 3-2-1 with restore drills.
- Full scoring: `docs/research/agent-01-integration.md` §3.
