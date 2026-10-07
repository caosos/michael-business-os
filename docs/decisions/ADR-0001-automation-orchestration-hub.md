# Decision

Status: PROPOSED

## Context
The marketing subsystem needs a workflow engine to orchestrate: inbound-lead → CRM, post-job → review-request, new-review → draft-reply, social-post scheduling, and attribution pulls. This likely overlaps with system-wide orchestration/durable-workflow choices owned by Agent 01 (coordinator) and sending infra owned by Agent 06 (communications), so it needs cross-agent reconciliation rather than a unilateral marketing pick.

## Options considered
- **n8n** — Sustainable Use License (fair-code; free for own-business use, no reselling; not OSI). ~207k★, v2.43.x, very active. Richest connector + webhook + AI node library. **[FACT]**
- **Activepieces** — MIT (cleanest license), ~22–24k★, active. Fewer connectors than n8n. **[FACT]**
- **Windmill** — AGPL-3.0; code-first, powerful but developer-heavy. **[FACT]**
- **Node-RED** — Apache-2.0; best for smart-home/IoT device wiring, weaker on business-SaaS connectors. **[FACT]**
- **Huginn / Automatisch** — MIT / AGPL; narrower or slower-cadence. **[FACT]**

## Recommendation
Adopt **n8n** as the marketing automation hub for its connector breadth (GBP, Meta, email, Sheets, HTTP/webhook) and active maintenance. Fall back to **Activepieces** if the project requires a strictly OSI-approved license. Reserve **Node-RED** only if smart-home hardware scripting is ever needed.

## Evidence
- github.com/n8n-io/n8n ; n8n Sustainable Use License (since Mar 2022): free self-host for internal/commercial use, no reselling as SaaS.
- github.com/activepieces/activepieces (MIT).
- Research detail and sources: `docs/research/agent-07-marketing.md` §4.
- Receipt: `docs/receipts/2026-10-06-marketing-research.md`.

## Risks
- **License (fair-code):** n8n may not be redistributed/resold as a hosted service — fine for running Michael's own business, but constrains any future productization. **[FACT]**
- **Overlap/duplication:** if Agent 01 selects a different durable-workflow engine (e.g. Temporal) for the core OS, running n8n too may duplicate orchestration. Reconciliation needed.
- **Self-host ops burden:** one more service to run/secure (coordinate secrets handling with Agent 05).

## Reversibility
Moderate. Workflows are portable in concept but not 1:1 between engines; migrating built flows is real effort. Keeping flows thin (n8n as glue, logic in the OS) reduces lock-in.

## Coordinator review required: YES
