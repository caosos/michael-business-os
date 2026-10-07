# ACTIVE WORK: who is doing what right now

- **Maintained by:** Agent 01. Synced from each agent's own `AGENT_STATUS.md` on its branch.
- **Last synced:** 2026-10-07 12:10 -0500.
- **Rule:** one claimed task per agent at a time. Claims are first-come by pushed commit time (`docs/COORDINATION.md`).

| Agent | Current task | Branch @ head | Started | Dependency / blocker | Next action (queue) |
|---|---|---|---|---|---|
| **01** Coordinator | **A-01** phase 1: state adapter on 04's existing SQL API. A-00 (ADR-0010) DONE | `research/agent-01-coordinator` | 2026-10-07 12:10 | Phase 2 waits on D-01/D-02 | A-02 release gate, then A-03 when E-02 lands |
| **02** Discovery | **B-01** `SourceAdapter`/`Normalizer`/`Deduper` on `mbos.interfaces` | `research/agent-02-opportunity` @ `6f84127` | 2026-10-07 12:07 | none | B-02 (ADR-0010 hashing), then B-03 |
| **03** Economics | **C-01** RESEARCH/estimate producer | `research/agent-03-economics` @ `b923852` | 2026-10-07 12:07 | none | C-02 (ADR-0010 hashing), then C-03 |
| **04** State ⚑ CRITICAL PATH | **D-01** migration 0005 + **D-02** ADR-0010 ledger (claimed together as "R1 + R3") | `research/agent-04-state` @ `7f0649a` | 2026-10-07 12:06 | none; **everything downstream waits on this** | D-03 |
| **05** Governance | **E-01** R7 grant + ADR-0010 `payload_hash` and stand-in `row_hash` | `research/agent-05-governance` @ `bd5aa3d` | 2026-10-07 12:06 | none | E-03 (A8/A9 hardening) while E-02 waits on D-01 |
| **06** Operator UI | **F-01** UI on `spine.decide` (R10) | `research/agent-06-communications` @ `6129cf5` | 2026-10-07 12:06 | none | F-02 (ADR-0010 hashing), then F-03 |
| **07** QA | Unblocked verification. **Switch to G-01** now that F-13/F-14 are ruled | `research/agent-07-marketing` @ `6fcaf98` | 2026-10-07 12:06 | none (R11 amended: G-02 is READY now) | G-01, then G-02 |

**Idle agents:** none. Every agent has a claimed task, and every agent has at least two READY follow-ups.
