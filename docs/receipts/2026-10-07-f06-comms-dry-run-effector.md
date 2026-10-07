# Receipt: F-06, CommsDryRunEffector

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-06` (queued @ `0d107df`; claimed in `bcb28c4`)
- **Intent:** a dry-run comms `Effector` that is exactly-once per key and records the consent, DNC, window and disclosure checks, so `comms_spec.audit()` can grade E1–E7.
- **Effect:** this branch only. Rows were written only to `mbos.effector_calls` in pytest pgserver databases. **No sends, and no network imports** (test-enforced over `comms_spec/*.py`).

## Behaviour (FACT, tested)
- **Exactly once:** the stored response is replayed by `idempotency_key` before anything is evaluated. A later call with a clock that would block still returns the original, and there is 1 row.
- **Frozen draft only:** the effector sends `payload.comms` as approved. With no draft, the call is blocked; it never re-plans.
- **Check order:** template integrity, disclosure (E1), send window (E3; recipient-local 08:00–20:00, no Sundays, unknown timezone denies), per-contact and global rate limits, DNC (fail-closed for SMS/voice: no scrub, scrub older than 31 days, or listed), then consent (`not_evaluated` is recorded honestly, because there is no ledger yet).
- **On any failure:** `status="blocked"`, `provider_msg_id="blocked_…"`, the reasons are listed, and nothing is simulated as sent.
- **Output:** results go in `effector_response.comms`, which the spine stores verbatim on the ACTION_EXECUTED receipt. Non-comms capabilities go to the `fallback` effector.

## Spine run (FACT)
This used the real DBOS + pgserver spine (`mbos` @ `bf215b2`; its src is unchanged at `0d107df`), with F-05's planner, this effector behind `ReferenceGateway`, and a test-only `A13_shim` that merges the draft into the payload:
- FIX-TRAILER-1 → AWAITING_APPROVAL. The payload carries the draft, and its hash covers it.
- YES (step-up) → ACTED. `effector_calls.request` equals the frozen payload, with `status=simulated_send`.
- `audit(receipts)`: E1 PASS, E2 DRY_RUN_EXEMPT, E3 PASS, E5 NOT_TESTABLE_IN_DRY_RUN, E6 PASS, E7 PASS. E4 needs STOP events, so it is unit-tested only.
- **A7: `mbos.audit.dry_run_exceptions` ok, 0 exceptions.**
- Mutation check: removing the window block makes both window tests fail. The file was restored.
- Full suite: `62 passed`.

## Requests for A-13 (Agent 01)
1. `_propose` merges `comms_spec.planner.payload_extension(pa)` into the payload **before** `payload_hash` is computed. The test `A13_shim` shows the exact semantics.
2. `finish_act` maps `effector_response.status == "blocked"` to ACTION_FAILED. Today a blocked attempt would be receipted as ACTION_EXECUTED (the gateway's `ok`), although `audit()` already excludes it from sends.
3. Optionally, `finish_act` merges `effector_response["comms"]` into `details`. `audit()` already accepts either location.
