# Global ADR Registry — Michael Business OS

Maintained by Agent 01. Last updated: 2026-10-07 (round-two integration review).

## Numbering rule
- **System ADRs** are `ADR-00NN`. Only Agent 01 issues them, on branch `research/agent-01-coordinator`.
- **Specialist ADRs keep their original filenames** on their own branches and are cited here by alias: `ADR-<agent>-<their number>`. For example, Agent 05's `ADR-001-governance-control-plane.md` is **ADR-05-001**.
- This resolves the collisions between 01/04/07's ADR-0001 and 03/05/06's ADR-001.
- Specialists don't need to rename files. New specialist ADRs should use `ADR-<agent>-NNN-<slug>.md`.

Dispositions:
- **ACCEPTED**: adopted as written.
- **ACCEPTED-WITH-CHANGES**: adopted; the listed changes are binding.
- **SUPERSEDED**: replaced by the named system ADR.
- **PENDING-MICHAEL**: needs his decision.

The executive synthesis is `docs/research/ROUND_ONE_SYNTHESIS.md`. The ADRs below record the same decisions, plus the contract freeze, as individual, citable records.

## System ADRs (Agent 01)
| ADR | Title | Status |
|---|---|---|
| ADR-0001 | PostgreSQL as single system-of-record spine | ACCEPTED |
| ADR-0002 | DBOS Transact durable backbone (Temporal = scale-out) | ACCEPTED |
| ADR-0003 | MCP tool boundary; A2A deferred | ACCEPTED |
| ADR-0004 | Unified contracts (Item v1, ActionRequest, Approval, Receipt, Provenance, Outcome) | ACCEPTED (frozen v1.0.0) |
| ADR-0005 | Governance control plane: Action Gateway + PDP + guard, merged PANIC, two spend ledgers | ACCEPTED; cash limits = MICHAEL_DECISIONS #1 |
| ADR-0006 | Integration roles: CRM projection, n8n edge-only, one comms subsystem, Operator UI approvals | ACCEPTED |
| ADR-0007 | Business scope: flips + services | ACCEPTED (Michael decision) |
| ADR-0008 | Implementation language: Python | ACCEPTED (technical; per synthesis) |
| ADR-0009 | Contracts v1.1.0 change set | **PROPOSED**: v1.0.0 stays in force (item 1 moved to ADR-0010) |
| ADR-0014 | Bounded workers, model routing (Sonnet/Opus/Fable) and usage telemetry; Agent 01 the only persistent session (Aria 1945) | **ACCEPTED** |
| ADR-0013 | Deal Sniffer product direction: mission engine now, marketplace seams later (owner package, Aria 2026-10-07) | **ACCEPTED** (scope + seams only) |
| ADR-0012 | No universal absolute-profit floor; capital-velocity scoring; deal classes as data (owner rule, Aria 2026-10-07) | **ACCEPTED**; implementation C-19 |
| ADR-0011 | Deal Sniffer opportunity card (derived view; UNKNOWN-not-guess; recommendation vocabulary; activity trail; logistics profile) | **ACCEPTED**; enrichment contract change PROPOSED (ADR-0009 items 10–11) |
| ADR-0010 | MBOS-CJSON-1 canonical JSON (RFC 8785 profile) + MBOS-RH-1 receipt hash; Agent 04 sole ledger owner | **ACCEPTED** (F-13/F-14) |

## Specialist ADRs
| Alias | Branch file | Title | Disposition | Binding changes / notes |
|---|---|---|---|---|
| ADR-02-0201 | agent-02 `ADR-0201-normalized-opportunity-schema.md` | Normalized opportunity schema | **ACCEPTED-WITH-CHANGES** | Becomes `Item.normalized` + `Item.sources[]` (ADR-0004). `source` becomes an array. `valuation`/`score` are removed (03 owns them). Stored in Postgres, not SQLite. |
| ADR-02-0202 | agent-02 `ADR-0202-source-access-tiering-and-legal-posture.md` | Source-access tiering and legal posture | **ACCEPTED** | The tiering and the do-not-automate list are binding for all collectors. Internal-endpoint use on gov-surplus sites is **PENDING-MICHAEL** (P2). The per-source kill switch becomes an L2 capability freeze (ADR-0005). |
| ADR-03-001 | agent-03 `ADR-001-economics-scoring-engine.md` | Economics and scoring engine | **ACCEPTED-WITH-CHANGES** | Fix §17.1 vs §12.4 (the AT-14 contradiction). Add the missing formula inputs to the schema. Add `inputs_hash` and `scorecard_id`. Thresholds ($/hr, caps) are **PENDING-MICHAEL** (P1). `scoring-config.json` is the single source for per-mile cost. |
| ADR-04-0001 | agent-04 `ADR-0001-durable-state-architecture.md` | Durable state architecture | **ACCEPTED-WITH-CHANGES** | Adopt Receipt v1 field names, prefixed-ULID public IDs and a `seq` chain. Workflow resume position is owned by DBOS, not by custom tables. Add DDL for `approvals`, `outcomes` and `lessons`. |
| ADR-05-001 | agent-05 `ADR-001-governance-control-plane.md` | Governance control plane | **ACCEPTED-WITH-CHANGES** → ADR-0005 | Merged PANIC (egress cut, queue drain, LiteLLM budget zeroed). An 8th guard check forces dry-run. |
| ADR-05-002 | agent-05 `ADR-002-governance-tech-stack.md` | Governance tech stack | **PARTIALLY SUPERSEDED** by ADR-0002/0005 | Temporal becomes DBOS. Biscuit and SPIFFE are deferred. The PDP starts as a policy table behind an OPA/Cedar-compatible interface. OpenBao is accepted; Vault (BUSL) is rejected. |
| ADR-06-001 | agent-06 `ADR-001-communications-architecture.md` | Communications architecture (hosted-first hybrid) | **ACCEPTED** | Vapi/Retell + Telnyx with Postmark. Generalize beyond used cars (ADR-0007). **Any live outbound is PENDING-MICHAEL** (legal counsel, EIN; P2). |
| ADR-06-002 | agent-06 `ADR-002-approval-gate-and-receipts.md` | Approval gate and receipts | **ACCEPTED-WITH-CHANGES** → ADR-0004/0005 | Add HOLD. The comms receipt becomes `Receipt.details{kind:"comms"}`. Add `inputs_hash` and `idempotency_key`. |
| ADR-07-0001 | agent-07 `ADR-0001-automation-orchestration-hub.md` | n8n automation hub | **SUPERSEDED** by ADR-0006 | n8n is an optional connector only, never the orchestrator. |
| ADR-07-0002 | agent-07 `ADR-0002-crm-selection.md` | CRM selection | **ACCEPTED-WITH-CHANGES** → ADR-0006 | Twenty is a one-way projection. Postgres holds the lead, attribution and system of record. |

## Round-two specialist ADRs (reviewed 2026-10-07; rulings in `docs/integration/ROUND_TWO_INTEGRATION.md`)
| Alias | Title | Disposition | Binding changes / notes |
|---|---|---|---|
| ADR-03-002 | Engine v0.1.0, C14 resolution, formula clarifications | **ACCEPTED-WITH-CHANGES** | The C14 resolution is accepted (rule kept, AT-14 corrected). The wider `inputs_hash` scope is accepted and goes into the contract via ADR-0009. The v1.1.0 schemas must get versioned `$id`s before re-vendoring. |
| ADR-05-003 | Wave-one gateway implementation, plus contract requests R1–R3 | **ACCEPTED-WITH-CHANGES** | Store and panic state move to Postgres (R2, R4, R5). Contract requests are folded into ADR-0009; canonical hashing is ruled now (R3). |
| ADR-06-003 | Operator UI on stdlib | **ACCEPTED-WITH-CHANGES** | Integration R10: drop the UI-side gateway, ticker and SQLite store; call `spine.decide`. |
| (04 schema) | Durable state migrations 0001–0004 | **ACCEPTED as canonical DDL** (R1) | Add the R1 tables in 0005. Payload hashes are not computed with `jsonb::text` (R3). |
