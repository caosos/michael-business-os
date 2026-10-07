# Michael Business OS — Agent Dashboard

Last updated: 2026-10-06 (by Agent 01, round-one reconciliation)

> **Source of truth:** each agent's `docs/status/AGENT_STATUS.md` on its own `research/agent-XX-*` branch. Agent 01 reads those branches with `git show` (never by checkout) and refreshes this table. Peer "Last update" values are copied verbatim; some are in UTC, which is why a few read 2026-10-07. Progress is never invented.

| Agent | Role | State | Current objective | Last update | Blocker | Deliverable (branch @ commit) |
|---|---|---|---|---|---|---|
| 01 | Coordinator / Architect | **COMPLETE (round one)** | Reconciliation done; round-two gap requests issued | 2026-10-06 | Michael P1 decisions | `agent-01-integration.md`, `contracts/`, ADR-0001..0008, `INDEX.md` |
| 02 | Opportunity Discovery | COMPLETE | Awaiting coordinator review → now: round-two gaps (§10) | 2026-10-07T04:02Z | none | `agent-02-opportunity.md` @ da52612 |
| 03 | Economics / Scoring | COMPLETE | Awaiting coordinator review → now: fix C14 + schema gaps | 2026-10-07T04:03Z | Michael $/hr, caps, home base | `agent-03-economics.md` + schemas @ b032676 |
| 04 | CRM / State | COMPLETE | Awaiting coordinator review → now: adopt Receipt v1, DDL gaps | 2026-10-07T04:01:49Z | Michael RPO/RTO, CRM UI | `agent-04-state.md` @ be6aed9 |
| 05 | Governance / Security | COMPLETE | Awaiting coordinator review → now: policy matrix as data, merged PANIC | 2026-10-06 | Michael $ / comms limits | `agent-05-governance.md` @ 5ee191d |
| 06 | Communications | COMPLETE | Awaiting coordinator review → now: generalize beyond cars, approval UX | 2026-10-06 | Michael legal / EIN | `agent-06-communications.md` @ c7af3bb |
| 07 | Marketing | COMPLETE | Awaiting coordinator review → now: Campaign entity, reversibility, caps | 2026-10-06 | Michael name / area / category | `agent-07-marketing.md` @ 68dd3e8 |

## Cross-Agent Conflicts (all ruled; details in `docs/research/agent-01-integration.md` §3)
| # | Conflict | Ruling | ADR |
|---|---|---|---|
| C1 | SQLite (02) vs Postgres | **Postgres** (84.0 vs 60.0) | 0001 |
| C2 | DBOS vs Temporal (05) vs n8n (02, 07) | **DBOS** (81.5 / 74.5 / 51.0) | 0002 |
| C3 | n8n role | Connector only | 0006 |
| C4 | CRM as system of record (07) | **Postgres SoR**, Twenty as projection (78.0 vs 59.0) | 0006 |
| C5 | Three receipt shapes (01, 04, 05, 06) | Merged Receipt v1 | 0004 |
| C6 | IDs: bigint/uuid (04) vs prefixed ULID (05) | Prefixed ULID externally, `seq` internally | 0004 |
| C7 | YES/MAYBE/PASS vs YES/NO/MODIFY/HOLD vs approve/edit/reject | Machine verdict and Michael's decision are separate; routing rule | 0004 |
| C8 | Item flow vs ActionRequest status | Nested state machines | 0004 |
| C9 | PANIC (01) vs 3-level freeze (05) | Merged L1/L2/L3 (81.0 vs 72.5) | 0005 |
| C10 | LLM spend vs real-world spend | Two ledgers | 0005 |
| C11 | Approval channel | Telegram, plus web step-up; ntfy for alerts only | 0006 |
| C12 | Outbound sending, 06 vs 07 | 06 owns all effectors | 0006 |
| C13 | $/mile and distance rule, 02 vs 03 | 03's config is the single source | 03-001 |
| C14 | 03's AT-14 contradicts §12.4 | 03 must fix | 03-001 |
| C15 | Sandbox, egress and observability unowned | Assigned to 05 | 0005 |
| C16 | Evidence-tag vocabulary | FACT/INFERENCE/RECOMMENDATION/UNKNOWN | 0004 |
| C17 | ADR number collisions | Global registry plus aliases | INDEX.md |
| — | Business domain: cars (06) vs home services (07) | **Michael: flips + services** | 0007 |

## Shared Decisions
- **ACCEPTED:** ADR-0001 Postgres spine · ADR-0002 DBOS · ADR-0003 MCP · ADR-0004 unified contracts (frozen v1.0.0) · ADR-0005 governance control plane · ADR-0006 integration roles · ADR-0007 flips + services.
- **PENDING MICHAEL:** ADR-0008 Python; limits in ADR-0005; approval channel in ADR-0006.
- Specialist ADR dispositions: `docs/decisions/INDEX.md`.

## Michael Decisions Needed (packet: integration doc §11)
- **P1 (blocks build):**
  - Python?
  - $/h floor and targets, cash and loss caps, home base and vehicle
  - spend and comms limits (default-deny for the MVP)
  - Telegram as the approval channel
- **P2 (blocks live outbound):**
  - counsel before AI voice or SMS
  - EIN / entity
  - gov-surplus internal-endpoint posture (recommend HOLD)
  - review-request auto-send (recommend NO for now)
- **P3:** RPO/RTO, CRM UI, dead-man switch, signed receipts, paid fallbacks, business name/area/category, multiple approvers.

## Integration Risks (new; plus the original 11 in `agent-01-coordinator.md` §11)
1. Item v1 pins Agent 03's schemas; any change needs a version re-pin.
2. Receipt volume (5–8 per action). Monthly partitions; 02's volume per day is still UNKNOWN.
3. The legal path (TCPA, 10DLC, recording consent, UETA) is critical for live outbound. All outbound stays dry-run until P2.
4. Gray-zone source ToS. ADR-02-0202 tiers plus the L2 freeze.
5. AGPL reference code (`ai-marketplace-monitor`) must not be vendored.
6. HumanLayer is withdrawn (deprecated).
7. Agent 03's thresholds are mostly REC/UNK. Needs the P1 decisions plus LEARN calibration.

## Current Recommended Direction
**INTEGRATED and ACCEPTED for round one** (see `docs/research/agent-01-integration.md`).

Postgres is the spine, with an insert-only, hash-chained receipt ledger committed in the same transaction as each state change. DBOS runs both state machines (Item flow and ActionRequest). Michael approves YES/NO/MODIFY/HOLD through a Telegram bot. Every side effect passes through 05's Action Gateway, with 8 guard checks and dry-run enforced in the MVP. There are two spend ledgers (LiteLLM and the budget ledger) and a 3-level PANIC. 02 discovers flips and services, 03 scores them, 04 owns state, 06 owns every outbound effector, and 07 drafts.

## Round-Two Gap Requests
See `docs/research/agent-01-integration.md` §10. Each agent has an exact numbered list.
