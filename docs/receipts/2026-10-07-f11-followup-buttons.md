# Receipt: F-11, follow-up / offer / quote buttons on the card

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-11` (A-15 done; claimed in `0a3c672`)
- **Intent:** after the first action has acted, Michael can draft the next step from the card. Each button creates its OWN step-up request through the public API; nothing is sent until his separate YES.
- **Effect:** this branch only. Dry-run only.

## Provenance
spine `mbos` @ `2f7b887` (`workflows.propose_followup`, `spine_d.propose_followup`; installed from `git archive`, no `build/`).

## What was built
- Card section "Next step" (only for an ACTED item with no open request, lane D): **Draft follow-up questions** (next unasked Q&A, never repeating earlier question ids), **Draft an offer** (flips; binding, never above the ask) or **Draft a quote** (services; binding, deposit 0 to 50%). Drafts come from `CommsActionPlanner` (single source), tagged `lane=agent-06-communications`.
- `POST /item/<id>/followup` → `App.add_followup` (CSRF) → `SpineBackend.propose_followup` → `workflows.propose_followup` (policy path: PDP, `proposer_for`, step-up; item row locked; approval gate enqueued). Every refusal is shown with its reason and the typed values are kept; a policy block says nothing was created.
- Offers and quotes use `offer.<channel>.send`: category offer, tier 0, irreversible, PIN step-up on YES.
- UI deployment: `make_backend()` on lane D now calls `init_runtime(launch=False)`; the gate is enqueued through a DBOS client and the worker runs it.

## Verification (FACT)
- Reference 124 passed; lane D/E 27 passed (`tools/run_tests.sh`).
- Follow-up on an ACTED item → new request (`proposed_by` = 06, no `lane` in the payload), item AWAITING_APPROVAL, 0 effector calls until YES; YES without PIN refused; with PIN it executes once (1 effector call, 1 ACTION_EXECUTED) and the item returns to ACTED.
- Offer: above-ask, non-numeric and zero amounts are refused and create nothing; a valid one is category offer / tier 0 / is_binding, and executes nothing until YES with PIN. Quote on a service item (deposit above 50 refused).
- Forged POST while a request is open, missing CSRF, foreign Host (403), unknown kind and unknown item (404) are all refused.
- **Separate-process path:** a child process running `make_backend()` creates the request and enqueues the gate; the launched worker executes it after YES.
