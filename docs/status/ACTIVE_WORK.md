# ACTIVE WORK: who is doing what right now

- **Maintained by:** Agent 01. Synced from each agent's own `AGENT_STATUS.md` on its branch.
- **Last synced:** 2026-10-07 17:00 -0500.
- **Rule:** one claimed task per agent at a time. Claims are first-come by pushed commit time (`docs/COORDINATION.md`).

| Agent | Current task | Branch @ head | Started | Dependency / blocker | Done this wave | Next (queue) |
|---|---|---|---|---|---|---|
| **01** Coordinator | **A-02** release gate; then A-01 A1–A10 parity on lane D | `research/agent-01-coordinator` | 17:00 | none | A-00, A-03, A-05, A-07, A-08, A-09, A-11, A-13, A-14, A-16, A-17, A-01 m1+m2 | A-15, A-12, A-10, A-06 |
| **02** Discovery | **B-14** image-artifact hook (assigned 17:00) | `research/agent-02-opportunity` | 17:00 | none | B-01..B-11, B-13 | B-12 (blocked) |
| **03** Economics | **C-14** LEARN e2e on lane D (assigned 17:00) | `research/agent-03-economics` | 17:00 | none | C-01..C-13 | — |
| **04** State | **D-11** velocity caps, then **D-15** mbos_dbos bootstrap helper | `research/agent-04-state` | 16:40 | none | D-01..D-08, D-10, D-13 | D-14 |
| **05** Governance | **E-06** policy into lane D | `research/agent-05-governance` @ `8ffe87d` | 16:10 | none | E-01..E-05, E-10 | E-09, E-07, E-08 |
| **06** Operator UI / Comms | **F-04** UI on real Components (assigned 17:00) | `research/agent-06-communications` @ `b5badb4` | 17:00 | none | F-01..F-03, F-05..F-10, F-12 | F-11 after A-15 |
| **07** QA ⚑ RELEASE | **G-04** release-candidate run on lanes D/E (assigned 17:00); finish G-03 | `research/agent-07-marketing` | 17:00 | none | G-01, G-02 | — |

**Idle agents:** none.

**Critical path now:** G-04 (07) + A-02 (01) → wave-two release candidate.

**Interop status.**
- F-14 is CLOSED: every Python lane passes all vectors and all rejections.
- F-13 is CLOSED: lane D's chain verifies with the pure-Python reference (01's gate, hard pass since 13:00). Lanes 05 and 07 verify `receipt_chain`.
