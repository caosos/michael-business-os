# Michael Business OS — Agent Dashboard

Last updated: 2026-10-07 (Aria reconciliation + Agent 01 contract freeze)

> Source of truth: each agent's `docs/status/AGENT_STATUS.md` on its own `research/agent-XX-*` branch.

| Agent | Role | State | Current objective | Blocker | Deliverable |
|---|---|---|---|---|---|
| 01 | Coordinator / Architect | COMPLETE | Round-One research + reconciliation complete; contracts frozen v1.0.0 | none | `docs/research/agent-01-coordinator.md`, `docs/research/ROUND_ONE_SYNTHESIS.md`, `docs/research/agent-01-integration.md`, `docs/research/contracts/`, `docs/decisions/INDEX.md` |
| 02 | Opportunity Discovery | COMPLETE | Await Round-Two implementation gate | none | `docs/research/agent-02-opportunity.md` |
| 03 | Economics / Scoring | COMPLETE | Await threshold calibration + implementation gate | none | `docs/research/agent-03-economics.md` |
| 04 | CRM / State | COMPLETE | Await coordinator state-model decision | none | `docs/research/agent-04-state.md` |
| 05 | Governance / Security | COMPLETE | Await policy values + implementation gate | none | `docs/research/agent-05-governance.md` |
| 06 | Communications | COMPLETE | Await legal/architecture gate before live comms | none | `docs/research/agent-06-communications.md` |
| 07 | Marketing | COMPLETE | Await Round-Two implementation gate | none | `docs/research/agent-07-marketing.md` |

## Cross-Agent Conflicts — reconciled

1. **DBOS vs Temporal**
   - Decision: **DBOS for MVP / single-operator deployment; Temporal deferred as scale-out option.**
   - Reason: same-Postgres durability and materially lower operator burden fit the current single-box requirement better. Governance semantics are engine-independent.

2. **Postgres source-of-truth vs CRM as primary**
   - Decision: **Postgres is authoritative. No CRM is authoritative.**
   - A CRM/UI may be added later as a projection if it clearly improves operator workflow.

3. **Core orchestration vs n8n**
   - Decision: **n8n is not the core runtime.**
   - It may be used later at the marketing/integration edge for reversible workflows. Core state transitions remain in the durable application workflow.

4. **Receipt/provenance ownership**
   - Decision: **one project-wide receipt/provenance schema in Postgres.**
   - Specialist-specific receipts extend the shared schema; they do not create separate ledgers.

5. **Communications ownership vs marketing**
   - Decision: **one communications service owns email/SMS/voice delivery.**
   - Marketing requests communication actions through that service; it does not own separate send infrastructure.

6. **Opportunity schema vs economics/state schemas**
   - Decision: **single canonical Opportunity envelope with typed economic and state extensions.**
   - Discovery owns source/raw fields; Economics owns scorecard fields; State owns durable IDs/history; all versioned.

7. **Business scope** (Agent 06: used cars; Agent 07: home services)
   - Decision (Michael): **both value-add FLIPS and paid SERVICES**, under one Item model with type-specific fields. Neither lane narrows the system (ADR-0007).

8. **Receipt shape, IDs and verdict vocabulary** (01/04/05/06)
   - Decision: one Receipt v1 that records lifecycle events (05), stored insert-only and hash-chained (04) in the same transaction as the state change (01).
   - IDs: prefixed-ULID public IDs.
   - Vocabularies: `recommendation.verdict` is YES/MAYBE/PASS (machine); `approval.decision` is YES/NO/MODIFY/HOLD (Michael).
   - See ADR-0004 and `docs/research/contracts/`.

9. **Kill switch and spend** (01 PANIC vs 05's 3-level freeze)
   - Decision: merged L1 agent / L2 capability / L3 global. L3 freezes, revokes credentials, cuts egress, zeroes LLM budgets and cancels queued work. It fails closed.
   - Two spend ledgers: LiteLLM for LLM spend, 05's budget ledger for real-world spend (ADR-0005).

The full register is C1–C17 with weighted rubric scores (`docs/research/agent-01-integration.md` §3). Every specialist ADR has a disposition in `docs/decisions/INDEX.md`.

## Frozen Round-Two contracts (v1.0.0)
`docs/research/contracts/` contains:
- `item` (flip | service), `action-request`, `approval`, `receipt`, `provenance` and `outcome` schemas
- Agent 03's economics schemas, vendored
- worked examples
- `validate_contracts.py`

Every build lane builds to these. Changes need an Agent 01 sign-off and a semver bump.

## Architecture direction — accepted for Round Two

- Python-first implementation.
- PostgreSQL as system of record.
- DBOS as durable workflow backbone for MVP.
- MCP as tool boundary.
- Custom Opportunity + Action + Approval + Receipt + Provenance schemas.
- Approval semantics: YES / NO / MODIFY / HOLD.
- Postgres append-only receipts/provenance + transactional outbox.
- No external side effect without governance authorization.
- No CRM as a second source of truth.
- No live phone/SMS/email in the first vertical slice.
- Official/sanctioned data sources first; riskier collectors isolated behind source adapters and governance flags.
- OSS/self-hosted core; paid services only where reliability/ROI clearly wins.

## Michael Decisions Needed
See `docs/status/MICHAEL_DECISIONS.md`.

## Integration Risks
- ToS/ban risk for certain listing sources.
- Outbound AI calling/texting legal exposure.
- Overbuilding infrastructure before the first useful loop works.
- Approval fatigue if too many low-value actions require manual confirmation.
- License contamination from AGPL/source-available components.
- Duplicate side effects after retries if idempotency is not enforced at tool boundary.
- Single-server failure; mitigate with off-box backups after MVP.

## Next move
Start Round Two with a thin vertical slice:

**DISCOVER → NORMALIZE → SCORE → RECOMMEND → APPROVE → DRY-RUN ACT → RECEIPT**

Use real read-only opportunity data, but keep external world-changing actions mocked until acceptance tests pass.
