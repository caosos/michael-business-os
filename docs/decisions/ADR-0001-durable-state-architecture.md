# Decision

ADR-0001 — Durable state architecture for Michael Business OS

Status:
PROPOSED

(Not self-accepted. This is a whole-system decision requiring Agent 01 cross-agent review per the coordination addendum.)

Date: 2026-10-07
Author: Agent 04 (CRM / State)

## Context

The business OS needs a system of record that survives restarts, model changes, crashes, and agent replacement, and that enforces the core Law: **no action without a receipt; no receipt without provenance.** The LLM agent is stateless and replaceable; durable state — not the model — must be the source of truth. We must choose the storage substrate, the history/audit model, the agent interface, artifact storage, and the recall layer.

## Options considered

1. **Adopt a CRM/ERP product as the system of record** (Twenty, EspoCRM, ERPNext, Odoo, NakatomiCRM).
   - All are mutable CRUD + a mutable "audit table." None is append-only. `[FACT]` Cannot mechanically satisfy the Law.
   - ERPNext is MariaDB-only; Directus is Postgres+native-MCP+best-audit but under a restrictive MSCL license gate. `[FACT]`
2. **Full event sourcing** (Marten on Postgres, or EventStoreDB/KurrentDB).
   - Perfect audit/replay but adds paradigm + infra complexity; EventStoreDB relicensed to non-OSI source-available. `[FACT]` Overkill for a solo operator. `[INFER]`
3. **CRUD current-state tables + append-only, hash-chained receipt ledger on one Postgres** (RECOMMENDED).
   - Normal queryable state + immutable "who/why/what" ledger for the parts that matter, without rebuilding the business from events. `[INFER]`
4. **Agent-memory framework as the store** (Letta, Mem0, Graphiti, Cognee).
   - Designed for recall, mostly mutable/self-editing (anti-append-only); Graphiti is bi-temporal but is a recall layer, not a ledger of record. `[FACT]`

## Recommendation

Adopt **Option 3**: one **PostgreSQL** as single source of truth, with **CRUD current-state tables + an append-only, hash-chained receipt ledger** (`prev_hash`→`row_hash`), INSERT-only for the agent role. Agent reaches state **only through a custom MCP server** with narrow intent-tools, strict input schemas, idempotency keys, server-side write guards, and human-approval gates. Artifacts in **content-addressed (SHA-256) object storage**. **pgvector** in the same Postgres as a *rebuildable* semantic index (FK + content-hash to canonical rows), never a source of truth. Backups via **pgBackRest WAL/PITR + nightly pg_dump + replicated object store** (3-2-1, scheduled restore drills). A CRM (Twenty / EspoCRM), if wanted, is an optional **read/UI surface projected from the ledger via the outbox** — never upstream of it.

## Evidence

- Full analysis + DDL for receipt and provenance schemas: `docs/research/agent-04-state.md`.
- Candidate licenses/activity verified via GitHub + official docs (Oct 2026). Key repos: twentyhq/twenty (AGPL-3.0), directus/directus (MSCL 1.0), baserow/baserow (MIT core), espocrm/espocrm (AGPL-3.0), frappe/erpnext (GPLv3, MariaDB-only), getzep/graphiti (Apache-2.0), mrdulasolutions/NakatomiCRM (MIT).
- Patterns: tamper-evident hash-chained audit logs; transactional outbox; idempotency keys; pgBackRest PITR; content-addressed storage; MCP security (human-in-the-loop, least privilege). Sourced in the research file.
- Avoid: MinIO CE (EOL), EventStoreDB/KurrentDB (source-available relicense), Anthropic SQLite MCP server (archived, unpatched SQLi). `[FACT]`

## Risks

- A custom MCP server + ledger is build effort vs. adopting a product off the shelf. Mitigated: the ledger is small/standard; a CRM can still be layered on later as a projection.
- Hash-chain gives forward integrity but not third-party-verifiable proofs without optional Merkle/anchoring (deferred until required). `[FACT]`
- pgvector adequacy assumed for solo scale (<5M vectors); revisit if volume explodes. `[FACT]`
- Cross-agent coupling: approval gates (Agent 05), comms/outbox (Agent 06), scoring data (Agent 03) must align to this schema.

## Reversibility

High at the data layer: the ledger + Postgres is a stable substrate; a CRM/UI can be added or swapped as a downstream projection without moving the source of truth. Vectors are rebuildable, so model/embedding changes are non-destructive. Choosing a CRM as source-of-truth (Option 1) would be far harder to reverse — another reason to keep state in our own Postgres.

Coordinator review required:
YES
