# Agent Status

Agent: 07
Role: ROUND TWO — QA / End-to-End Integration / Manual-Assist Outputs (lane G)
Branch: research/agent-07-marketing
Worktree: /home/michaelos/business-os-worktrees/agent-07-marketing
State: WORKING
Claimed: G-01
Current phase: Round Two — foreman loop; G-01 (ADR-0010 interop) claimed, G-02 next
Started: 2026-10-06 (round one) · 2026-10-07 (round two)
Last updated: 2026-10-07

## Work queue (foreman loop, docs/COORDINATION.md)
- Source: `origin/research/agent-01-coordinator` @ `99e9ec0`, `docs/status/READY_QUEUE.md`. G-01 and G-02 are READY for 07, and both are unclaimed.
- **Claimed: G-01** (P1). Steps:
  - Move `core.canonical`/`receipt_row_hash` onto the ADR-0010 reference (MBOS-CJSON-1 / MBOS-RH-1).
  - Add `vectors.json` to `mbos_qa interop`.
  - Re-run interop across all lanes and publish the matrix.
- Next: **G-02** (P1, READY): `mbos_qa.impl_spine:build` against 01's public API on pgserver. Then G-03 (READY after G-02).
- Earlier note, superseded: at 11:5x no READY_QUEUE existed and R11 was WAITING. The amended R11 removes that wait.

## Current objective
Independent QA/integration lane against the frozen contracts v1.0.0. DRY-RUN ONLY.

## Completed (round two)
- `qa/`: QA harness (Python 3.12, jsonschema, pytest). Read `qa/README.md` first.
- **Contract validation runner:** pinned byte-exact contracts with a sha256 manifest, a drift check against the coordinator branch, and 21 negative invariants. It also runs 5 gap probes for rules the ADRs state but the schemas do not enforce. Result: 31/31.
- **Acceptance orchestration:** `python -m mbos_qa run` runs the contract checks, the e2e run and the pytest suite, then writes `docs/qa/ACCEPTANCE_REPORT.md`.
- **A1–A10 + G suite:** 76 pass, 0 fail, 1 strict-xfail (known gap F-5).
- **E2E fixtures:**
  - One synthetic flip: a trailer listing with a planted prompt injection. Flow: YES on the seller email, then MODIFY → YES on the resale listing.
  - One synthetic service: a drywall lead with attribution. Flow: HOLD → wake → MODIFY → YES.
  - Report: `docs/qa/e2e/E2E_REPORT.md`, covering source, normalization, economics, recommendation, approval, dry-run action, receipts and provenance.
- **Dry-run manual-assist packets** (real, owned by this lane): `docs/qa/e2e/packets/`. Each packet is content-addressed, and its hash is on the `ACTION_EXECUTED` receipt.
- **Mocks** for lanes A, B, C, D and E are clearly labelled `MOCK` in code and in every report, and sit behind the `MBOS_QA_IMPL` seam.

## Cross-lane interop against the peers' real code (docs/qa/INTEROP_REPORT.md)
Peer refs checked: 01 c6c5ad4 · 02 5b62625 · 03 dcd6883 · 04 3af8e92 · 05 03db146 · 06 3e51ba4.
- PASS (FACT): the vendored contract copies in 02, 04 and 05 are byte-identical to the frozen pin. 01 and 06 read the coordinator path.
- PASS (FACT): all 13 Agent 03 scored examples (26 documents) validate against frozen Item/Provenance v1.
- PASS (FACT): every lane computes the same payload_hash for int, string, unicode and nested payloads.
- **FAIL (FACT) F-13, blocking for integration:** two lanes (01 and 04) each define `mbos.receipts`. Their row_hash formulas differ from each other and from the contract text used by 05, 06 and 07. On real PostgreSQL 16, one identical receipt produced 3 different row_hashes, so no lane can verify another lane's chain.
- **FAIL (FACT) F-14:** `{"offer": 850.0}` hashes differently in 03 (Decimal normalisation) than in 01, 02, 06 and 07. 05 refuses floats entirely.
- **FAIL (FACT) F-15:** 03 changed its schemas but kept the pinned `$id`. Nothing breaks today.

## Findings (all in docs/qa/ACCEPTANCE_REPORT.md)
- F-1: the example hashes are not reproducible, and the contract does not pin the exact bytes. (01)
- F-2: 5 schema gaps. The runtime enforces each one. (01)
- F-3: no `superseded` status for requests closed by MODIFY. (01/05)
- F-4: `INSERT OR REPLACE` bypassed the DELETE trigger in SQLite. The Postgres analogue is `TRUNCATE`. (04)
- F-5: tail truncation needs an anchor. 04's code has one; QA has not exercised it yet. (04)
- F-6: budget reservations must be durable. (05/04)
- F-7 / F-8: A2 roles, A8 against LiteLLM and A9 egress are proven on mocks only. (05/04)
- F-9..F-12: item state with multiple actions, the guard-denial receipt type, step-up fatigue, and the coordinator validator skipping `format` checks.
- F-13..F-15: see the interop section above.

## Blockers
None.

## Needs Michael decision
None new. (Round-one marketing questions remain parked until marketing go-live.)

## Needs coordinator review
- **F-13 (blocking for integration):** rule on one receipts ledger and one byte-exact row_hash formula. 01 and 04 currently both define `mbos.receipts`.
- **F-14:** rule on number canonicalisation for hashed payloads: no floats (05) or RFC 8785 JCS everywhere.
- F-1, F-2, F-3, F-9 and F-10 touch the frozen contracts. A v1.1.0 bump is proposed and is for Agent 01 to decide.

## Next action
1. Wire `MBOS_QA_IMPL` to Agent 01's spine (`mbos.runtime` / `mbos.interfaces`) and re-run A1–A10 on real Postgres and DBOS.
2. Re-run A2 (roles), A3 (anchors) and A5 against Agent 04's store, and A8/A9 against Agent 05's gateway and PANIC.
3. Re-run `python -m mbos_qa interop` once F-13 and F-14 are ruled on.
