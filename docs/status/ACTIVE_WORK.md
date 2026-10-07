# ACTIVE WORK: who is doing what right now

- **Maintained by:** Agent 01. Synced from each agent's own `AGENT_STATUS.md` on its branch.
- **Last synced:** 2026-10-07 17:00 -0500.
- **Rule:** one claimed task per agent at a time. Claims are first-come by pushed commit time (`docs/COORDINATION.md`).

| Agent | Current task | Branch @ head | Started | Dependency / blocker | Done this wave | Next (queue) |
|---|---|---|---|---|---|---|
| **01** Coordinator | **A-02** release gate; then A-01 A1–A10 parity on lane D | `research/agent-01-coordinator` | 17:00 | none | A-00, A-03, A-05, A-07, A-08, A-09, A-11, A-13, A-14, A-16, A-17, A-01 m1+m2 | A-15, A-12, A-10, A-06 |
| **02** Discovery | **B-15** listing_activity + seller enrichment (P0, Deal Sniffer card) | `research/agent-02-opportunity` | 18:10 | none | B-01..B-11, B-13, B-14 | B-12 (blocked) |
| **03** Economics | **C-15** economics/logistics/seasonality/why blocks (P0), then C-16 | `research/agent-03-economics` @ `cc383cc` | 18:10 | B-15 (dates) | C-01..C-14 | C-16 |
| **04** State | **D-11** velocity caps, then **D-15** mbos_dbos bootstrap helper | `research/agent-04-state` | 16:40 | none | D-01..D-08, D-10, D-13 | D-14 |
| **05** Governance | **E-12** offer/purchase policy + R20 | `research/agent-05-governance` | 18:10 | none | E-01..E-11 | — |
| **06** Operator UI / Comms | **F-13** render the opportunity card (P0) | `research/agent-06-communications` @ `9fd135c` | 18:10 | A-19 (done) | F-01..F-12, F-04 | F-11 after A-15 |
| **07** QA ⚑ RELEASE | **G-04** release-candidate run on lanes D/E, then **G-05** card acceptance | `research/agent-07-marketing` | 17:00 | none | G-01, G-02 | G-03, G-05 |

**Idle agents:** none.

**Critical path now:** G-04 (07) + A-02 (01) → wave-two release candidate.

**Interop status.**
- F-14 is CLOSED: every Python lane passes all vectors and all rejections.
- F-13 is CLOSED: lane D's chain verifies with the pure-Python reference (01's gate, hard pass since 13:00). Lanes 05 and 07 verify `receipt_chain`.
