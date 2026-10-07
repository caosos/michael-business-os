# Receipt — Round-One state architecture research

- Timestamp: 2026-10-07T04:01:49Z
- Agent: 04 (CRM / State)
- Branch: research/agent-04-state
- Related output: `docs/research/agent-04-state.md`, `docs/decisions/ADR-0001-durable-state-architecture.md`

## What was checked

Three parallel research streams via subagents with web search/fetch:
1. Open-source CRM/ERP backbones (Twenty, Directus, Baserow, EspoCRM, ERPNext/Frappe, Odoo CE, NocoDB, Dolibarr, SuiteCRM, Monica, Krayin, Teable, Relaticle).
2. Agent-native CRMs + agent-memory frameworks + NakatomiCRM (Graphiti, Cognee, Letta, Mem0, Supermemory, Headless_CRM, Marten, MCP ecosystem).
3. Durable-state architecture patterns (Postgres features, event sourcing vs CRUD+audit, tamper-evident logs, object storage, vector memory, MCP security, concurrency, backup/recovery).

## Sources observed (primary)

- GitHub repos + release pages (licenses, stars, commit recency) for all candidates above — queried Oct 2026.
- Official docs: postgresql.org (continuous archiving, RLS), modelcontextprotocol.io (security/human-in-the-loop), directus.com (revisions), docs.espocrm.com (audit), docs.frappe.io (versioning/audit).
- License files: twentyhq/twenty LICENSE (AGPL + EE), Directus MSCL 1.0, Baserow FAQ (MIT core), NocoDB license change (~Jan 2026).
- Pattern references: pgBackRest/WAL-G/PITR comparisons, transactional outbox, idempotency keys, hash-chain vs Merkle audit logs, content-addressed storage, pgvector vs Qdrant/Chroma/LanceDB.

## What was observed (key verified facts)

- No surveyed CRM is append-only; all use mutable CRUD + mutable audit tables. `[FACT]`
- ERPNext/Frappe is MariaDB-only (Postgres experimental/unsupported). `[FACT]`
- Directus is under MSCL 1.0 (free only under $5M revenue AND under 50 employees). `[FACT]`
- MinIO Community Edition archived/EOL (~Apr 2026). `[FACT]`
- EventStoreDB/KurrentDB relicensed to non-OSI ESLv2 (v24.10+). `[FACT]`
- Anthropic official SQLite MCP server archived with unpatched SQL-injection. `[FACT]`
- NakatomiCRM: MIT, FastAPI/PG16, `/mcp` ~30 tools, ~9★, 0 releases, solo, not append-only. `[FACT]`
- Graphiti: Apache-2.0, bi-temporal with fact invalidation, first-party MCP. `[FACT]`

## Confidence

High on licenses/DB/MCP-existence and architecture patterns (directly sourced). Medium on star counts / release dates (point-in-time ballparks). Self-hosted MCP parity for Twenty and exact Graphiti edge schema remain UNKNOWN (noted in the research file).

## Uncertainty / to verify in round 2

- Twenty self-hosted native-MCP parity vs Cloud.
- Whether Cognee/MemOS offer true append-only/bi-temporal invalidation.
- Vendor memory benchmarks (self-reported, unverified).
- Operator-dependent values: volume, RPO/RTO, approval thresholds, retention/regulatory constraints.
