# Michael Business OS — Agent Dashboard

Last updated: 2026-10-06 (by Agent 01)

> Source of truth: each agent's `docs/status/AGENT_STATUS.md` on its `research/agent-XX-*` branch. Agent 01 refreshes this table by reading those branches. "NO REPORT" = that agent has not yet committed/pushed a status file (verified: all of 02–07 are still at the initial commit `2e60f38` with no `docs/` committed as of this update). Progress is never invented.

| Agent | Role | State | Current objective | Last update | Blocker | Deliverable |
|---|---|---|---|---|---|---|
| 01 | Coordinator / Architect | WAITING | Research deliverable complete; awaiting 02–07 status to reconcile | 2026-10-06 | none (waiting on peers) | `docs/research/agent-01-coordinator.md` (complete, pushed) |
| 02 | Opportunity Discovery | NO REPORT | — | — | — | — |
| 03 | Economics / Scoring | NO REPORT | — | — | — | — |
| 04 | CRM / State | NO REPORT | — | — | — | — |
| 05 | Governance / Security | NO REPORT | — | — | — | — |
| 06 | Communications | NO REPORT | — | — | — | — |
| 07 | Marketing | NO REPORT | — | — | — | — |

## Cross-Agent Conflicts
None yet (02–07 have not reported). One intra-coordinator tension was already resolved: durable backbone **Temporal vs DBOS/Hatchet** → DBOS (see ADR-0002). Conflicts will be scored through the comparison framework in `docs/research/agent-01-coordinator.md` §7.

## Shared Decisions Pending
- ADR-0001 Postgres spine — PROPOSED, needs cross-agent review (esp. 03 scoring storage, 04 CRM/state).
- ADR-0002 DBOS durable backbone — PROPOSED, needs 05 (governance hooks) + 06 (approval waits) review.
- ADR-0003 MCP tool boundary / A2A deferred — PROPOSED, needs 06 + 02 (tool/source access) review.
- Primary implementation language (Python vs TS) — affects every agent's tool/code choices.

## Michael Decisions Needed
- **Primary implementation language** (recommend Python). Not urgent until Round-Two build. Low interrupt priority.

## Integration Risks
1. License traps — source-available (not OSI) tools: Restate/BSL, Inngest/SSPL, Twenty/AGPL, Phoenix/ELv2, Vault+Nomad/BSL, KurrentDB/KLv1. Mitigation: MIT/Apache/MPL core.
2. Two-sources-of-truth if a CRM becomes authoritative. Mitigation: Postgres is system-of-record; CRM is a projection.
3. OTel GenAI semconv unstable → abstract attribute names.
4. HOLD backlog / approval latency → TTL + escalation.
5. Cost runaway before cap reset (LiteLLM ~10 min) → conservative caps + rate limits + per-call token cap.
6. Prompt injection → excessive agency (OWASP #1/#3 2026) → authorization outside the model + least privilege.
7. Single-server SPOF → off-box backups + tested restore.
(Full list with mitigations: `docs/research/agent-01-coordinator.md` §11.)

## Current Recommended Direction
**PROVISIONAL until 02–07 research lands and cross-agent review completes.**

Postgres as the spine, with the receipt + state change committed atomically (the governance invariant made mechanical). DBOS Transact as the Postgres-native durable backbone running the DISCOVER→…→LEARN state machine; LangGraph/Pydantic AI for agent reasoning; MCP as the authenticated tool boundary; LiteLLM as the cost gateway + spend kill-switch; Langfuse + Prometheus/Grafana for observability; OpenBao + SOPS for secrets; gVisor + self-hosted E2B + default-deny egress for sandboxing; pgBackRest for backups. Governance = a composed, model-unmodifiable control plane with one atomic PANIC action (revoke creds + cut egress + drain queues).
