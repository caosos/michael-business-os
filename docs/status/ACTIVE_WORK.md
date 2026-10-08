# ACTIVE WORK: who is doing what right now

- **Maintained by:** Agent 01. Synced from each agent's own `AGENT_STATUS.md` on its branch.
- **Last synced:** 2026-10-08, against branch heads 02 `bd5076b` · 03 `4579261` · 04 `cd7e338` · 05 `a55b983` · 06 `0a3c672` · 07 `7342abc`.
- **Rule:** one claimed task per agent at a time. Claims are first-come by pushed commit time (`docs/COORDINATION.md`). "Assigned" means dispatched but not yet claimed on the agent's own branch.
- **Idle check:** `tools/foreman.py` (A-22) reports any agent that is idle while READY work exists.

| Agent | Current (claimed) | Assigned next, in order | Dependency / blocker |
|---|---|---|---|
| **01** Coordinator | A-22 foreman tool, then A-23 mission schema | A-25 inventory/merchandising, A-26 campaign + valuation, A-24, A-27, A-12, A-04 | none |
| **02** Discovery | WAITING (only B-12 left) | **B-21** category tags (READY now); **B-20** campaign matcher after A-26; B-12 stays blocked on Michael #8 + credentials | B-12 only |
| **03** Economics | **C-19** (P0, claimed 4579261) | C-20, then C-21 (needs A-23), C-22 (needs A-26) | none |
| **04** State | D-09 part a (PITR, local) | **D-18** capital ledger (needs A-23); D-10 final acceptance after A-01 phase 2 | D-09b off-box destination = Michael |
| **05** Governance | WAITING (E-01..E-16 done) | **E-18** trust/payment seams, **E-19** jurisdiction pack (both READY now); E-17 after A-26 | none |
| **06** Operator UI / Comms | F-11 (claimed; its "blocked on A-15" is stale: A-15 is DONE) | F-17 (ADR-0012 fields), F-18 (needs A-23), F-19 (A-25), F-20 (A-27), F-16 | none |
| **07** QA | IDLE | **G-09** (re-verify my G-08 fixes), **G-10** (ADR-0012 card half now), **G-11** (as each schema lands) | none |

**Idle agents with READY work (dispatch sent):** 02 (B-21), 05 (E-18, E-19), 07 (G-09, G-10).

**Critical path now:** C-19 (03) -> C-20/C-21; A-23 (01) -> C-21, D-18, F-18. The dry-run release candidate (07 G-07: READY, 105/0) is not blocked by any of the product-package work.

**Interop status.** F-13/F-14 CLOSED (ADR-0010); all six Python lanes conform; release gate green at last run (see `docs/status/RELEASE_GATE.md`).
