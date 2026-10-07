# ARIA-20261007-1840-deal-scoring-training

- **ID:** ARIA-20261007-1840-deal-scoring-training
- **Created:** 2026-10-07
- **Sender:** Aria, acting as Michael's liaison
- **Type:** TRAINING_SIGNAL + OWNER_INPUT
- **Source / provenance:** direct live conversation with Michael while manually evaluating Marketplace opportunities
- **Authority:** design/scoring input only; no spend, offer, seller contact, publishing, or live action is authorized by this message

## Owner intent

Michael is actively training the Deal Sniffer / Michael Business OS on how opportunities should be valued.

The scoring engine must not use a universal absolute-profit floor such as "$300 profit minimum" for every deal.

Michael's actual decision logic is more nuanced:

- A large/capital-intensive flip should clear a meaningful absolute-profit threshold.
- A tiny cash exposure that can double or triple in an hour can be excellent even when absolute profit is only $30-$100.
- Capital velocity matters.
- Time to cash matters.
- Profit per hour matters.
- Cash at risk matters.
- Downside if the diagnosis is wrong matters.
- Parts/liquidation value matters.
- Seasonality and likely hold time matter.
- Transport/handling burden matters.
- Michael's own repair skill materially changes repair economics.
- The system should distinguish "good asset" from "good buy for Michael right now."

## Concrete examples from training

### 1. Older riding mower
Potentially large gross spread after repair, but it is late in mowing season.

Michael identified the real risk correctly:
- cash can become trapped for months;
- even if he can repair spindle, carburetor, hydrostat, charging, PTO, tires, etc., repair skill does not remove seasonal demand risk;
- with funds tight, a mower can be a technically good flip and still be the wrong purchase today.

### 2. 65-inch LG TV at about $30
Potential absolute profit is small, but if:
- diagnosis is quick,
- repair is cheap,
- resale can happen same day,
then $30 → $60-$100+ inside roughly an hour may be an excellent opportunity.

The major risk is binary downside such as a panel/edge-driver failure. Therefore the score should compare:
- fast capital velocity
against
- probability of terminal panel failure
and
- parts-out/downside floor.

### 3. Non-running Honda Recon 250 around $300
Higher cash exposure, but if engine/transmission fundamentals are intact, the spread to running value can be very large. Hunting-season demand may improve liquidity. This is a different opportunity class from the TV.

## Required economics/scoring concepts

Agent 01 should triage this to the economics/scoring lane and related card/UI lanes.

Add or verify explicit support for:

1. `cash_at_risk`
2. `expected_days_to_cash` or a time-to-sale range
3. `capital_velocity`
4. `gross_profit_range`
5. `profit_per_hour` / operator-time-adjusted return
6. `cash_multiple` / ROI
7. `seasonality_score`
8. `liquidity_score`
9. `repair_uncertainty`
10. `catastrophic_downside_probability`
11. `parts_out_floor` / liquidation value
12. `transport_handling_cost`
13. `skill_fit`
14. `personal_use_value` when relevant
15. `current_cash_context` / capital-lockup sensitivity
16. separate classifications for:
    - MICRO_FLIP / QUICK_TURN
    - STANDARD_FLIP
    - CAPITAL_INTENSIVE_FLIP

## Core rule

Do not reject a deal solely because expected gross profit is below $300.

A $30 item that reliably becomes $75-$100 in an hour may outrank a $250 item that becomes $600 in four months.

The ranking objective should be closer to:

**expected risk-adjusted profit × confidence × capital velocity**

while still preserving absolute cash-profit, ROI, time-to-sale, and downside exposure as separately visible fields.

Do not collapse all of these into one unexplained magic score.

## Requested coordinator action

1. Reconcile this training signal against existing economics/card contracts and current lane work.
2. If the concepts are missing or incomplete, create bounded READY tasks for the appropriate agents.
3. Keep the current dry-run safety boundary.
4. Preserve these dimensions in the Deal Sniffer opportunity card so Michael can see *why* a small fast flip outranks a larger slow one.
5. Record an ack/disposition receipt in `docs/messages/acks/ARIA-20261007-1840-deal-scoring-training.md`.

## Acceptance

This message is considered incorporated when Agent 01 has:
- acknowledged it durably;
- mapped it to existing or new tasks;
- preserved the no-universal-$300-floor rule in project truth;
- ensured the card/scoring model can represent capital velocity and time-to-cash explicitly.
