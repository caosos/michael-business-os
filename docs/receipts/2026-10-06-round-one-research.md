# Receipt — Round-One Architecture Research

- Timestamp: 2026-10-06
- Agent: 01 (Coordinator / Architect)
- Related output: `docs/research/agent-01-coordinator.md`, ADR-0001/0002/0003
- Confidence: Medium-High on recommendations; license/activity FACTs web-verified as of 2026-10-06 but version/star counts are point-in-time and may drift.

## What was done
Three parallel research sweeps across 17 technology categories (~50 candidate platforms). Each candidate labeled FACT / INFERENCE / RECOMMENDATION / UNKNOWN. Method: web search + source fetch to verify license (SPDX), maintenance/activity, and self-hostability.

## Stream A — Orchestration & Execution
- Checked: multi-agent frameworks (LangGraph, CrewAI, OpenAI Agents SDK, Pydantic AI, MS Agent Framework, AutoGen/AG2, Google ADK, LlamaIndex, Mastra), durable engines (Temporal, Restate, Inngest, Hatchet, DBOS, Trigger.dev, Airflow/Prefect/Dagster, Windmill), queues (pgmq, River, pg-boss, BullMQ/Valkey, NATS, RabbitMQ, Kafka, Celery), schedulers, containers (Docker Compose, Podman/Quadlet, k3s, Nomad, systemd).
- Key observations: DBOS/Hatchet = MIT + Postgres-only durable backbones; Restate BSL; Inngest SSPL; Temporal heavy to run solo; LangGraph native checkpointers; Podman+systemd best single-box runtime; k3s/Nomad overkill (Nomad BSL).
- Representative sources: github.com/dbos-inc, github.com/hatchet-dev/hatchet, github.com/temporalio/temporal, github.com/restatedev/restate, github.com/inngest/inngest, github.com/langchain-ai/langgraph, Podman-vs-Docker 2026 writeups. (Full list: research file §6 + Stream A sources.)

## Stream B — Integration & Data
- Checked: MCP (spec 2025-11-25, SDKs, auth, AAIF), A2A/ACP/AGNTCY, Postgres (+pgvector/pgvectorscale/pgmq/pg_cron), SQLite/libSQL/DuckDB, Qdrant, event logs (Postgres outbox, Kafka, Redpanda, NATS JetStream, KurrentDB, Debezium), CRMs (Twenty, EspoCRM, SuiteCRM, Odoo, ERPNext), approvals (Temporal signals, Inngest waits, HumanLayer, n8n).
- Key observations: Postgres-as-spine + transactional outbox uniquely satisfies the atomic-receipt invariant; KurrentDB non-OSI (KLv1); Twenty AGPL (best packaged CRM, use as projection); MCP de-facto standard; A2A deferrable.
- Representative sources: modelcontextprotocol.io/specification/2025-11-25, github.com/modelcontextprotocol, a2a-protocol.org, github.com/twentyhq/twenty, tigerdata pgvector-vs-qdrant, kurrent.io license notes, Temporal/Inngest/HumanLayer HITL docs.

## Stream C — Cross-cutting Ops
- Checked: observability (OTel GenAI semconv, Langfuse, Arize Phoenix, Grafana/Prometheus, Helicone), cost gateways (LiteLLM, Portkey, OpenRouter, Cloudflare AI Gateway), secrets (OpenBao, Vault, Infisical, SOPS, Doppler), sandboxing (gVisor, Firecracker, Kata, E2B, Daytona), backups (pgBackRest, Barman, WAL-G), DLQ/resilience patterns, kill-switch/guardrail posture (OWASP LLM Top 10 2026).
- Key observations: Langfuse MIT core (acquired by ClickHouse Jan 2026); LiteLLM MIT hard spend caps enforced at proxy; OpenBao MPL-2.0 dynamic creds; gVisor baseline + E2B Firecracker for model-gen code; Helicone in maintenance mode (avoid); Daytona closed-source June 2026 (avoid); kill-switch is a composed pattern, no turnkey OSS suite verified (UNKNOWN).
- Representative sources: langfuse.com + github.com/langfuse/langfuse, litellm.ai, openbao.ch, northflank/amux sandboxing guides, OWASP LLM Top 10 2026, pgBackRest release notes.

## Uncertainty / UNKNOWN
- OTel GenAI semantic conventions still "Development" (unstable) — attribute names may change.
- No dominant turnkey OSS "agent-governance kill-switch" suite verified — must be composed.
- Microsoft Agent Framework exact SPDX unconfirmed.
- Point-in-time star/version counts may have drifted since 2026-10-06.
- Real workload volume (determines whether pgmq/pgvector suffice vs standalone broker/Qdrant) is unknown until Agent 02 reports source volumes.
