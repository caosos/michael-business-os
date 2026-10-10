# OWNER ADDENDUM — arbitrary search origin and radius; reuse earlier GPT Deal Finder auction sources

ID: ARIA-20261009-1930-owner-custom-radius-previous-gpt-auction-sources
Created: 2026-10-09 ~19:30 CDT
Sender: Aria on Michael's behalf
Type: OWNER_INPUT / PRODUCT_REQUIREMENT
Related: ARIA-20261009-1920-michaels-marketplace-one-hour-vertical-slice.md and B-25/F-46; do not duplicate implementation branches.

## Michael's clarification
Michael wants his new **Michael's Marketplace** to see **the auctions his earlier GPT Deal Finder found, plus other auction sources**, filtering results **within whatever number of miles he specifies from whatever location he enters**. Conway, Arkansas and 100 miles are his defaults/preferences, **NOT fixed constraints**. Each new search and saved campaign must persist editable: city/ZIP/geocodable search origin; arbitrary nonnegative radius miles (not just fixed dropdown options); optional nationwide/anywhere; item/category/keyword; price; seller-stated condition; include/exclude/must-have description phrases. Provide source selection and source-health/availability, do not infer item location or distance without grounded location. If only city/ZIP is available, clearly mark distance as approximate straight-line, not claimed road miles; unknown location should remain UNKNOWN with explicit filter handling.

## Earlier auction sources recovered from prior Deal Finder research
These are authentic discovery leads for audit and permitted data ingestion; NOT claims the source is already connected/authorized for automatic collection:

1. **Wooley Auctioneers**, https://wooleyauctioneers.com/auctions/ — previously discussed **T.J. Bruck Estate Heavy Equipment & Machinery Auction (Perryville, AR)**; original auction page: https://wooleyauctioneers.com/t-j-bruck-estate-heavy-equipment-machinery-auction-perryville-arkansas/ (October 13, 2026 closing listed on official site at time of lookup).
2. **Wilson Auctioneers**, https://wilsonauctioneers.com/auctions/ — previously discussed **Little Rock cabinet-shop liquidation** (Oct 14, 2026 closing listed) and **Hot Springs campers/vehicles/trailers/equipment** (Oct 13, 2026 closing listed). Official site is a source directory, not evidence of individual current bids.
3. **HiBid**, https://hibid.com/ — previously used in GPT Deal Finder comparisons/research; access method/permissions for automatic capture needs source-specific audit.
4. **Proxibid**, https://www.proxibid.com/ — prior auction research/comparables; source-specific access verification required.
5. **GSA Auctions**, official GET API from earlier verified smoke: receipt docs/receipts/2026-10-09-gsa-api-smoke.md — current first connector B-25.
Potential later sources already in B-23 plan (GovDeals, PublicSurplus, auction houses, estate auctions, equipment platforms) remain candidates only. Do not advertise connected status prematurely.

## Acceptance and priority
**Don't delay the first one-source GSA vertical slice.** Record sources 1–4 in the source backlog and integrate one by one with documented lawful/technical collection path, tests, real seller/auction links and original images where permitted. In the sidebar search UI, origin and radius must be owner-customizable, not hardcoded Conway/100 miles; preserve searches per campaign; permit 'Anywhere'. Distinguish an auction-house's location from the **lot pickup/location**; radius applies to actual lot/pickup location, never merely the company's HQ.

Do not scrape without permission, bypass login/CAPTCHA or site restrictions, spend money, contact sellers or bid. CAOSCare and Desktop-Agent remain PAUSED. Reuse existing campaign/filter models, no new silo, new files <=300 lines and <=400 hard-review boundary. Owner wants real results and tight agent control.

ACK via docs/messages/acks/ARIA-20261009-1930-owner-custom-radius-previous-gpt-auction-sources.md on coordinator branch when synced. This addendum is a product directive, not evidence of implementation.
