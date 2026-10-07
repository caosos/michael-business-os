# Receipt: E-15, F-40 backstop and F-41 least privilege (Agent 05)

- **Date:** 2026-10-07
- **Task:** E-15 (P0, release). Findings F-40 and F-41 from Agent 07's G-06 verdict.
- **External effects:** none.

## F-40 backstop
- **Case.** A YES that lacks the step-up the PDP requires is accepted upstream (the spine records it through lane D directly) and then refused at the gateway. Before, the request stayed `approved` and the item ended FAILED, so Michael's approval was lost.
- **Fix.** `approved → failed` with `ACTION_FAILED` in the same transaction, plus a released reservation, when the refusal is one that retrying cannot fix.
  - A shared `_terminal_refusal` rule decides which refusals are terminal. G7 (freeze) keeps R20's `cancelled_by_freeze`, and freeze takes precedence over failed.
  - Transient conditions keep the approval: quiet hours, budget caps, an unreadable policy or rules file, and G8 system state.
- **Prevention** is Agent 01's: `decide()` now refuses such a YES using the PDP's `step_up`.

## F-41 least privilege
- `agent-01-coordinator` now holds only: `comms.email.send`, `comms.sms.send`, `offer.*` (7), `purchase.create`, `publish.listing.create`, `publish.content.post`.
- `money.payment.send`, `price.change` and `commit.external` are granted to nobody until a lane needs them.
- `comms.voice.call`, `comms.message.send` and `schedule.appointment.create` stay ungranted for the spine.
- **Per-lane proposers:** a proposed action carries `lane`. `spine_adapter.proposer_for()` stamps `proposed_by`.
- Policy `2026.10.07-w1.8`.

## Verification (FACT)
- 37 E-15 tests pass.
  - **F-40:** a missing step-up, a bad auth context, scope, channel or decider, a revoked grant and a secret all settle `failed`. Quiet hours, budget caps and an unreadable policy keep the approval. A freeze beats failed.
  - **F-41:** the exact grant matrix is asserted against the shipped policy file, and every money-moving capability is denied for every agent.
- The mechanics tests (all 11 categories) use a test copy of the policy that adds the three money capabilities for agent-01. The shipped policy does not.
- The full suite (408 tests) passes on PG16.
