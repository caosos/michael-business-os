# ACTIVE WORK: who is doing what right now

- **Maintained by:** Agent 01. Synced from each agent's own `AGENT_STATUS.md` on its branch.
- **Last synced:** 2026-10-07 12:52 -0500.
- **Rule:** one claimed task per agent at a time. Claims are first-come by pushed commit time (`docs/COORDINATION.md`).

| Agent | Current task | Branch @ head | Started | Dependency / blocker | Done this wave | Next (queue) |
|---|---|---|---|---|---|---|
| **01** Coordinator | **A-05** wire 03's RESEARCH producer, then **A-04** wire 02's adapter. A-01 phase 1 DONE | `research/agent-01-coordinator` | 2026-10-07 12:40 | A-01 phase 2 waits on D-01/D-02 | A-00, A-07, A-09, A-01 phase 1 | A-02 release gate, A-08 |
| **02** Discovery | **B-03** credential-free GSA / Trash Nothing adapters | `research/agent-02-opportunity` @ `41d45a6` | 2026-10-07 ~12:35 | none | B-01, B-02 | B-04 |
| **03** Economics | **C-03** versioned `$id`s for v1.1.0 schemas | `research/agent-03-economics` @ `73a4d32` | 2026-10-07 12:40 | none | C-01, C-02 | (queue refill by 01) |
| **04** State ⚑ CRITICAL PATH | **D-01 + D-02** migration 0005 + ADR-0010 ledger; **fold in D-04** (05's requirements) | `research/agent-04-state` @ `7f0649a` | 2026-10-07 12:06 | none. No push for ~30 min; working per its claim | — | D-03 |
| **05** Governance | **E-04** secret scan + INJECTION_SUSPECTED tripwire (assigned 12:52) | `research/agent-05-governance` @ `b632583` | 2026-10-07 12:52 | none | E-01, E-03 | E-05, then E-02 when D-01/D-04 land |
| **06** Operator UI | **F-03** comms dry-run spec as data | `research/agent-06-communications` @ `c125618` | 2026-10-07 ~12:38 | none | F-01, F-02 | F-04 after A-03 |
| **07** QA | **G-02** QA suite on the real spine | `research/agent-07-marketing` @ `332c26c` | 2026-10-07 ~12:48 | none | G-01 | G-03 |

**Idle agents:** none.

**ADR-0010 interop** (`tools/interop_check.py --fetch`, 12:52):

| Lane | Result |
|---|---|
| 01, 02, 03, 05, 06, 07 | 10/10 vectors, 6/6 rejections: CONFORMS (F-14 closed) |
| 04 | gated by the strict-xfail test in `tests/integration/test_state04_adapter.py` (flips when D-02 lands) |
