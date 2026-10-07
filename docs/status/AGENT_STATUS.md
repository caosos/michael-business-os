# Agent Status

Agent: 01
Role: Chief Coordinator / Systems Architect
Branch: research/agent-01-coordinator
Worktree: /home/michaelos/business-os-worktrees/agent-01-coordinator
State: WAITING
Current phase: Round-One research deliverable COMPLETE and pushed; coordinator reconciliation WAITING on Agents 02–07 to publish status
Started: 2026-10-06
Last updated: 2026-10-06

## Current objective
Stand up the GitHub coordination layer (status, dashboard, ADRs, receipts) and keep the master dashboard (`docs/status/ALL_AGENTS.md`) synced from the other agents' branches.

## Completed
- Comprehensive Round-One architecture research across 17 technology categories via 3 parallel research streams (orchestration/execution, integration/data, cross-cutting ops), ~50 candidate platforms, web-verified licenses/activity as of 2026-10-06.
- Final research deliverable written: `docs/research/agent-01-coordinator.md` (recommended architecture, textual diagram, candidate platforms w/ URLs+licenses+activity, adopt-vs-custom, 5 stable interface contracts, comparison framework, info required from 02–07, 24h MVP + 1-week paths, acceptance criteria, integration risks).
- Resolved the one cross-stream tension (Temporal vs DBOS) using the comparison framework → DBOS.
- Established coordination structure: docs/status, docs/research, docs/decisions, docs/receipts.
- Authored ADR-0001 (Postgres spine), ADR-0002 (DBOS durable backbone), ADR-0003 (MCP tool boundary / A2A deferred) — all PROPOSED, pending cross-agent review.
- Created master dashboard `docs/status/ALL_AGENTS.md`.

## Findings
- **The one idea:** Postgres is the spine; the receipt + the state change commit in the SAME transaction → "no action without a receipt, no receipt without provenance" is DB-enforced, not discipline.
- **Recommended stack (provisional):** Podman+systemd · PostgreSQL · DBOS Transact (MIT, Postgres-only durable backbone) · LangGraph/Pydantic AI · MCP tool boundary · Postgres append-only + outbox provenance log · business-state in Postgres (+ Twenty optional projection) · DBOS durable waits for YES/NO/MODIFY/HOLD · LiteLLM cost gateway + spend kill-switch · Langfuse + Prometheus/Grafana · OpenBao + SOPS secrets · gVisor + self-hosted E2B + egress proxy · pgBackRest backups.
- **License discipline is a live risk:** several strong tools are source-available, NOT OSI — Restate (BSL), Inngest (SSPL), Twenty/SuiteCRM (AGPL), Arize Phoenix (ELv2), Vault/Nomad (BSL), KurrentDB (KLv1). Recommended core (DBOS, LiteLLM, Langfuse core, OpenBao) is MIT/Apache/MPL.
- **FACT:** MCP spec rev 2025-11-25, under Linux Foundation AAIF; A2A v1.0 (also AAIF). OWASP LLM 2026: prompt injection #1, excessive agency #3. OTel GenAI semconv still "Development"/unstable.
- Full FACT/INFERENCE/RECOMMENDATION/UNKNOWN detail in the research file.

## Decisions made
- DBOS Transact over Temporal/Hatchet as durable backbone (ADR-0002) — PROPOSED.
- PostgreSQL as single system-of-record spine (ADR-0001) — PROPOSED.
- MCP now as tool boundary; A2A deferred until external agent federation is real (ADR-0003) — PROPOSED.
- Business-state as system-of-record in Postgres; any CRM is a read-model projection.
(Nothing marked ACCEPTED — awaiting cross-agent review per protocol.)

## Unknowns
- Primary implementation language (Python favored by LiteLLM/DBOS/Pydantic AI; TS viable) — blocks MVP; candidate Michael decision.
- Whether workload volume ever justifies a standalone broker (NATS) or Qdrant over pgvector.
- Whether to run Twenty CRM at all vs Postgres-only + thin custom UI.
- Exact approval policy matrix (auto-pilot vs human-only) — owned by Agent 05.
- Microsoft Agent Framework exact SPDX license.

## Blockers
None currently.

## Needs Michael decision
- Primary implementation language for the build (Python vs TypeScript). Recommendation: Python. Not urgent until Round Two build begins.

## Needs coordinator review
(This is me.) Pending: reconcile 02–07 recommendations against the comparison framework once they report; ratify or revise ADRs 0001–0003 after cross-agent review.

## Files produced
- docs/research/agent-01-coordinator.md
- docs/status/AGENT_STATUS.md
- docs/status/ALL_AGENTS.md
- docs/decisions/ADR-0001-postgres-spine.md
- docs/decisions/ADR-0002-dbos-durable-backbone.md
- docs/decisions/ADR-0003-mcp-tool-boundary.md
- docs/receipts/2026-10-06-round-one-research.md

## Next action
Coordination scaffold committed and pushed (branch research/agent-01-coordinator, remote origin). Next: on resume, refresh `docs/status/ALL_AGENTS.md` by reading each `research/agent-0X-*` branch's `docs/status/AGENT_STATUS.md`; run any new 02–07 recommendations through the comparison framework; ratify/revise ADR-0001/0002/0003 after cross-agent review. As of this update all peers = NO REPORT (still at initial commit 2e60f38).
