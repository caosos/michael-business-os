# Decision

ADR-0002 — DBOS Transact as the durable workflow backbone

Status: ACCEPTED (2026-10-06, Agent 01, after cross-agent reconciliation — see "Ratification" below)

## Context
The core flow (DISCOVER→NORMALIZE→RESEARCH→SCORE→RECOMMEND→[APPROVAL]→ACT→RECEIPT→OUTCOME→LEARN) must survive crashes/restarts while Michael sleeps, retry idempotently, schedule recurring work, and support indefinite human-approval waits (HOLD). One operator must be able to run it.

## Options considered
- **DBOS Transact** — MIT library; durability lives in Postgres (the spine); workflows/queue/cron/exactly-once steps/durable messaging; runs in-process.
- **Hatchet** — MIT; Postgres-only standalone engine + dashboard.
- **Temporal** — MIT server; gold-standard guarantees; but multiple services + backing DB.
- **Restate** (BSL) / **Inngest** (SSPL) — single-binary / bundled, but source-available, not OSI.
- DAG schedulers (Airflow/Prefect/Dagster) — wrong paradigm (batch DAGs, not per-step crash-resume).

## Recommendation
Adopt **DBOS Transact** as the durable backbone. Rationale from the comparison framework (research §7): all clear the provenance hard-gate; DBOS wins on single-operator ops burden and — decisively — keeps workflow state in the SAME Postgres transaction as the receipt, so a step and its receipt commit atomically. **Hatchet** is the primary alternative (out-of-process engine + dashboard) if we want workflow state to survive a hard app crash independently. **Temporal** is the documented scale-out option if we outgrow one box.

## Evidence
- FACT: DBOS Transact MIT, Postgres-only, exactly-once steps, durable queue + cron + messaging, TS/Python. Hatchet MIT, Postgres-only. Temporal MIT server but multi-service. Restate BSL; Inngest SSPL.
- INFERENCE: DBOS's transactional step+state is a near-perfect fit for the receipt/provenance invariant and the leanest footprint (app + Postgres only).
- Full detail + scoring: `docs/research/agent-01-coordinator.md` §1 (worked example), §6.

## Risks
- DBOS durability couples to app-process uptime (mitigate: systemd `Restart=on-failure` + health checks; upgrade to Hatchet if this bites).
- Smaller ecosystem/company than Temporal.

## Reversibility
High-ish. The core flow is expressed as our own state machine over the Item; Pydantic AI integrates with DBOS/Restate/Temporal, so swapping engines later is contained if we keep the state machine engine-agnostic.

Coordinator review required: YES (needs input from 05 governance hooks, 06 approval-wait UX).

## Ratification (2026-10-06, round-one reconciliation)
**Conflict C2.** Agent 05 (ADR-05-002) recommended Temporal, or LangGraph if in-process. Agents 02 and 07 named n8n as the "backbone". Scored with the §7 rubric (integration doc §3):

| Option | Weighted score | Hard gate |
|---|---|---|
| DBOS | **81.5 / 90** | passes |
| Temporal | 74.5 / 90 | passes |
| n8n | 51.0 / 90 | **fails as system of record**: workflow state and credentials live outside the receipt transaction, and its license is fair-code, not OSI |

- Agent 05 marked DBOS's license "UNKNOWN [verify]". FACT: DBOS Transact is MIT (github.com/dbos-inc/dbos-transact-py).
- Agent 05's own warning applies: LangGraph `interrupt()` resume re-runs the node from the top. **Approval waits therefore live in DBOS durable waits (recv/send), never in LangGraph interrupts.** LangGraph/Pydantic AI stays inside a single reasoning step.
- 05's reasoning that "changing the substrate later is the most expensive swap" is accepted. That is why the Item and ActionRequest state machines are defined in our contracts (ADR-0004) and not in engine primitives. Temporal remains the documented scale-out path.
- n8n is demoted to an optional connector (ADR-0006).
