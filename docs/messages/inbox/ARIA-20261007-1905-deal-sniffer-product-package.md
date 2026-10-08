# ARIA-20261007-1905-deal-sniffer-product-package

- **ID:** ARIA-20261007-1905-deal-sniffer-product-package
- **Created:** 2026-10-07
- **Sender:** Aria, acting as Michael's liaison
- **Type:** OWNER_INPUT + TASK_REQUEST + PROJECT_FACT
- **Authority:** product/design direction only; no live spend, contact, bidding, payment, publishing, deployment, or external commitment is authorized.

## Michael's direction

Michael expanded the Deal Sniffer concept beyond individual flips. The system should become a broader opportunity engine and, later, a local verified marketplace.

Aria created the durable onboarding package:

`docs/product/DEAL_SNIFFER_START_HERE.md`

on branch:

`origin/liaison/aria-to-agent-01`

The package captures:
- Weekly Money Mission: given Michael's skills, time, location, capital and weekly target, find the best legal path to close the income gap.
- $500 protected-principal bankroll model.
- No universal absolute-profit floor; use capital velocity, time-to-cash, risk, profit/hour, liquidity, seasonality and fit.
- Service + flip + other opportunity combinations.
- Conversational intake: users talk naturally; system asks missing questions and builds structured transaction objects.
- Evidence-rich listings with category-specific questions/photos/disclosures.
- One canonical inventory object with multiple truthful audience-specific merchandising views.
- Categories such as mechanic special, project/fix-and-flip, quick-turn, donor/parts, auction, wanted match, contractor opportunity.
- Buyer wanted campaigns and persistent opportunity campaigns.
- Seller listings, buyer bids, customer jobs, provider bidding, services.
- Verified-account/payment commitment and behavior-based reputation.
- Conditional bids/contingencies and transaction evidence.
- Jurisdiction-aware service eligibility rather than blanket contractor-only restrictions.
- Valuation engine for homes and other assets.
- Long-term growth path: Michael private engine → transaction engine → public marketplace.

## Immediate coordinator action

1. Read and acknowledge the full product package.
2. Reconcile it against current repo truth.
3. Keep MVP scope disciplined, but create bounded current-scope tasks where the package exposes missing capabilities.
4. At minimum evaluate and queue:
   - weekly money mission / portfolio-of-opportunities planning;
   - richer opportunity classes;
   - canonical inventory plus audience-specific merchandising views;
   - campaign/wanted-object model seams;
   - conversational intake seams;
   - valuation interfaces that can be added later without refactoring the core.
5. Add `docs/product/DEAL_SNIFFER_START_HERE.md` to the canonical onboarding path on the coordinator branch.
6. Preserve DRY-RUN and existing governance boundaries.
7. Create an acknowledgment under `docs/messages/acks/ARIA-20261007-1905-deal-sniffer-product-package.md`.

## Important runtime concern

Michael reports that all seven Claude agents can become idle simultaneously even while useful work remains. The written foreman loop is not sufficient by itself; the host needs a real idle-agent wake/dispatcher mechanism. Treat runtime foreman/watchdog activation as an immediate operational priority.
