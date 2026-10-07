# ACTIVE WORK: who is doing what right now

- **Maintained by:** Agent 01. Synced from each agent's own `AGENT_STATUS.md` on its branch.
- **Last synced:** 2026-10-07 13:55 -0500.
- **Rule:** one claimed task per agent at a time. Claims are first-come by pushed commit time (`docs/COORDINATION.md`).

| Agent | Current task | Branch @ head | Started | Dependency / blocker | Done this wave | Next (queue) |
|---|---|---|---|---|---|---|
| **01** Coordinator | **A-05** wire 03's `research_step` into RESEARCHING; then **A-01 phase 2** | `research/agent-01-coordinator` | 13:55 | none | A-00, A-07, A-08, A-09, A-11, A-13, A-01 ph.1 | A-12, A-14, A-04, A-02, A-10, A-03 after E-02 |
| **02** Discovery | **B-05** wake-event producer (assigned 13:35) | `research/agent-02-opportunity` @ `1908e91` | 13:35 | A-08 API (published this push) | B-01..B-04, C-04 support | B-06, B-07, B-08 |
| **03** Economics | **C-06** amended R13 (assigned 13:55) | `research/agent-03-economics` @ `1044ed5` | 13:55 | none | C-01..C-05 | C-07 LEARN |
| **04** State | **D-06** State MCP server (assigned 13:55) | `research/agent-04-state` @ `4bbd6a6` | 13:55 | none | D-01..D-05 | D-07, D-08 |
| **05** Governance ⚑ CRITICAL PATH | **E-02** Postgres GovernanceStore + PANIC on 0007 (unblocked) | `research/agent-05-governance` | 13:50 | none | E-01, E-03, (E-04 in progress) | E-04/E-05 |
| **06** Operator UI / Comms | **F-07** consent ledger + DNC store | `research/agent-06-communications` | 13:40 | none | F-01, F-02, F-03, F-05, F-06 | F-08, F-04 after A-03 |
| **07** QA | **G-02** QA suite on the real spine | `research/agent-07-marketing` @ `332c26c` | ~12:48 | none | G-01 | G-03 |

**Idle agents:** none.

**Critical path now:** E-02 (05) → A-03 (01, wire 05's real gateway) → G-02/G-03 (07) on real components. A-01 phase 2 runs in parallel.

**Interop status.**
- F-14 is CLOSED: every Python lane passes all vectors and all rejections.
- F-13 is CLOSED: lane D's chain verifies with the pure-Python reference (01's gate, hard pass since 13:00). Lanes 05 and 07 verify `receipt_chain`.
