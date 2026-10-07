# Receipt: E-13, 07's G-04 release blockers F-24 / F-25 (R22) / F-22 (Agent 05)

- **Date:** 2026-10-07
- **Task:** E-13 (P0, release blocker)
- **Inputs:** `agent-07-marketing @ 6d43d2b` `docs/qa/RELEASE_CANDIDATE.md` and `ACCEPTANCE_REPORT.md` (F-22, F-24, F-25); Agent 01's ruling R22.
- **External effects:** none. Dry-run only.

## F-24: a denied approval must not stay `approved`
- **Cause.** 07 tested `101a7e6`, before R20 (E-12, `c507ac0`). R20 already moves any `approved` request refused by a **PANIC** reason (`G7:PANIC_*`) to `cancelled_by_freeze`.
  - `PANIC_STATE_UNREADABLE` also starts with `PANIC_`, so empty, corrupt and unavailable states are covered.
  - L1, L2 and L3 are covered too.
- **How it settles.** The status move and the `ACTION_FAILED` receipt happen in one transaction, and the reservation is released. Lane D's deferred trigger makes a status change without a receipt impossible (tested).
- **A distinction.** An unreadable or broken *policy* is not a freeze. It leaves the approval intact (`approved`), because the specific expiry and hash reasons are what change status.
- **Regression.** `test_a_request_denied_by_a_freeze_cannot_fire_once_the_switch_is_readable_again` runs against **6 fault modes**:
  - L3 frozen before the YES
  - state emptied
  - checksum corrupted
  - reader unavailable (`panic_read` missing)
  - L2
  - L1

  After each denial, the switch is repaired or released and the request is executed again. It stays `cancelled_by_freeze`, with 0 effector rows, and a fresh proposal plus YES executes.
- 07's own copy of the test runs on Agent 01's spine and was **not** run by me. Agent 07 should re-run it on the new head.

## F-25 / R22: the simulated provider's delivery log is durable
- **Change.** `DryRunEffector` no longer keeps an in-process log. It writes the delivery to lane D's `mbos.effector_calls` at send time, in its own committed transaction (`DurableProviderLedger`), before success is reported. Its lookup reads the same row.
- **Crash after the send.**
  - The durable row exists, but the request is still `executing`.
  - The DBOS re-run of `gateway_step`, or `gw.reconcile()`, finds the row and settles `executed`. It runs `BUDGET_COMMITTED` and `ACTION_EXECUTED`, with `details.reconciled`, and the Item reaches ACTED.
  - The effector is **not** called again.
- **Crash before the send.** No durable row exists, so the request settles `failed` with a `RECONCILED` receipt (`PROVIDER_NOT_FOUND`) and the reservation is released. It is not retried, and Michael re-approves.
- **A provider that cannot answer** (timeout, outage) settles `failed` too (`PROVIDER_UNPROVEN`), never a resend and never stuck.
  - The receipt says that for a live provider the send must be verified before re-approving.
  - The alert is `reconcile_unproven` (MEDIUM). This replaces my earlier "NEEDS_HUMAN, leave it executing" behaviour, per R22.
- A new process with empty memory still finds the send (`test_the_provider_log_is_durable_not_in_process`).

## F-22: publish.* grants
- `agent-01-coordinator` (the spine's proposer) now holds propose-only `publish.listing.create` and `publish.content.post`. `agent-07-marketing` already held them.
- They are tier 0, category publishing, default deny otherwise.
- `publish.*` may map only to publishing. A `publish.*` request carrying a binding key (`offer`, `counter_offer`, …) is denied as `BINDING_UNDER_PUBLISH`, and binding offers stay on `offer.*`.
- Policy `2026.10.07-w1.7`.

## Verification (FACT)
- **E-13 tests:** 22 pass.
- **Full suite:** 362 tests pass on PG16 with lane D @ `a08dd9f`, in one clean run. The reconcile, adapter and alert tests were rewritten for the durable provider.
