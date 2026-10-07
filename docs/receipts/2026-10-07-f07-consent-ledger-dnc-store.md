# Receipt: F-07, consent ledger + DNC scrub store

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-07` (06's claim pushed in `e570c09`; the queue at `aa88e7a` already showed it as CLAIMED from 01's sync)
- **Intent:** E2 should grade PASS/FAIL instead of DRY_RUN_EXEMPT. Consent and DNC scrubs become append-only, receipted data, with raw contact values referenced and never copied.
- **Effect:** this branch only. Tables were created only in pytest pgserver databases. No contact, no sends, no network (test-enforced).

## Provenance
| Input | Ref |
|---|---|
| Task text | READY_QUEUE @ `aa88e7a` (F-07 = P-06-6) |
| Spine used | `mbos` @ `aa88e7a` (git archive, installed, not merged): `mbos.ledger.append_receipt` / `record_provenance` |
| Legal basis for the checks | `comms_spec/data/comms_policy.v1.json` (F-03), Round One receipt-04 |

## What was built
- `comms_spec/sql/0001_comms_ledger.sql`: schema `mbos_comms` with `contacts` (the only place a raw value lives), `consent_events` and `dnc_scrubs`. All insert-only (UPDATE, DELETE and TRUNCATE are rejected by triggers) and idempotent. **PROPOSED for lane D (04 owns DDL, R1).**
- `comms_spec/ledger.py`:
  - `register_contact` returns an opaque `cref_<ULID>`, idempotent on the normalized value.
  - `record_consent`, `revoke_consent`, `handle_inbound` (STOP → revoke) and `record_dnc_scrub` each write the ledger row, provenance and a hash-chained `mbos.receipts` row in **one transaction**.
  - `ConsentLedger.consent_lookup` / `.dnc_lookup` plug into `CommsDryRunEffector`. A missing contact or consent is `not_found`, which blocks.
- Receipt types: v1.0.0 has no consent types, so these use GRANT_CREATED/GRANT_REVOKED with `entity_type` `consent` or `dnc_scrub`. Requested for ADR-0009: CONSENT_RECORDED / CONSENT_REVOKED / DNC_SCRUB_RECORDED.

## Verification (FACT)
- `tests/test_comms_ledger.py` (8 tests):
  - insert-only enforced;
  - no raw value in any receipt, and the chain verifies;
  - fault injection gives both-or-neither (receipt count and ledger rows unchanged);
  - lookups fail closed and follow the latest event, and STOP suppresses;
  - **E4: STOP → suppression is within 60 s, and the next send is blocked;**
  - **E2 is graded PASS (ratio 1.0) on a real spine run with consent on file, and without consent the send is blocked → ACTION_FAILED;**
  - E2 FAIL for a live-style send without recorded checks.
- Full suite: `72 passed` (spine `aa88e7a`). This also confirms A-13: `A13_shim` was removed, and the blocked → ACTION_FAILED test passes.

## Finding (FACT, reported to Agent 01; their code, not changed here)
Spine @ `aa88e7a` assigns receipt `seq` with `nextval('mbos.receipts_seq')` inside the chain trigger. Sequences are not rolled back, so **any rolled-back receipt transaction leaves a seq gap**. A1 fault injection does exactly that.
- `mbos.verify_chain()` checks only `prev_hash`/`row_hash` links and reports ok.
- The normative ADR-0010 `mbos_canonical.verify_chain` reports `gap before seq N`.
- Hash links stay intact: the test re-checks every link with the reference.

The finding is pinned in `tests/test_operator_ui.py::test_finding_spine_seq_gap_after_rollback_is_flagged_only_by_the_reference`. The Operator UI ledger page shows both results. R1 already moves the ledger to lane D's gapless chain.
