# Decision

ADR-0003 — MCP as the authenticated tool boundary; A2A deferred

Status: ACCEPTED (2026-10-06, Agent 01, after cross-agent reconciliation — see "Ratification" below)

## Context
Agents must call tools (sources, comms, CRM writes, LLM) through a boundary that is standard, authenticatable, and whose identity/scope can be recorded as provenance on every receipt. We must also decide whether to adopt an agent-to-agent protocol now.

## Options considered
- **MCP (Model Context Protocol)** as the tool/capability layer (stdio for co-located tools, Streamable HTTP across trust boundaries; OAuth 2.x resource-server auth).
- **A2A (Agent2Agent)** for inter-agent communication now vs. later.
- Ad-hoc custom tool interfaces (no standard).

## Recommendation
Adopt **MCP now** as the authenticated tool boundary; pin to spec rev **2025-11-25**. Record MCP server identity + OAuth scope as part of each receipt's provenance. **Defer A2A** until we actually need to expose/consume external third-party agents — internal sub-agents use plain calls + the durable engine. Watch AGNTCY (identity/discovery).

## Evidence
- FACT: MCP spec rev 2025-11-25; official TS/Python SDKs (MIT); stdio + Streamable HTTP; OAuth 2.x resource-server model with Resource Indicators (RFC 8707); now under Linux Foundation AAIF.
- FACT: A2A v1.0, Linux Foundation/AAIF; ACP effectively absorbed into A2A. Mature enough to adopt later at low risk.
- INFERENCE: On a single server with one orchestrator + in-process sub-agents, A2A's cross-org federation value is largely unused; MCP's scoped-tool model maps cleanly onto "every tool call is an authenticated, scoped, provenanced action."
- Full detail: `docs/research/agent-01-coordinator.md` §1, §6.

## Risks
- MCP spec churn (mitigate: pin the revision).
- Prompt injection → excessive agency via tools (OWASP #1/#3 2026) — mitigate with least-privilege tool scoping + out-of-band approval for consequential actions (cross-refs ADR work by Agent 05).

## Reversibility
High. MCP is an interface boundary; A2A can be layered on later without disturbing MCP.

Coordinator review required: YES (needs input from 06 communications tools, 02 source access).

## Ratification (2026-10-06, round-one reconciliation)
- **Agreements:** 04 (a custom MCP server is the only write path), 05 (agents hold no credentials; tools are mediated), and 06 (one Business-OS MCP server; Telnyx ships an official MCP server).
- **Refinement:** every MCP tool that causes an external side effect goes through the **Action Gateway** (ADR-0005). An MCP call can create an ActionRequest, but only the gateway's execution guard can run an effector.
- **Avoid:** Anthropic's archived SQLite MCP server (unpatched SQL injection, per 04 FACT). Postgres MCP Pro (MIT) is allowed for read/admin only, never for agent writes.
- A2A stays deferred.
