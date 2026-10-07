# Receipt: F-08, follow-up and binding offer/quote drafts as their own step-up ActionRequests

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-08` (READY after F-07; claimed in `0839229`)
- **Intent:** after first contact, the next steps (more questions, photos, a cash offer, a service quote) are each drafted as a separate ActionRequest. Binding ones are tier 0, irreversible, category `offer`, and need step-up. Nothing auto-sends.
- **Effect:** this branch only. No sends, no network.

## What was built (`comms_spec/planner.py`, planner 0.2.0)
- `plan_followup(item, asked)` (non-binding): the next two unasked category questions (`seller_followup_questions`), an SMS photo request, or `customer_photo_request` for services. Returns `[]` when no route or no questions remain.
- `plan_offer(item, amount, pickup_window, offer_expires)` (flip, BINDING, `seller_offer`):
  - refuses a non-positive, boolean, non-numeric or NaN amount;
  - **refuses any offer above the asking price;**
  - sanitizes free-text inputs.
- `plan_quote(item, amount, scope_summary, deposit_pct, quote_expires)` (service, BINDING, `customer_quote`): the deposit must be 0–50%.
- Binding drafts are proposed as **`offer.<channel>.send`**. The spine's `classify_capability` maps that to category `offer` (effect `commit`), so tier 0, step-up and 05's offer policy all apply. Under `comms.*` a binding draft would be classified as plain `email`.
- Effector: `offer.*` is accepted as comms. A binding draft under `comms.*`, or a non-binding draft under `offer.*`, is **blocked**.

## Verification (FACT)
- `tests/test_comms_followups.py` (13 tests). On the real spine (`mbos` @ `aa88e7a`), an offer passed through the spine's own `_propose` insert path (contract validation + PDP) becomes `category=offer`, `tier=0`, `irreversible`, `pending_approval`.
  - `spine.decide(YES)` without step-up raises `DecisionRefused`.
  - After 1 s there are **0 `effector_calls`**: nothing auto-sends.
  - The effector blocks a binding draft smuggled under `comms.email.send`.
- Mutation check: disabling the above-ask guard fails `test_offer_guards[1500]`. The file was restored.
- Full suite: `85 passed`.

## Gap (lane A; proposed as P-06-8)
The spine has the R12 edge ACTED → AWAITING_APPROVAL, but **no public API or workflow** to propose a follow-up ActionRequest on an existing item and run it through the approval gate. The F-08 tests therefore call the spine's internal `_propose`. Proposed: `spine.propose_followup(conn, item_id, proposed_action)` plus a gate workflow for it, called by the UI ("Draft follow-up / offer / quote" on a card) and by inbound-reply handling.
