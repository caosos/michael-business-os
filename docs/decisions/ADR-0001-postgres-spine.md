# Decision

ADR-0001 — PostgreSQL as the single system-of-record "spine"

Status: PROPOSED

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
