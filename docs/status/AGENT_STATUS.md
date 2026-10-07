# Agent Status

Agent: 04
Role: CRM / State (durable business-state, memory, receipts, provenance)
Branch: research/agent-04-state
Worktree: /home/michaelos/business-os-worktrees/agent-04-state
State: WORKING
Current phase: ROUND TWO — implementation, Lane D (Postgres state spine / receipts)
Started: 2026-10-06
Last updated: 2026-10-07 (round two start)

## Current objective
ROUND TWO (implementation). Build the authoritative Postgres state spine per ADR-0001/ADR-0004 and frozen contracts v1.0.0: DDL for items, action_requests, approvals, receipts, provenance, outcomes, outbox, policy, budget_ledger, lessons; append-only + hash-chained ledger; verify_chain; state+receipt+outbox in one transaction; least-privilege roles; EliteDesk bootstrap; tests. Round-one material below is retained for history.

## Completed
- Fanned out 3 parallel research streams: (1) open-source CRM/ERP backbones, (2) agent-native CRMs + agent-memory frameworks + NakatomiCRM, (3) durable-state architecture patterns.
- Synthesized into the full Round-One design: `docs/research/agent-04-state.md`.
- Covered every required RETURN item: candidate systems (URLs/licenses/activity), recommended architecture, 23 canonical entities + relationships, receipt schema (DDL), provenance schema (DDL), agent read/write model, concurrency controls, version/history model, backup/recovery, search strategy, vector-memory role, data that must never live only in model memory, 24-hour MVP, migration path.
- Filed ADR-0001 (PROPOSED) for the whole-system state architecture.
- Filed research receipts under `docs/receipts/`.

## Findings
- **No turnkey "append-only + receipt/provenance CRM" exists.** `[FACT]` Every surveyed CRM (Twenty, EspoCRM, ERPNext, Odoo, NakatomiCRM) is mutable CRUD + a mutable "audit table" — cannot satisfy "no action without a receipt." A CRM can only be an optional read/UI surface projected from our own ledger.
- **Postgres can be the whole backbone** `[FACT/INFER]`: canonical store + append-only hash-chained receipt ledger + outbox + pgvector, in one instance.
- **Twenty** (AGPL-3.0, Postgres, native MCP, ~58k★) is the best-shaped agent-native CRM *surface*; EE-gated files + mutable. `[FACT]`
- **Directus** (Postgres, native MCP, best built-in audit) is technically ideal but **MSCL license gate** (<$5M rev AND <50 staff) is a commercial blocker. `[FACT]`
- **Baserow** (MIT core) = most permissive licensed Postgres backbone w/ built-in row history + snapshots. `[FACT]`
- **EspoCRM** (AGPL-3.0, PG15+, free official MCP, strong native audit) = batteries-included auditable CRM; PHP/REST-only. `[FACT]`
- **ERPNext** disqualified: **MariaDB-only** (Postgres experimental). `[FACT]`
- **NakatomiCRM** (MIT, FastAPI/PG16, `/mcp` ~30 tools) is closest in spirit but solo/unproven (~9★, 0 releases) and **not append-only**. Fork-and-own candidate only. `[FACT]`
- **Graphiti** (Apache-2.0, bi-temporal, provenance-native, first-party MCP) = strongest optional memory/recall layer (projection, not source of truth). `[FACT]`
- Concurrency: idempotency keys + transactional outbox + optimistic (version-column) locking + advisory locks. `[FACT]`
- Backups: pgBackRest WAL/PITR + nightly pg_dump + replicated object store; 3-2-1; scheduled restore drills. `[FACT]`
- **Avoid:** MinIO CE (EOL ~Apr 2026), EventStoreDB (relicensed source-available ESLv2), Anthropic SQLite MCP server (archived, unpatched SQLi). `[FACT]`
- Content-addressed (SHA-256) artifact storage; pgvector only below ~5M vectors (far above solo scale). `[FACT]`

## Decisions made
- Architecture = **one Postgres, CRUD current-state + append-only hash-chained receipt ledger** (not full event sourcing, not a CRM's mutable audit). See ADR-0001.
- Agent reaches state **only via a custom MCP server** (narrow intent-tools, strict schemas, idempotency keys, server-side write guards, human-approval gates). No raw-SQL writes.
- Vectors (pgvector) are a **rebuildable index**, never a source of truth — every embedding carries FK + content-hash to its canonical row.
- Clarified the overloaded term "receipt": **action-receipt** (ledger row) vs **financial receipt** (artifact document).

## Unknowns
- Expected volume (txns/artifacts/vectors per month) → drives partitioning/backup tooling.
- RPO/RTO the business will accept.
- Which actions require human approval + spend thresholds.
- Single host vs HA; object-store trust boundary/hosting.
- Regulatory/retention constraints → plain hash chain vs externally anchored.
- Whether a CRM UI is wanted at all.
- Per-entity attribute detail (quote line-items, job scheduling fields).
- MCP server stack (Python/FastAPI vs TS); fork NakatomiCRM vs start clean.

## Blockers
None.

## Needs Michael decision
- Business-owner choices only: RPO/RTO tolerance; which actions must be human-approved and spend thresholds; whether a CRM UI is desired. (All deferrable to round-2 build gate.)

## Needs coordinator review
- ADR-0001 is a whole-system state decision (PROPOSED). Agent 01 must reconcile with Agents 03 (economics/scoring data shapes), 05 (governance/security — approval gates, RLS, tamper-evidence), and 06 (communications — messages/outbox). Flagged for cross-agent review; NOT self-accepted.

## Files produced
- `docs/research/agent-04-state.md` — full Round-One design (primary deliverable).
- `docs/status/AGENT_STATUS.md` — this file.
- `docs/decisions/ADR-0001-durable-state-architecture.md` — architecture decision (PROPOSED).
- `docs/receipts/2026-10-07-state-architecture-research.md` — research provenance receipt.

## Next action
Round One complete. Commit and push to `research/agent-04-state`. Await coordinator (Agent 01) review of ADR-0001 and round-2 build gate (operator answers to the open UNKNOWNs).
