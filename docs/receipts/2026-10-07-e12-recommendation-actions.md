# Receipt: E-12, recommendation-action policy and R20 (Agent 05)

- **Date:** 2026-10-07
- **Task:** E-12 (READY_QUEUE @ `d2ef52f`; triggered by Michael's Deal Sniffer card)
- **External effects:** none. Dry-run only.

## Built
- **Policy `2026.10.07-w1.6`:**
  - capabilities `offer.{email,sms,message}.{send,counter}`; `offer.submit` and `purchase.create` existed already
  - grants for agent 06 (offers and counters) and agent 01 (all offers and `purchase.create`)
  - the `recommendation_actions` block: binding namespaces, comms categories, binding payload keys, cash-at-risk defaults
  - the schema pins the namespaces and category sets
- **PDP:**
  - a binding payload under `comms.*` is denied
  - `step_up_required()` and `PolicyDecision.step_up`
  - policy cross-checks for the namespace rules and for step-up on offer and purchase
- **Gateway:**
  - cash-at-risk per flip and in total
  - **R20**
  - one bug fixed: an unreadable policy no longer changes the request's status. Before, a transient policy problem expired or failed an approved request. Now only the specific expiry and hash reasons change status.
- **Test harness:** it falls back to `/tmp` for its socket directory when `/run/user/1001` has no free space.

## Verification (FACT)
- 338 tests pass on PG16 (lane D @ `a08dd9f`).
- **CONTACT / OFFER / COUNTER / BUY:** each is tier 0 with the right step-up flag. 10 card actions across 8 capabilities pass, and 5 default-deny cases are denied.
- **Binding payload under `comms.*`:** denied for email, SMS and message across 4 payload shapes. The same content is accepted on `offer.*`.
- **Editing the policy to break the namespaces:** each of the 4 attempts makes the policy unavailable.
- **Full offer → counter → buy flow:** a YES without step-up is refused, and a YES with step-up executes in dry-run.
- **Cash at risk:** per-flip and total limits hold, and released cash frees them.
- **R20:** L1, L2 and category freezes each leave a `cancelled_by_freeze` request, an `ACTION_FAILED` receipt and a released reservation. The request stays dead after an unrelated release, and a fresh proposal executes.

## Needs attention
- **The frozen example `action-request-email-held` has `offer: 1050` under `comms.email.send`.** The new rule would deny it, which is exactly the situation the rule exists for. The example is wrong for the new policy, so ADR-0009 should regenerate it.
- **Environment (FACT):** `/run/user/1001` is a 1.5 GB tmpfs that is 100% full, mostly leftover `a07-spine-pg-*` and `d13-*` Postgres clusters from other lanes. I did not touch them. Agents 04 and 07 should clean them up.
