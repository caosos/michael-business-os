# Michael Business OS — Coordinator Architecture (Agent 01)

**Round One: Research & Design only.** No deployment, no production code, no purchases, no outbound contact, nothing published. This document is the coordinator's architecture decision record and the integration contract that makes Agents 02–07 converge into ONE system.

**Date:** 2026-10-06 · **Author:** Agent 01 (chief coordinator / systems architect)

> **UPDATE 2026-10-06, round-one reconciliation.** All six specialists have reported. The integrated decision is now **`docs/research/agent-01-integration.md`**. ADR-0001/0002/0003 are ACCEPTED, and ADR-0004–0008 have been added (see `docs/decisions/INDEX.md`). This file remains the technology survey. Corrections that follow from reconciliation:
> - **HumanLayer** is withdrawn: Agent 05 reports the repo is effectively deprecated. A custom Telegram approval bot replaces it (ADR-0006).
> - **n8n** is a connector only, never the orchestrator (ADR-0006).
> - The governance layer adopts Agent 05's Action Gateway, PDP and execution guard, with a merged 3-level PANIC (ADR-0005).
> - Scope is **flips + services** (Michael, ADR-0007).
> - The Item and Receipt in §4 are superseded by the frozen JSON Schemas in `docs/research/contracts/` (ADR-0004).

Every substantive claim below is labeled **FACT** (web-verified), **INFERENCE** (reasoning), **RECOMMENDATION** (adopt/consider/avoid), or **UNKNOWN**.

---

## 0. Context & the one invariant that shapes everything

Michael wants a persistent, self-hosted AI business OS that runs 24/7 on a single server he controls — discovering opportunities, normalizing, researching, scoring, recommending, requesting his approval, acting, recording receipts, observing outcomes, and learning. Seven agents research in parallel (02 discovery, 03 deal economics, 04 CRM/state, 05 governance/security, 06 comms, 07 marketing). Agent 01 owns the overall architecture and the method for reconciling the other six.

The governance invariant drives every technical choice:

> **No action without a receipt. No receipt without provenance.**

The human interface is one decision primitive: **YES / NO / MODIFY / HOLD**.

**Priority order used to break every tie:** `1) Provenance & auditability → 2) Safety/control (kill-switch, approvals, cost caps) → 3) Durability (survive crash/restart while Michael sleeps) → 4) Single-operator simplicity → 5) Capability/features.`

A single architectural idea satisfies the invariant mechanically: **Postgres is the spine, and the receipt + the state change commit in the SAME database transaction.** You then literally cannot have an action without a receipt, or a receipt without its provenance row — the database enforces it, not discipline.

---

## 1. Recommended Architecture (the stack)

| Layer | Recommendation | License | Why (INFERENCE) |
|---|---|---|---|
| **Host / runtime** | **Podman + Quadlet + systemd**, authored from Docker Compose files | Apache-2.0 | Boot-persistent, auto-restart, rootless, journald logs, zero extra orchestrator. Survives reboots while Michael sleeps. Avoid k3s/Nomad on one box. |
| **Spine / datastore** | **PostgreSQL** (+ pgvector, pg_cron, LISTEN/NOTIFY) | PostgreSQL (BSD-like) | One process = relational state + JSONB receipts + vector memory + scheduler + wake-signal, under one transaction boundary, one backup, one credential set. The atomic receipt+action guarantee lives here. |
| **Durable backbone** | **DBOS Transact** (default) — library, Postgres-only: durable workflows + queue + cron + exactly-once steps + durable messaging | MIT | *Workflow state lives in your Postgres and runs in-process, so a workflow step and its receipt insert commit in one transaction.* Lightest footprint, cleanest license, perfectly aligned with the spine thesis. |
| **Agent reasoning** | **LangGraph** or **Pydantic AI** (Python-first) | MIT | LangGraph: native Postgres checkpointers = crash-resume + human-in-the-loop interrupts. Pydantic AI: typed, native DBOS integration. Durable engine owns crash-resume; framework owns reasoning. |
| **Tool boundary** | **MCP** (stdio for co-located tools, Streamable HTTP across trust boundaries) | MIT SDKs | De-facto standard; OAuth-scope per tool call becomes part of each receipt's provenance. |
| **Event / provenance log** | **Postgres append-only tables + transactional outbox** (insert-only; revoke UPDATE/DELETE) | PostgreSQL | Only option where receipt and state change are atomically coupled → mechanically enforces the invariant. |
| **Business-state / CRM** | **Build state in Postgres as system-of-record**; **Twenty** CRM as optional human-facing projection | Twenty = AGPL-3.0 | A packaged CRM owning a second source of truth fragments provenance. Keep the ledger in Postgres; CRM is a read-model. |
| **Approvals (YES/NO/MODIFY/HOLD)** | DBOS durable workflow blocks on an approval message; decision+diff as append-only rows; delivery via Telegram/Slack bot or **HumanLayer** | HumanLayer SDK Apache-2.0 | Durable wait = HOLD survives restart at zero compute. Signal payload = MODIFY. Every decision is a provenanced receipt. |
| **LLM cost gateway** | **LiteLLM** proxy — ALL model calls route through it | MIT | Mature self-hostable **hard** budget caps + rate limits + virtual keys, enforced at the proxy (the model cannot edit it). Doubles as the spend kill-switch. Prometheus metrics. |
| **Observability** | **Langfuse** (LLM/agent traces, token, cost, prompts) + **Prometheus/Grafana/Alertmanager** (infra, DLQ, stuck-runs); OTLP wire format | Langfuse MIT core; Prometheus Apache-2.0; Grafana/Loki/Tempo AGPL-3.0 | Langfuse = only purpose-built LLM tracer that is fully MIT with no core feature-gating. Prometheus+Grafana for host/queue/DB. |
| **Secrets** | **OpenBao** (dynamic short-lived creds) + **SOPS** (GitOps bootstrap secrets) | MPL-2.0 | Dynamic leased credentials are the mechanism behind least-privilege and credential-based kill-switches. OSI license (vs Vault's BSL). |
| **Sandboxing** | **gVisor** baseline for all tool/code exec; **self-hosted E2B** (Firecracker microVM) for model-generated code touching data/creds; default-deny egress proxy + controlled DNS | gVisor Apache-2.0; E2B Apache-2.0 | 2026 consensus: gVisor minimum for untrusted code, microVM when it touches data/creds. Bare Docker is NOT a security boundary. |
| **Backups** | **pgBackRest** → off-box object storage, PITR + incremental | MIT | Fast restore + point-in-time recovery; keep backups off the single server (SPOF mitigation). |

### Resolved tension — Temporal vs DBOS (worked example of §7's framework)
The integration stream recommended **Temporal** for durable approvals; the orchestration stream recommended **DBOS/Hatchet**. Scored on the rubric (§7): all three clear the provenance hard-gate. Temporal wins *capability/maturity* but loses hard on *single-operator ops burden* (multiple services: frontend/history/matching/worker + DB + UI) and doesn't keep state in *your* Postgres transaction. DBOS keeps workflow state in the same Postgres, in-process, so step + receipt commit atomically — directly advancing priorities #1 (provenance) and #4 (simplicity). **RECOMMENDATION: DBOS as the backbone. Hatchet (MIT, Postgres-only, standalone engine + dashboard) is the primary alternative if you want an out-of-process engine with a UI. Temporal is the documented scale-out option if the system outgrows one box.**

---

## 2. Textual Architecture Diagram

```
                           ┌──────────────────────────────────────────────┐
                           │  MICHAEL  (Telegram / Slack / web)             │
                           │  decides:  YES · NO · MODIFY · HOLD            │
                           └───────────────▲───────────────┬───────────────┘
                                   approval │ request       │ decision (+diff)
┌───────────────────────────────────────────┴───────────────▼─────────────────────────┐
│  GOVERNANCE / CONTROL PLANE  (things the agent process CANNOT modify)                 │
│   LiteLLM hard spend caps + rate limits  │  OpenBao short-lived scoped creds          │
│   default-deny egress proxy + DNS        │  tiered approval queue                     │
│   ► PANIC = revoke creds + cut egress + drain queues (one atomic action)              │
└───────────────────────────────────────────┬─────────────────────────────────────────┘
                                             │
┌────────────────────────────────────────────┴────────────────────────────────────────┐
│  DURABLE BACKBONE  — DBOS Transact (crash-resume, retries, queue, cron, durable waits) │
│                                                                                        │
│  DISCOVER → NORMALIZE → RESEARCH → SCORE → RECOMMEND →[APPROVAL GATE]→ ACT → RECEIPT    │
│    (02)       (01)       (02/03)   (03)     (01)      (05/06)  (04/06/07)   (all)       │
│                                                             │                          │
│                                                   OUTCOME → LEARN ───────┐ (feeds SCORE)│
│                                                     (04)     (03)        │              │
│     Agents 02–07 = LangGraph / Pydantic AI reasoning nodes ◄─────────────┘              │
│     call tools only via ──────────────┐                                                │
└────────────────────────────────────────┼──────────────────────────────────────────────┘
                                          │ MCP (stdio / Streamable HTTP, OAuth scope)
          ┌───────────────────────────────┼───────────────────────────────┐
          ▼                                ▼                               ▼
   ┌─────────────┐              ┌────────────────────┐          ┌──────────────────┐
   │ Tool servers│              │ Sandbox (gVisor /   │          │ LLM calls ──► LiteLLM
   │ (sources,   │              │ E2B Firecracker for │          │ (every call metered,
   │ comms, CRM) │              │ model-gen code)     │          │  capped, traced)  │
   └─────────────┘              └────────────────────┘          └──────────────────┘
          │                                                               │
          ▼                                                               ▼
┌───────────────────────────────────────────────────────────────────────────────────────┐
│  POSTGRES — THE SPINE   (one DB, one backup, one transaction boundary)                  │
│   items · scores · recommendations · approvals(append-only) ·                           │
│   receipts(append-only) · provenance(append-only) · outbox ·                            │
│   pgvector memory · business_state (system of record)                                   │
│   ▲ receipt + state change commit in the SAME transaction ◄── the invariant, enforced   │
└───────────────────────────────┬─────────────────────────────┬─────────────────────────┘
                                 │ outbox (optional fan-out)    │ WAL
                          NATS JetStream / Debezium       pgBackRest → off-box object store
                                 │                              (PITR, incremental)
                                 ▼
                     Twenty CRM (read-model projection, optional)

  OBSERVABILITY (OTLP):  Langfuse (agent traces/token/cost) · Prometheus+Grafana+Alertmanager
                         (host/queue/DLQ/stuck-run alerts)
  RUNTIME:  Podman + Quadlet + systemd  (restart=on-failure, boot-persistent)
```

---

## 3. The Core Flow as a durable state machine

Every opportunity is an **Item** that moves through one explicit state machine. The states ARE the architecture. Each transition is a DBOS workflow step that (a) is crash-resumable and idempotent, and (b) writes a receipt + provenance in the same transaction as the state change.

| State | Owner | Writes (Item fields) | Emits |
|---|---|---|---|
| DISCOVER | 02 | `raw`, `source` | provenance (source URL + fetched_at) |
| NORMALIZE | 01 contract | `normalized` | provenance (mapping + version) |
| RESEARCH | 02/03 | `research[]` | provenance per finding (URL/model+version) |
| SCORE | 03 | `scores{}` | provenance (formula + model version) |
| RECOMMEND | 01 | `recommendation{}` (action, cost, reversibility, confidence) | provenance |
| APPROVAL GATE | Michael | `approval{}` (YES/NO/MODIFY/HOLD, decided_by/at, modifications) | append-only approval row = receipt |
| ACT | 04/06/07 | — | **receipt (mandatory)** + external_refs |
| RECEIPT | all | `receipts[]` | — |
| OUTCOME | 04 | `outcomes[]` | provenance (observed result + source) |
| LEARN | 03 | score-model adjustment | provenance (what changed + why) → feeds SCORE |

**Durability guarantee (acceptance-tested in §10):** kill the process mid-ACT → on restart DBOS resumes at the exact step with no duplicated side-effect; the receipt either committed with the action or neither did.

---

## 4. Stable Interface Contracts (the spine — frozen early, owned by Agent 01, versioned)

Specialists build to these contracts, not to each other. Changes require Agent 01 sign-off and a version bump.

**1. `Item` (opportunity envelope).** `id`, `created_at`, `source`, `state` (enum §3), `raw` (immutable as-discovered), `normalized` (typed), `research[]` (finding + source_url + fetched_at), `scores{}` (per-dimension + composite + model/version), `recommendation{}` (action, rationale, cost_estimate, reversibility, confidence), `approval{}` (status, decided_by, decided_at, modifications), `receipts[]`, `outcomes[]`, `provenance[]`.

**2. `Receipt` (emitted for EVERY action).** `{ id, item_id, action, actor (agent|human), inputs_hash, timestamp, cost, external_refs, result, provenance_chain }`. DB constraint: an ACT transition cannot commit without a matching receipt row.

**3. `Provenance` entry (append-only).** Links every fact/score/recommendation/decision to its origin: source URL + fetched_at, OR model + version + prompt_hash, OR human decision id.

**4. Agent I/O contract.** Each specialist is a pure-ish function over the Item with declared `inputs`, `outputs` (the ONLY fields it may write — enforced by a per-agent scoped Postgres role), `tools` (MCP servers/scopes it may call), `cost_budget` (LiteLLM virtual key), and `must_emit_receipt`.

**5. Approval contract.**
- **YES** → proceed with recommended action as-is.
- **NO** → terminate item, record reason, feed LEARN.
- **MODIFY** → human supplies altered params; re-enters at ACT with new provenance referencing the original.
- **HOLD** → park with a wake condition (time / new info); durable wait survives restart; TTL triggers re-notify/escalate.

---

## 5. What to ADOPT vs what must be CUSTOM

**Adopt off-the-shelf:** PostgreSQL, DBOS Transact, LangGraph/Pydantic AI, MCP SDKs, LiteLLM, Langfuse, Prometheus/Grafana/Alertmanager, OpenBao + SOPS, gVisor + (self-hosted) E2B, pgBackRest, Podman/systemd. (Optional/later: Twenty CRM, NATS JetStream/Debezium for fan-out.)

**Must be custom (this is the actual product — no off-the-shelf fit):**
1. The **Item schema + state machine** (canonical envelope and transitions).
2. The **Receipt + Provenance model** and the DB-level enforcement of the invariant (insert-only tables, revoked UPDATE/DELETE, outbox trigger).
3. The **normalization layer** (source-specific payload → canonical Item) — contract between 02 and everyone.
4. The **scoring/recommendation engine** (03's formulas, versioned, with confidence/uncertainty).
5. The **YES/NO/MODIFY/HOLD orchestration glue** + the approval notification UX.
6. The **LEARN loop** (outcome → score-model adjustment with provenance).
7. The **governance "panic" action** wiring LiteLLM + OpenBao + egress proxy + queue-drain into one atomic kill-switch.
8. **Agent I/O contract enforcement** (per-agent DB roles + output-field validation).

---

## 6. Candidate platforms (URLs · license · activity · strengths/weaknesses)

> Dense reference. "Activity" verified via web as of 2026-10-06; residual uncertainty marked UNKNOWN.

**Durable backbone / workflow**
- **DBOS Transact** — github.com/dbos-inc · MIT · active (TS/Python/Java/Go/Rust) · **+** library-only, Postgres-only infra, exactly-once steps, cron, durable queue, transactional step+state · **−** durability couples to app uptime (mitigate: systemd restart + health checks), fewer distributed features than Temporal. **ADOPT (default).**
- **Hatchet** — github.com/hatchet-dev/hatchet · MIT · active (Go engine; Py/TS/Go SDKs) · **+** Postgres-only, standalone engine + dashboard, durable queue/workflows/DAG · **−** smaller ecosystem than Temporal. **ADOPT (primary alternative).**
- **Temporal** — github.com/temporalio/temporal · MIT (server) · very active · **+** gold-standard guarantees, signals model HOLD/MODIFY natively · **−** multiple services + backing DB = heaviest solo ops. **CONSIDER (scale-out).**
- **Restate** — github.com/restatedev/restate · BSL 1.1 (→Apache after 4y); SDKs MIT · active · **+** single Rust binary, embedded storage, lowest ops · **−** not OSI. **CONSIDER.**
- **Inngest** — github.com/inngest/inngest · SSPL (→Apache after 3y); SDKs Apache-2.0 · active · **+** bundled event+cron+durability, great DX · **−** not OSI. **CONSIDER.**
- DAG schedulers (Airflow Apache-2.0 / Prefect Apache-2.0 / Dagster Apache-2.0) — wrong paradigm (batch DAGs, not per-step crash-resume). **AVOID** Airflow solo; Prefect only for scheduled data jobs. (FACT: Prefect announced acquiring Dagster Labs 2026-07-13.)

**Agent frameworks** — LangGraph (MIT, github.com/langchain-ai/langgraph, ~42k★, native checkpointers) **ADOPT**; Pydantic AI (MIT, native DBOS/Restate/Temporal integration) **ADOPT/CONSIDER**; CrewAI (MIT) consider for quick crews, not durability; OpenAI Agents SDK (MIT) thin loop, durability via engine; Microsoft Agent Framework (GA 1.0, Apr 2026; **UNKNOWN** exact SPDX) **CONSIDER only if .NET** — durability leans on Azure; AutoGen folded into MAF (maintenance) **AVOID new builds**.

**Database / vector** — PostgreSQL (PostgreSQL License) **ADOPT**; pgvector (+pgvectorscale) for memory; Qdrant (Apache-2.0) **CONSIDER later** if vector scale outgrows PG; SQLite/libSQL **AVOID** as primary (single-writer); DuckDB (MIT) **CONSIDER** for read-side analytics.

**Queue / broker** — prefer the engine's built-in queue (none separate). Standalone-if-needed: pgmq / River (MIT) / pg-boss (Postgres-only). Valkey+BullMQ (BSD/MIT) only for high-throughput fan-out; NATS JetStream (Apache-2.0) only for pub/sub+streaming. **AVOID** Kafka/RabbitMQ/Celery on one box.

**Event/provenance log** — Postgres append-only + outbox **ADOPT**; NATS JetStream (Apache-2.0) / Debezium (Apache-2.0) for later fan-out; **AVOID KurrentDB** (non-OSI Kurrent License v1) despite great semantics; **AVOID** Kafka/Redpanda overhead solo.

**CRM** — Twenty (AGPL-3.0, github.com/twentyhq/twenty, Postgres + GraphQL/REST + Metadata API) **CONSIDER as projection**; Odoo Community (LGPL-3.0, Postgres) ERP-breadth fallback; EspoCRM (GPL-3.0)/SuiteCRM (AGPL) MySQL/PHP **AVOID as primary**.

**Approval / HITL** — HumanLayer (Apache-2.0 SDK) ~~CONSIDER~~ **WITHDRAWN** (effectively deprecated per Agent 05; custom Telegram bot instead, ADR-0006); n8n (fair-code, not OSI) low-code waits **CONSIDER**; Temporal/Inngest/DBOS durable waits are the state machine.

**Cost gateway** — LiteLLM (MIT) **ADOPT**; Portkey Gateway (MIT since 2026-03, semantic caching + guardrails) **CONSIDER**; OpenRouter / Cloudflare AI Gateway (SaaS) only as upstreams behind your gateway, **AVOID** as control plane.

**Observability** — Langfuse (MIT core; acquired by ClickHouse Jan 2026, self-host unchanged; heavy: PG+ClickHouse+Redis+blob) **ADOPT**; Arize Phoenix (ELv2, OTel-native, Python, strong evals) **CONSIDER** (not OSI); Grafana/Prometheus stack **ADOPT** for infra; Helicone (acquired by Mintlify 2026-03, now maintenance mode) **AVOID new builds**.

**Secrets** — OpenBao (MPL-2.0, Vault-API-compatible, dynamic leased creds) **ADOPT**; SOPS (MPL-2.0) **ADOPT** as GitOps complement; Infisical (MIT open-core) **CONSIDER** if static-sync UX dominates; Vault (BSL) / Doppler (SaaS) **AVOID** for this design.

**Sandboxing** — gVisor (Apache-2.0) **ADOPT** baseline; self-hosted E2B (Apache-2.0, Firecracker) **ADOPT/CONSIDER** for model-gen code touching data/creds; Kata/Firecracker direct **CONSIDER**; bare Docker **not a security boundary**; Daytona went closed-source June 2026 **AVOID** for self-host.

**Protocols** — MCP (spec rev 2025-11-25, LF/AAIF, MIT SDKs) **ADOPT** now; A2A (v1.0, LF/AAIF) **DEFER** until external agent federation is real; AGNTCY **WATCH**.

**Backups** — pgBackRest (MIT, active, v2.59.0 Jul 2026) **ADOPT**; WAL-G **CONSIDER** if purely S3/MinIO; Barman **CONSIDER**.

---

## 7. Comparison Framework — reconciling conflicting recommendations from 02–07

Deterministic rubric. **Hard gate first:** any candidate that cannot emit receipts + provenance is rejected before scoring. Survivors scored 0–5 × weight; ties broken by the §0 priority order.

| Dimension | Weight |
|---|---|
| Provenance/auditability fit | ×3 |
| Safety & control (kill-switch, approval hooks, cost caps, least-privilege) | ×3 |
| Durability (crash-resume, idempotent) | ×2.5 |
| Single-operator ops burden | ×2 |
| Self-hostability & license (OSI-permissive preferred) | ×2 |
| Maintenance/activity (active, backed, not abandoned) | ×1.5 |
| Capability/fit | ×1.5 |
| Interop with our contracts | ×1.5 |
| Reversibility / exit cost | ×1 |

**Protocol:** (1) apply hard gate; (2) require FACT evidence, not assertion; (3) prefer one tool doing two jobs (operator-burden tiebreak); (4) if still tied, pick the more reversible option; (5) record every decision as an ADR tagged FACT / INFERENCE / RECOMMENDATION / UNKNOWN. *Worked example: the Temporal-vs-DBOS resolution in §1.*

---

## 8. Exact information required from Agents 02–07

All specialists return findings in FACT / INFERENCE / RECOMMENDATION / UNKNOWN and map to the contracts in §4.

- **02 — Discovery:** sources + access methods (APIs, licenses, rate limits, ToS/legality), expected volume/day, dedup keys, the `raw → normalized` field mapping they need, provenance each source provides, cost per source.
- **03 — Deal economics:** scoring dimensions + exact formulas, required input fields, valuation data sources, confidence/uncertainty model, "good" thresholds, how scores are versioned, what signal the LEARN loop should feed back.
- **04 — CRM / state:** entities + relationships to persist, build-in-Postgres vs Twenty recommendation, programmatic write API, how Item state syncs to the CRM projection, reporting needs, outcome-capture method.
- **05 — Governance / security:** approval policy matrix (what needs Michael vs auto-pilot), kill-switch/panic design, secrets handling, the cost-cap enforcement point, audit requirements, sandboxing policy, egress allow-list.
- **06 — Communications:** channels (email/Telegram/Slack), the YES/NO/MODIFY/HOLD notification UX, templates, rate/consent rules, how outbound emits receipts.
- **07 — Marketing:** campaign primitives, reversible vs irreversible actions, spend controls, attribution → OUTCOME feedback, content provenance.

**Required from ALL:** candidate tools (URL, license, activity), self-hostability, cost model, the exact Item fields they read/write, failure modes, and what they need from the shared backbone.

---

## 9. 24-Hour MVP path (thinnest vertical slice of the whole loop — round-one is design; this is the build plan)

Single box, one opportunity type, **all outbound actions mocked/dry-run** (round-one rule). Goal: prove the invariant and the loop end-to-end.
1. Postgres + DBOS up via Docker Compose; migrations for `items`, `receipts` (append-only), `provenance` (append-only), `approvals` (append-only), `outbox`.
2. One DBOS workflow implementing DISCOVER→NORMALIZE→RESEARCH(cheap)→SCORE(simple)→RECOMMEND→[approval wait]→ACT(dry-run, logs only)→RECEIPT.
3. One MCP tool server wrapping a single source from Agent 02 (read-only).
4. LiteLLM in front of all model calls with a **hard daily $ cap** + per-call max tokens.
5. Telegram (or Slack) bot delivering the recommendation and accepting YES/NO (MODIFY/HOLD stubbed).
6. Every transition writes receipt + provenance in the same transaction.

**MVP acceptance:** one opportunity flows end-to-end; a YES produces a dry-run receipt with a full provenance chain; killing the process mid-flow resumes cleanly.

## 9b. 1-Week path (harden toward real operation)
- Full append-only provenance + outbox; **all four** approval states incl. MODIFY re-entry and HOLD durable wait + TTL escalation.
- Langfuse tracing on every agent run; Prometheus+Grafana+Alertmanager with DLQ-depth and stuck-run alerts.
- OpenBao for secrets (short-lived scoped creds per agent); SOPS for bootstrap.
- gVisor runtime for all tool/code execution; default-deny egress proxy + controlled DNS; self-hosted E2B only for the model-gen-code path.
- pgBackRest PITR to off-box object storage + a tested restore drill.
- Integrate 2–3 real sources (02); CRM projection via Twenty (optional, read-model).
- LEARN loop writing outcome → score-model adjustment with provenance.
- Governance **panic** action (revoke creds + cut egress + drain queues, atomic).
- Per-agent scoped Postgres roles enforcing the Agent I/O contract for 02–07.

---

## 10. Acceptance Criteria (end-to-end, testable)

1. **Invariant enforced by DB, not discipline:** forcing a failure mid-action commits *both* receipt+action or *neither* — never an action without a receipt. (Insert-only tables; UPDATE/DELETE revoked.)
2. **Provenance completeness:** every receipt's `provenance_chain` resolves to a source URL+timestamp, a model+version+prompt_hash, or a human decision id — no orphans.
3. **Crash-resume / idempotency:** kill the process mid-workflow → restart resumes at the exact step, no duplicated side-effect.
4. **Approval correctness:** YES/NO/MODIFY/HOLD each produce the correct transition + an append-only decision row; HOLD survives restart and wakes on its condition; MODIFY re-enters ACT with new provenance referencing the original.
5. **Cost cap is real:** exceeding the budget blocks further LLM calls at the gateway (verified by test), independent of agent behavior.
6. **Kill-switch is real:** the panic action revokes creds, cuts egress, and drains queues; no in-flight external call can complete afterward.
7. **No unapproved outbound:** in round one, no real outbound side-effect occurs without a YES (all outbound mocked); verified by audit of receipts.
8. **Observability:** every agent run is traced with token + cost; DLQ-depth and stuck-run alerts fire in a drill.
9. **Restore drill:** a pgBackRest point-in-time restore to a fresh box succeeds from documented steps.

---

## 11. Integration Risks (and mitigations)

1. **License traps** — Restate (BSL), Inngest (SSPL), Twenty/SuiteCRM (AGPL), Phoenix (ELv2), Vault/Nomad (BSL), KurrentDB (KLv1). *Mitigation:* default to MIT/Apache/MPL core (DBOS, LiteLLM, Langfuse core, OpenBao all qualify); treat source-available tools as deliberate, documented exceptions.
2. **Two-sources-of-truth** if a CRM becomes authoritative. *Mitigation:* Postgres is system-of-record; CRM is a projection synced from the event log.
3. **OTel GenAI semconv is unstable** (FACT: still "Development"). *Mitigation:* emit OTLP but abstract `gen_ai.*` attribute names; don't hard-code dashboards/alerts to them.
4. **MCP spec churn.** *Mitigation:* pin to rev 2025-11-25.
5. **HOLD backlog / approval latency.** *Mitigation:* TTL + escalation on every HOLD; a visible queue.
6. **Agent writes outside its lane.** *Mitigation:* per-agent scoped Postgres roles + output-field validation in the contract layer.
7. **Cost runaway before cap reset** (FACT: LiteLLM reset check ~every 10 min). *Mitigation:* conservative caps + rate limits + per-call max-tokens + a hard circuit-breaker.
8. **Prompt injection → excessive agency** (FACT: OWASP LLM #1 and #3 in 2026). *Mitigation:* authorization outside the model, least-privilege tools, out-of-band approval for consequential actions.
9. **DBOS durability couples to app uptime.** *Mitigation:* systemd `Restart=on-failure` + health checks; upgrade to Hatchet (out-of-process) if this bites.
10. **Single-server SPOF.** *Mitigation:* off-box backups + tested restore; accept SPOF in round one, revisit for HA later.
11. **Seven agents recommending conflicting tools.** *Mitigation:* the §7 comparison framework; Agent 01 owns the final ADR.

---

## 12. Open UNKNOWNs to resolve in round two
- Primary implementation language (Python favored by LiteLLM/DBOS/Pydantic AI; TS also viable). Needs a decision before the MVP.
- Microsoft Agent Framework exact SPDX (if .NET ever considered).
- Whether the workload volume ever justifies a standalone broker (NATS) or Qdrant over pgvector.
- Whether to run Twenty at all, or keep business-state Postgres-only with a thin custom UI.
- Exact approval policy matrix (what is auto-pilot vs human-only) — owned by Agent 05.
```
