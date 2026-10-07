# Michael Business OS — Durable State Architecture (Agent 04)

**Round One — research & design only.** No deployment. CAOSCare untouched.
Date: 2026-10-06 · Owner: Agent 04 (state/CRM/memory/business-state)

## The Law (non-negotiable)

1. **No action without a receipt.**
2. **No receipt without provenance.**

Every design choice below exists to make those two sentences mechanically enforceable — not a matter of the agent "remembering" to log, but a property the data layer *cannot* violate.

**Label key:** `[FACT]` sourced/verified · `[INFER]` reasoned judgment · `[REC]` recommendation · `[UNKNOWN]` needs a decision or hands-on test before build.

---

## 0. Executive summary (the decision)

`[REC]` **Build on one PostgreSQL instance as the single source of truth**, with a **CRUD-current-state + append-only hash-chained receipt ledger** (not full event sourcing, not a CRM's mutable "audit table"). Expose it to the agent **only** through a **custom MCP server** with narrow intent-tools, server-side write guards, idempotency keys, and human-approval gates. Store artifacts (photos, quote/receipt PDFs) in **content-addressed object storage** referenced by SHA-256. Use **pgvector in the same Postgres** for semantic recall — as a *rebuildable index*, never a source of truth. Back up with **pgBackRest WAL/PITR + nightly pg_dump + replicated object store**.

`[REC]` **Do not adopt a CRM product as the system of record.** No surveyed CRM is append-only; every one uses mutable CRUD + a mutable "audit" table, which cannot satisfy the Law. `[FACT]` Treat a CRM (if wanted at all) as an optional *read/UI surface* projected from our ledger — not the other way around. The highest-fit codebase to *borrow from* is **NakatomiCRM** (MIT, FastAPI/Postgres, MCP-first) but it is an unproven solo project; fork-and-own, don't depend.

The one-sentence durability test that governs everything:

> **If the agent process and its model vanished right now and a brand-new agent booted against only the durable store, could it (a) know exact current business state, (b) explain and prove every past action, and (c) safely resume in-flight work?** If any answer is "no," the missing data must move out of context into Postgres/object storage.

---

## 1. Candidate systems (URLs / licenses / activity)

### 1a. Open-source CRM / data backbones

| System | URL | License | Activity (Oct 2026) | DB | MCP / API | Native audit | Verdict |
|---|---|---|---|---|---|---|---|
| **Twenty** | github.com/twentyhq/twenty | **AGPL-3.0** core; MIT SDK; some EE-gated files `[FACT]` | ~58k★, v2.45 ~Oct 2026, weekly `[FACT]` | **Postgres** | Native MCP (Cloud); REST+GraphQL auto `[FACT]` | Timeline only; **not** immutable `[FACT]` | Best-shaped agent-native CRM *surface*; AGPL + EE gating; mutable |
| **Directus** | github.com/directus/directus | **MSCL 1.0** (source-available; free only <$5M rev **and** <50 staff; →GPLv3 after 4y) `[FACT]` | ~38k★, native MCP v11.13 `[FACT]` | **Postgres** +others | Native MCP; REST+GraphQL auto `[FACT]` | **Best OOTB** — Activity log + full Revisions/rollback `[FACT]` | Technically ideal data backbone; **license gate is the blocker** |
| **Baserow** | github.com/baserow/baserow | **MIT core** (open-core premium) `[FACT]` | active, v2.3.x `[FACT]` | **Postgres** | Embedded MCP; REST auto (no GraphQL) `[FACT]` | Row change history + audit + snapshots `[FACT]` | Most permissive license w/ built-in history; lighter relational depth |
| **EspoCRM** | github.com/espocrm/espocrm | **AGPL-3.0**, no open-core gating `[FACT]` | active, 10.0.x `[FACT]` | MySQL/Maria/**PG15+** | Official free MCP; REST only `[FACT]` | **Best CRM audit OOTB** (Audited fields + Stream + Preserve) `[FACT]` | Batteries-included auditable CRM; PHP/REST-only |
| **ERPNext/Frappe** | github.com/frappe/erpnext | GPLv3 / MIT framework, no paywall `[FACT]` | ~40k★, v16.x `[FACT]` | **MariaDB only** (PG experimental) `[FACT]` | Community MCP; auto-REST per DocType `[FACT]` | Automatic Version diffs per DocType `[FACT]` | Great shape; **disqualified by MariaDB-only** |
| **Odoo CE** | github.com/odoo/odoo | LGPLv3 core; **EE proprietary** (Studio, Accounting gated) `[FACT]` | ~55k★ `[FACT]` | **Postgres** | Community MCP; XML/JSON-RPC→JSON-2 in v20 `[FACT]` | Add-on (OCA auditlog) `[FACT]` | Heavy, code-first custom entities, open-core; wrong shape |
| NocoDB | github.com/nocodb/nocodb | AGPL→**Sustainable-Use** (~Jan 2026; customer-facing restricted) `[FACT]` | ~65k★ `[FACT]` | **Postgres** | Embedded MCP; REST | Audit log (light) | Watch new license clause |
| Dolibarr | github.com/Dolibarr/dolibarr | GPL-3.0 `[FACT]` | ~7.7k★, v22 `[FACT]` | **Postgres** 1st-class | 3rd-party MCP (55+ tools); REST | **Weak** (security events only) `[FACT]` | Postgres-friendly but weak audit |
| SuiteCRM | github.com/salesagility/SuiteCRM | AGPL-3.0 | ~5.8k★ | **MySQL only** `[FACT]` | 3rd-party MCP; REST | Per-field change log | MySQL-only; sales-shaped |
| Monica | github.com/monicahq/monica | AGPL-3.0 | **stalling** (v5 beta since 2025) `[FACT]` | MySQL | none | none | Reject — fixed personal schema |
| Krayin | github.com/krayin/laravel-crm | MIT | active | MySQL | none | none | Reject — MySQL, no MCP/audit |
| *Watch* **Teable** | github.com/teableio/teable | AGPL core/MIT pkgs `[FACT]` | active | **Postgres** | community MCP | — | Round-2 look (Postgres-native no-code DB) |
| *Watch* **Relaticle** | github.com/relaticle/relaticle | AGPL-3.0 `[FACT]` | 1.7k★, active `[FACT]` | **Postgres 17** | 37 MCP tools; REST `[FACT]` | No (mutable) `[FACT]` | Heavy PHP/Filament; MCP is add-on |

### 1b. Agent-native / MCP-first CRMs

| System | URL | License | Activity | Notes |
|---|---|---|---|---|
| **NakatomiCRM** | github.com/mrdulasolutions/NakatomiCRM | **MIT** `[FACT]` | created Apr 2026; ~9★; **0 releases, 0 human issues** `[FACT]` | Python/FastAPI/PG16, `/mcp` ~30 tools. **Closest in spirit**, but solo/unproven and **NOT append-only** (soft-delete + mutable audit) `[FACT]`. Fork-and-own candidate. |
| Headless_CRM | github.com/Cam-Smith-One/Headless_CRM | AGPL-3.0 | 1★ solo `[FACT]` | Hono/Node, PG+pgvector, 29 MCP tools, `events` audit table. Good *reference design*, not a dependency |
| Attio / HubSpot / Salesforce Agentforce | — | proprietary SaaS | — | **Reject** — no self-host, no data ownership, not append-only `[FACT]` |
| cluster-software/agent-crm | github.com | — | **deprecated** shell `[FACT]` | Reject |

### 1c. Agent-memory frameworks (the semantic/recall layer)

| System | URL | License | Activity | Durability | MCP | Fit |
|---|---|---|---|---|---|---|
| **Graphiti** (Zep) | github.com/getzep/graphiti | **Apache-2.0** `[FACT]` | ~31k★, v0.30.x `[FACT]` | Durable; Neo4j/FalkorDB/Neptune; **bi-temporal edges w/ fact invalidation + provenance** (facts invalidated, not deleted) `[FACT]` | First-party MCP `[FACT]` | **Strongest memory fit** — "what was true, as-of-when, on what evidence". Projection layer, not system-of-record |
| Cognee | github.com/topoteretes/cognee | Apache-2.0 | ~31k★ `[FACT]` | Durable; can run on **single Postgres+pgvector** `[FACT]` | First-party MCP `[FACT]` | Strong runner-up; `[UNKNOWN]` true append-only/bi-temporal |
| Letta (MemGPT) | github.com/letta-ai/letta | Apache-2.0 | ~25k★ `[FACT]` | Durable PG+pgvector; **self-editing** memory `[FACT]` | consumes MCP | Mutable-by-design — opposite of append-only |
| Mem0 | github.com/mem0ai/mem0 | Apache-2.0 | ~67k★ `[FACT]` | **default `/tmp` = volatile**; durable only if pointed at PG/Qdrant; graph memory now paid `[FACT]` | exposes MCP | Mutable/LLM-summarized; weaker fit |
| *Reject/stale* | Supermemory (auto-forgets), Zep CE (discontinued Apr 2025 → use Graphiti), Memary (stale 2024) `[FACT]` | | | | | |

### 1d. Ledger / provenance building blocks

- **Marten** — github.com/JasperFx/marten — **MIT**, active — append-only event streams + projections **on Postgres**. `[FACT]` Best OSS event-store fit *if .NET*; otherwise a plain append-only table is simpler. `[REC]`
- **KurrentDB/EventStoreDB** — relicensed **source-available ESLv2 (not OSI)** v24.10+ → lock-in risk. `[FACT]` Avoid for a data-ownership-first system.
- **MCP** — github.com/modelcontextprotocol — **MIT**, now under Linux Foundation's Agentic AI Foundation. `[FACT]` The agent interface.
- **Postgres MCP Pro** — crystaldba/postgres-mcp — MIT, ~3.4k★ — generic Postgres MCP front. `[FACT]` Useful for read/admin; **not** for the agent's write path (too broad).
- **Avoid** Anthropic's official SQLite MCP server — archived with unpatched SQLi. `[FACT]`
- Provenance standards to build on: **W3C PROV, OpenTelemetry, OpenLineage**. `[FACT]` "Cryptographic agent receipts" is active 2026 research (arXiv 2610.00327, 2512.17259) — implement the *pattern* yourself; don't depend on preprint code. `[FACT]`

---

## 2. Recommended state architecture

```
                 ┌─────────────────────────────────────────────┐
   LLM Agent ───▶│  MCP Server  (ONLY write path)              │
  (stateless,    │  • narrow intent-tools (create_quote …)     │
   replaceable)  │  • strict input schemas (Zod/Pydantic)      │
                 │  • idempotency keys · write guards          │
                 │  • human-approval gates                     │
                 └───────────────┬─────────────────────────────┘
                                 │ one transaction per action
                                 ▼
   ┌───────────────────────── PostgreSQL (source of truth) ──────────────────────┐
   │  Current-state tables      Append-only ledger         Vector index           │
   │  (customers, quotes,  ┌──▶ receipts (hash-chained) ─┐ (pgvector, REBUILDABLE)│
   │   jobs, payments…)    │    provenance               │  embeddings → FK to    │
   │   + version column    │    agent_actions            │  canonical rows        │
   │   + row history        │   approvals · outbox        │                        │
   └───────────┬────────────┘                            └────────────────────────┘
               │ content-hash references                 WAL ─▶ pgBackRest (PITR)
               ▼
   ┌─────────────────────── Content-Addressed Object Store ──────────────────────┐
   │  artifacts by SHA-256:  photos · quote PDFs · financial receipts · msg blobs │
   │  local FS → Garage/SeaweedFS → cloud (S3 API).  NOT MinIO CE (EOL).          │
   └──────────────────────────────────────────────────────────────────────────────┘
```

**Design rules:**
- `[REC]` **One Postgres** is canonical store + receipt ledger + outbox + vectors. Collapsing infra is the biggest reliability win for a solo operator. `[INFER]`
- `[REC]` **CRUD current-state tables** (query normally) **+ append-only hash-chained ledger** for every agent action/approval/receipt/provenance. This hybrid gives "who/why/what + replay for what matters" without the complexity of full event sourcing. `[FACT]` Full event sourcing is overkill here; a CRM's mutable audit table is insufficient. `[INFER]`
- `[REC]` The **MCP server is the only write path.** The agent never runs raw SQL writes. `[FACT]` (raw-SQL-to-LLM is the documented anti-pattern.)
- `[REC]` Every write + its receipt + its outbox entry commit in the **same DB transaction** → the receipt exists iff the action happened (no dual-write gap). `[FACT]`

---

## 3. Canonical entities & relationships

The 23 tracked nouns group into six domains. All are plain relational tables (we define the schema — no CRM's fixed schema is imposed). Every mutating table carries `id (uuid)`, `version int`, `created_at`, `updated_at`, and every mutation emits a receipt (§4).

**Parties & acquisition**
- `lead_sources` (channel/campaign) → `leads` → convert to `customers`
- `sellers` (suppliers/vendors), `referrals` (referrer → referred, maps to a lead/customer)

**Pipeline / revenue**
- `opportunities` (scored potential deal; FK → customer/lead) → `quotes` (versioned offers; FK → opportunity) → `jobs` (scheduled/performed work; FK → quote) → `sales` (closed revenue event; FK → job/quote)

**Money**
- `payments` (inbound/outbound; FK → sale/purchase), `purchases` (from `sellers`; FK → `materials`/`equipment`)
- **financial `receipts`** = proof-of-purchase *artifacts* (PDF/photo) stored in object store, referenced by content-hash → **distinct from action-receipts** (see note below)

**Resources & cost**
- `equipment` (owned assets), `materials` (consumables used on jobs), `travel` (trips w/ cost/mileage; FK → job)

**Communications**
- `messages` (inbound/outbound, any channel; FK → customer/lead), `follow_ups` (scheduled next-touch), `reviews` (customer feedback/rating; FK → job/customer)

**Governance / agent cognition** *(the Law's core)*
- `agent_actions`, `approvals`, **action-`receipts`**, `provenance`, `outcomes` (result of an action/job vs. expectation), `lessons` (durable learnings; link to outcomes)

```
lead_source → lead → customer ──┬──< opportunity ──< quote ──< job ──< sale ──< payment
                                │                                 │
referral ───────────────────────┘                     travel >───┤
                                                      materials >─┤
                                                      equipment ──┤ (usage)
seller ──< purchase ──< payment ; purchase ──> financial_receipt(artifact)
customer ──< message ; customer ──< review ; (anything) ──< follow_up
EVERY mutation ⇒ agent_action ⇒ receipt ⇒ provenance ; job/action ⇒ outcome ⇒ lesson
```

> **⚠ The word "receipt" is overloaded in the brief.** Two distinct things, both needed:
> 1. **Action-receipt** (the Law's receipt) — an immutable ledger row proving *an agent action occurred*. §4.
> 2. **Financial receipt** — a document (vendor PDF/photo) proving *a purchase/payment*. An artifact in object storage, referenced by hash, and itself attached to an action-receipt when recorded.
> `[REC]` Name them `receipts` (ledger) and `purchase_documents` (or `financial_receipts`) to avoid collision.

`[UNKNOWN]` Exact attribute lists per entity (e.g., quote line-items model, job scheduling fields) — to be finalized with the operator in round 2.

---

## 4. Receipt schema (the ledger — append-only, hash-chained)

Every state-changing action produces exactly one receipt, in the same transaction as the change. The table is **INSERT-only** (agent role has no UPDATE/DELETE; a `BEFORE UPDATE OR DELETE` trigger raises). Tamper-evidence via per-row hash chaining (`prev_hash` → `row_hash`). `[FACT]` This gives append-only forward integrity "with zero extra machinery."

```sql
CREATE TABLE receipts (
  id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- monotonic seq
  receipt_uuid    uuid NOT NULL DEFAULT gen_random_uuid(),
  occurred_at     timestamptz NOT NULL DEFAULT now(),
  action_id       uuid NOT NULL REFERENCES agent_actions(id),      -- what was attempted
  intent          text NOT NULL,                 -- human-readable "why" (required)
  tool_name       text NOT NULL,                 -- MCP tool invoked
  tool_input      jsonb NOT NULL,                -- validated args (secrets redacted)
  entity_type     text NOT NULL,                 -- e.g. 'quote'
  entity_id       uuid NOT NULL,                 -- affected row
  effect          text NOT NULL,                 -- create|update|delete(logical)|send|pay…
  before_state    jsonb,                         -- snapshot pre-change (NULL on create)
  after_state     jsonb,                         -- snapshot post-change
  idempotency_key text NOT NULL,                 -- UNIQUE; dedupes retries
  approval_id     uuid REFERENCES approvals(id), -- NULL unless gated action
  provenance_id   uuid NOT NULL REFERENCES provenance(id),  -- NO receipt without provenance
  artifact_hashes text[] DEFAULT '{}',           -- SHA-256 of attached docs/photos
  outcome_id      uuid REFERENCES outcomes(id),  -- filled when result known
  prev_hash       bytea NOT NULL,                -- row_hash of receipt id-1
  row_hash        bytea NOT NULL,                -- sha256(canonical(this row ⊕ prev_hash))
  UNIQUE (idempotency_key)
);
-- enforce: agent role = INSERT only; immutability trigger; monthly range partition.
```

**Enforcement** `[REC]`: agent DB role granted `INSERT` only; `REVOKE UPDATE, DELETE`; `BEFORE UPDATE OR DELETE` trigger `RAISE EXCEPTION`; `row_hash` computed in trigger over canonical serialization so the agent cannot forge the chain. `[FACT]` Optional later: periodic Merkle batching / external anchoring if third-party-verifiable proofs are ever required — start with the simpler chain. `[FACT]`

**Invariants (DB-enforced):** no row without `intent`, `provenance_id`, `idempotency_key`; no action-with-side-effect commits unless its receipt commits in the same tx; gated actions require non-null `approval_id` with status `approved`.

---

## 5. Provenance schema (no receipt without it)

Provenance answers *who/what/on-what-basis* — modeled on **W3C PROV** (agent / activity / entity / used / wasGeneratedBy). `[FACT]` It must survive model changes, so it records the exact model identity at action time.

```sql
CREATE TABLE provenance (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  created_at      timestamptz NOT NULL DEFAULT now(),
  actor_type      text NOT NULL,          -- 'agent' | 'human' | 'system' | 'external'
  agent_name      text,                   -- logical agent (e.g. 'agent-04-state')
  model_id        text,                   -- exact: 'claude-opus-4-8[1m]'
  model_version   text,                   -- pinned snapshot/version string
  prompt_hash     bytea,                  -- sha256 of system+task prompt used
  tool_version    text,                   -- MCP server/tool version
  trace_id        text,                   -- OpenTelemetry trace id (links the run)
  inputs_used     jsonb NOT NULL,         -- source records/evidence consulted (ids+hashes)
  reasoning_ref   text,                   -- pointer to stored reasoning/plan (not context)
  source_uri      text,                   -- external source if action came from outside
  confidence      numeric,                -- optional agent self-report
  human_actor     text                    -- email/id when actor_type='human'
);
```

`[REC]` `inputs_used` lists the canonical record ids **and their content-hashes** the decision relied on — so we can later prove the decision was made on data that actually existed in that state. Ties provenance to the immutable record graph.

---

## 6. Agent read/write model

`[REC]` **The MCP server is the sole interface.** Two DB roles:
- **`agent_read`** — read-only, no `BYPASSRLS`; backs read tools and semantic search.
- **`agent_write`** — only the specific grants needed; `INSERT`-only on `receipts`/`provenance`; no raw SQL exposed.

**Tool design** `[FACT]`/`[REC]`:
- **Narrow intent-tools**, not `run_sql`: `create_quote`, `record_payment`, `log_message`, `schedule_follow_up`, `record_outcome`, `capture_lesson`, etc. Separate **read** tools from **write** tools.
- **Strict input schemas** (Zod/Pydantic) on every tool; parameterized queries only.
- **Every write tool takes an `idempotency_key`** and writes `{state change + receipt + provenance + outbox}` in one transaction.
- **Server-side write guards:** amount/frequency caps, allow-listed recipients, state-machine checks ("can't invoice an unaccepted quote"). The guard lives in the server, never relies on the model choosing to behave. `[FACT]`
- **Human-approval gate:** high-impact tools (spend money, send external comms, irreversible actions) return a **pending-approval receipt** and do **not** execute until a human approves; the approval is itself a logged provenance event. `[FACT]`

`[UNKNOWN]` Exact high-impact/approval-required action list and spend thresholds — operator decision (round 2).

---

## 7. Concurrency controls

Single agent, but parallel/retried tool calls are the real hazard. `[FACT]`
- **Idempotency keys** — `UNIQUE` column + `INSERT … ON CONFLICT DO NOTHING` → exactly-once *effect* for retried/duplicated tool calls. `[FACT]`
- **Transactional outbox** — domain change + outbox row in one tx; async relay with idempotent consumers → crash-safe external side effects (emails/payments not lost or double-sent). Pull work with `SELECT … FOR UPDATE SKIP LOCKED`. `[FACT]`
- **Optimistic locking** — `version` column; update only if version matches, else retry. Ideal for rare-conflict, ledger-style data. `[FACT]`
- **Advisory locks** — coarse "one-at-a-time" sections (e.g., the planning loop, a migration) without hot-row contention. `[FACT]`

---

## 8. Version / history model

`[REC]` Two complementary layers:
1. **Receipt ledger (§4)** = authoritative, immutable "what happened & why" — the audit/replay spine.
2. **Row history** on current-state tables for "what did this row look like at time T":
   - `[REC]` App-layer snapshots (`before_state`/`after_state` already captured in each receipt → history is *derivable from the ledger for free*). `[INFER]`
   - Optional: Postgres trigger→history table or `temporal_tables` extension. `[FACT]` Note Postgres 18 still has **no built-in system versioning** (temporal PK/FK only). `[FACT]` Triggers add ~4%/~18–22% write overhead (INSERT/UPDATE). `[FACT]`
   - **`version` column** on every mutable entity drives optimistic locking (§7) and gives a cheap monotonic revision number.

Because `before_state`/`after_state` live in the immutable ledger, full point-in-time reconstruction is possible without a second history system — the ledger *is* the history. `[INFER]`

---

## 9. Backup / recovery

`[REC]` `[FACT]`
- **Primary:** continuous WAL archiving + PITR via **pgBackRest** (recommended for self-hosted PG under ~1TB), archiving to the same S3-compatible store used for artifacts.
- **Secondary:** nightly **`pg_dump`** for portable/human-readable recovery. (Note: `pg_dump` alone **cannot** do PITR — no WAL replay. `[FACT]`)
- **Artifacts:** object store needs its *own* replication/versioning — Postgres backups don't cover it.
- **3-2-1:** 3 copies, 2 media/targets, 1 offsite (second bucket).
- **Restore drills:** scheduled test restore into a scratch DB + row-count/hash comparison + re-verify the receipt hash-chain. "A successful backup job is not proof of recoverability." `[FACT]`
- `[UNKNOWN]` RPO/RTO targets — operator must set (how much data loss / downtime the business tolerates).

**Model/agent-replacement recovery:** because provenance pins `model_id`/`model_version` and vectors are rebuildable (§11), swapping the model means re-embedding from the source of truth — no state loss. `[INFER]`

---

## 10. Search strategy

`[REC]` Three tiers, all over the one Postgres:
1. **Relational/exact** — SQL on current-state tables (filters, joins, ledger lookups by entity/action). Authoritative.
2. **Lexical** — Postgres full-text search (`tsvector`/GIN) over messages, notes, quotes. `[INFER]`
3. **Semantic** — pgvector ANN over embeddings for "find similar past jobs/decisions/customers." Returns candidate **ids**, which are then read authoritatively from relational tables. `[REC]`

`[REC]` Hybrid retrieval = lexical + vector, re-ranked; but **answers are always grounded by reading the canonical row**, never by trusting the embedding text.

---

## 11. Vector-memory role

`[FACT]`/`[REC]` **pgvector in the same Postgres** (solo-scale is far below the ~5M-vector point where a dedicated vector DB like Qdrant is justified; pgvector inherits our backups/RLS/monitoring).
- **Vectors are a derived, rebuildable index — never a source of truth.** Every embedding row carries a **FK + content-hash to the canonical record it came from**, so the entire vector store can be regenerated after a model/embedding-model change. `[REC]`
- **Belongs in vectors:** embeddings of messages, notes, past decisions, job descriptions, lessons — for semantic recall.
- **Must NOT be only in vectors:** money, commitments, receipts, provenance (see §12).
- **Optional round-2 memory layer:** **Graphiti** (bi-temporal, provenance-native, Apache-2.0) *projecting from* our receipt store for "what did we believe, and when" — but it is the recall layer, **not** the system of record. `[REC]` `[UNKNOWN]` exact Graphiti edge schema — verify hands-on.

---

## 12. Data that must NEVER exist only in model/agent memory

**Principle:** `[INFER]` *The context window is volatile scratch space, not storage. Anything whose loss would make a past action unexplainable, unrepeatable, or unverifiable MUST be committed to the durable store before the action is "done."* `[FACT]` (the context window is flushed every run).

Must be persisted (never context-only):
1. **Receipts** of every action (the ledger) — else the Law is already broken.
2. **Provenance** for each receipt (actor, model+version, intent, inputs-used).
3. **Canonical business facts** — customers, quotes, jobs, sales, invoices, payments, balances, and **promises/commitments made to third parties.**
4. **Idempotency keys + outbox entries** for in-flight external side effects (crash mid-send resolves deterministically).
5. **Approvals / policy decisions** (human sign-offs).
6. **Artifacts + their content-hashes** (photos, quote/receipt PDFs).
7. **Agent plan / open tasks / state-machine position** needed to resume safely after restart or agent replacement.

The §0 durability test is the enforcement criterion for this list.

---

## 13. 24-hour MVP

Goal: the Law is enforceable end-to-end for a *minimal* slice, with nothing load-bearing left in model memory. `[REC]`

**Hour 0–4 — foundation**
- Postgres 16 in Docker; enable `pgvector`; create `agent_read` / `agent_write` roles (least privilege).
- DDL: `receipts`, `provenance`, `agent_actions`, `approvals`, `outbox` + a thin slice of current-state tables: `customers`, `leads`, `opportunities`, `quotes`, `messages`, `payments`.
- Immutability: INSERT-only grants + `BEFORE UPDATE/DELETE` trigger + `row_hash`/`prev_hash` chaining trigger on `receipts`.

**Hour 4–10 — the write spine**
- Minimal **MCP server** (Python/FastAPI or TS) exposing ~6 intent-tools: `create_customer`, `log_lead`, `create_quote`, `log_message`, `record_payment`, `schedule_follow_up` — each writing `{change + receipt + provenance + outbox}` in one tx, with `idempotency_key`.
- 2 read tools: `get_entity`, `search` (SQL + lexical first; vector optional).
- One approval-gated tool (e.g. `record_payment` ≥ threshold) returning a pending-approval receipt.

**Hour 10–16 — artifacts + integrity**
- Content-addressed artifact store: start with **local FS CAS** (`ab/cd/<sha256>`); `attach_document` tool records hash onto a receipt.
- `verify_chain` admin script: walk `receipts`, recompute hashes, assert chain intact.

**Hour 16–22 — durability + recall**
- pgBackRest WAL archiving + one nightly `pg_dump`; perform **one real restore drill** into a scratch DB and re-run `verify_chain`.
- pgvector: embed `messages` + `quotes`, store with FK+hash to source; wire `search` to hybrid.
- Reboot test: kill everything, restart, confirm a fresh agent can read current state + explain the last action from receipts alone (the §0 test).

**Hour 22–24 — seal & document**
- Seed a realistic walkthrough (lead → quote → approval → payment → receipt → outcome → lesson).
- Write `RUNBOOK.md` (restore, verify-chain, rotate keys) and record open `[UNKNOWN]`s for round 2.

**Explicitly out of scope for the MVP:** full 23-entity schema, Graphiti, Merkle/anchoring, HA, cloud object store, CRM UI surface.

---

## 14. Migration path

`[REC]` Four stages, each reversible, never touching CAOSCare until stage 3.

1. **Greenfield ledger-first (round 2 build):** stand up Postgres + MCP + receipt ledger as above. This is the durable spine; everything else projects from it.
2. **Backfill / import:** if existing business data lives elsewhere (spreadsheets, an existing CRM), import it as *seed current-state rows* each with a genesis receipt (`effect='import'`, provenance `actor_type='system'`, `source_uri`). History before this point is attested, not reconstructed. `[INFER]`
3. **Optional CRM surface:** if a UI/CRM is wanted, attach **Twenty** (or EspoCRM for built-in audit) as a **read/projection layer fed from the ledger via the outbox** — CRM is downstream, never the source of truth. Keeps data ownership and the Law intact. `[REC]`
4. **Scale-out (only if needed):** local FS CAS → Garage/SeaweedFS (S3 API) **not MinIO CE** (EOL `[FACT]`); pgvector → Qdrant only past ~5M vectors; add Merkle/external anchoring only if third-party-verifiable proofs become a requirement.

**Model/agent replacement is a first-class migration, not an exception:** pin `model_id` in provenance, keep all load-bearing state in Postgres/object storage, keep vectors rebuildable → a new model or a fully new agent boots against the store and resumes. `[INFER]`

---

## Consolidated open questions for the operator (round 2 gate)

- `[UNKNOWN]` Expected volume (txns / artifacts / vectors per month) → drives partitioning & backup tooling.
- `[UNKNOWN]` RPO/RTO the business will accept.
- `[UNKNOWN]` Which actions require human approval + spend thresholds.
- `[UNKNOWN]` Single host vs. HA; trust boundary / hosting for the object store.
- `[UNKNOWN]` Regulatory/retention constraints → plain hash chain vs. externally anchored.
- `[UNKNOWN]` Do we want a CRM UI at all, or is MCP + dashboards enough?
- `[UNKNOWN]` Per-entity attribute detail (quote line-items, job scheduling fields, etc.).
- `[UNKNOWN]` Language/stack for the MCP server (Python/FastAPI vs TS) and whether to fork NakatomiCRM or start clean.
```
