# ARIA-20261007-2253-owned-bbq-trailer-candidate

- **ID:** ARIA-20261007-2253-owned-bbq-trailer-candidate
- **Created:** 2026-10-07
- **Sender:** Aria, acting as Michael's liaison
- **Type:** OWNER_INPUT + OWNED_ASSET + DEAL_SNIFFER_TRAINING_SIGNAL
- **Source / provenance:** direct live conversation with Michael
- **Authority:** evaluation/planning only; no purchase, seller contact, spending, external commitment, cutting/fabrication, or listing publication is authorized by this message

## Asset

Michael already owns a barbecue / tailgate trailer.

Historical purchase cost was roughly $300 about a year ago, but Michael explicitly treats that as sunk/history rather than the deciding factor for whether to rehab it now.

Known current facts:
- Michael personally pulled the trailer from **Little Rock to Conway** after installing tires.
- Therefore, at the time of that tow, the trailer was physically towable enough to make that trip on its own running gear.
- It currently has good tires according to Michael.
- It has two burners.
- It needs rework / welding.
- Michael says the shocks are poor and need attention.
- Michael can weld/fabricate himself.
- He is considering a red/black hog-inspired Arkansas tailgate aesthetic, possibly including a chrome rear bumper or other cosmetic/fabrication changes.
- Tailgating season creates a possible near-term merchandising/use case.

Important inference boundary:
The Little Rock → Conway tow is useful evidence that the frame/axle/hubs/coupler/wheels were functional enough for that trip, but it does **not** prove current roadworthiness, structural integrity, bearing condition, suspension condition, lighting compliance, or title/registration status. Inspect before scoring those as FACT.

## Why this matters to Deal Sniffer

Deal Sniffer needs to support **owned inventory / dormant assets**, not only newly discovered listings.

An owned asset can have:
- zero new acquisition cost,
- existing sunk basis,
- rehab cash required,
- operator labor required,
- current liquidation/as-is value,
- finished resale value,
- personal-use value,
- time-to-cash,
- seasonality,
- alternate conversion paths.

The system should distinguish:
1. historical cost / sunk basis,
2. new cash required from today,
3. total economic basis,
4. incremental value created by rehab.

## Candidate rehab paths

A. **Minimal safe flip**
- inspect structure/running gear
- repair only needed welds
- suspension/shock correction if required
- lights/wiring
- cleanup/paint
- prove burners
- list as a functional BBQ/tailgate trailer

B. **Themed value-add build**
- red/black hog-inspired cosmetic package
- possible chrome rear bumper / rear redesign
- upgraded finish/storage/accessories if ROI supports it

C. **Fallback conversion**
- if BBQ configuration is poor but chassis is sound, evaluate utility/event/camp-cooker conversion instead of forcing the original concept.

## Required intake once photos arrive

Collect:
- full left/right/front/rear photos
- tongue/coupler
- axle/springs/shocks
- hubs/bearings evidence if inspectable
- underside/frame/welds
- lights/wiring
- deck/floor
- burners/cooking surface
- tire size/date/condition
- VIN/tag/title/bill-of-sale status
- overall dimensions
- whether burners work
- whether it tracks/pulls straight now
- structural rust/cracks
- approximate material thickness where relevant

## Economics fields this asset should exercise

- owned_asset = true
- historical_basis
- incremental_cash_required
- as_is_liquidation_value
- minimal_rehab_cost_range
- themed_rehab_cost_range
- finished_resale_range
- operator_hours
- profit_per_incremental_dollar
- profit_per_hour
- expected_days_to_cash
- seasonality / tailgate demand
- personal_use_value
- structural_risk
- roadworthiness_confidence
- alternate_use_value
- keep_vs_flip recommendation

## Coordinator action requested

1. Acknowledge this as an owned-inventory Deal Sniffer candidate.
2. Map it to the existing inventory/opportunity-card/economics model rather than creating a one-off subsystem.
3. Ensure owned assets can be evaluated on **incremental cash from today**, not rejected because of sunk historical basis.
4. When Michael supplies photos, create a structured inspection/evaluation object and score:
   - KEEP
   - MINIMAL REHAB FLIP
   - THEMED VALUE-ADD FLIP
   - CONVERT
   - SELL AS-IS / PART OUT
5. Preserve FACT vs INFERENCE on the prior Little Rock → Conway tow.
6. Record disposition under `docs/messages/acks/ARIA-20261007-2253-owned-bbq-trailer-candidate.md`.

## Acceptance

This training signal is incorporated when the system can represent this trailer as owned inventory and compare as-is sale, minimal rehab, themed rehab, conversion, and keep/use paths using current incremental cash, operator labor, risk, seasonality, and time-to-cash.
