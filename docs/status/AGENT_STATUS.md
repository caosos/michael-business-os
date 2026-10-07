# Agent Status

Agent: 07
Role: ROUND TWO — QA / End-to-End Integration / Manual-Assist Outputs (lane G)
Branch: research/agent-07-marketing
Worktree: /home/michaelos/business-os-worktrees/agent-07-marketing
State: WORKING
Current phase: Round Two, wave one — harness delivered against mocks; starting runs against real peer lanes
Started: 2026-10-06 (round one) · 2026-10-07 (round two)
Last updated: 2026-10-07

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

## Findings (details and recommendations in docs/qa/ACCEPTANCE_REPORT.md)
- F-1 UNKNOWN: the canonical JSON form behind the example hashes is unspecified. The examples do not reproduce. (01/04)
- F-2 FACT: 5 schema gaps, covering MODIFY/HOLD required fields, step-up, the MVP `dry_run` value and the `prev_hash` pattern. (01)
- F-3 FACT: there is no `superseded` ActionRequest status for requests closed by MODIFY. (01/05)
- F-4 FACT: `INSERT OR REPLACE` bypassed the DELETE triggers in SQLite. The Postgres analogue is `TRUNCATE`. (04)
- F-5 FACT: the hash chain cannot detect tail truncation and needs an external anchor. (04)
- F-6 FACT: budget reservations must be durable and committed in the same transaction as `ACTION_EXECUTING`. (05/04)
- F-7 / F-8 INFERENCE: A2 roles, A8 against LiteLLM and A9 egress are proven on mocks only. Re-run against the real lanes before MVP sign-off.
- F-9..F-12: item state with multiple actions, the guard-denial receipt type, step-up fatigue on irreversible emails, and the coordinator validator skipping `format` checks.

## Blockers
None.

## Needs Michael decision
None new. (Round-one marketing questions remain parked until marketing go-live.)

## Needs coordinator review
- Findings F-1, F-2, F-3, F-9 and F-10 touch the frozen contracts. A v1.1.0 bump is proposed and is for Agent 01 to decide.

## Next action
Peer lanes pushed code during this session (01 c6c5ad4, 02 5b62625, 03 dcd6883, 04 3af8e92, 05 03db146, 06 3e51ba4). Next: run the contract and conformance checks against their real outputs, then wire `MBOS_QA_IMPL` to Agent 01's spine.
