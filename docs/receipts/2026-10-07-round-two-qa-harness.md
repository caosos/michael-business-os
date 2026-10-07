# Receipt: round two, wave one — QA / integration harness (Agent 07, lane G)

- **Date:** 2026-10-07
- **Agent:** 07 (QA / end-to-end integration / manual-assist outputs)
- **Branch:** research/agent-07-marketing
- **Mode:** implementation, DRY-RUN ONLY. Nothing was published, sent, spent or contacted.

## Inputs read (provenance)
| Source | Ref | What was used |
|---|---|---|
| `docs/research/agent-01-integration.md` (§4 state machine, §8 acceptance suite A1–A10/G) | origin/research/agent-01-coordinator @ `acb6f3b` | test definitions |
| `docs/research/contracts/**` (6 schemas, 3 vendored Agent 03 schemas, 7 examples) | same @ `acb6f3b` | pinned byte-exact into `qa/contracts/` with `PIN.json` sha256 manifest |
| ADR-0004..0008, START_HERE.md, AGENT_HANDOFF.md, ROUND_ONE_SYNTHESIS.md (lane G) | same | contract rulings, 8-check guard, 3-level PANIC, ownership |

## What was checked and how
- FACT: the contract runner validates pin integrity, absence of drift against the coordinator branch, schema validity, 7 examples, and 21 negative invariants. Result: 31/31 pass.
- FACT: 5 contract gap probes. The schema accepts documents that the ADR prose forbids. Each rule is enforced at runtime and tested.
- FACT: the A1–A10 + G pytest suite (76 pass, 1 strict-xfail known gap) runs against reference mocks behind the `MBOS_QA_IMPL` seam.
- FACT: A5 uses a real hard kill (`os._exit(137)`) in a child process at two points inside ACT. The effector is called exactly once after restart.
- FACT: the e2e run takes one synthetic flip and one synthetic service through the whole spine. Its output is reproducible byte for byte.
- FACT: the suite found three defects in its own reference implementation, which were fixed in code. No test was weakened:
  1. `INSERT OR REPLACE` bypassed the append-only DELETE trigger.
  2. Budget reservations were lost on a crash.
  3. Re-ingesting the same listing crashed instead of deduplicating.
- UNKNOWN: the canonical JSON form behind the example hashes (finding F-1).

## Outputs
- `qa/` (harness, mocks, fixtures, tests)
- `docs/qa/ACCEPTANCE_REPORT.md`
- `docs/qa/e2e/E2E_REPORT.md`
- `docs/qa/e2e/packets/*`

## Not verified
- A2 role-level denial, A8 against LiteLLM, and A9 egress/lease revocation. These are mocks only (findings F-7, F-8).
- Peer lanes pushed implementations during this session (01 `c6c5ad4`, 02 `5b62625`, 03 `dcd6883`, 04 `3af8e92`, 05 `03db146`, 06 `3e51ba4`). They were not yet exercised by this suite at the time of this receipt.
