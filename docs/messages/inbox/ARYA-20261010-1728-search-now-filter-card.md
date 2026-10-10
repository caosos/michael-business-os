# Owner correction: Search Now inside the filter card
To: existing Agent 01 coordinator
From: Arya, owner liaison
Date: 2026-10-10 17:28 UTC
Owner source: Sentinel_7ed2d81549e48191a62606fcea8e834c

Michael says: “the Find Deals Now button should be in the same filter button or filter area ... I don't like this little box down here that says Find Deals Now, New Search, Save Search, My Campaigns, Save Deals. I need a button that says Search Now ... it should be in that same card instead of this one down below.”

## Bounded work on the existing marketplace
Read current queue and active worker ownership first. Reuse the existing lane and serial handoff; no new coordinator or duplicate worker.
1. Put the primary **Search Now** action in the SAME price/distance/filter card. It must submit the actual current form values on desktop and mobile, including keyboard submission. Avoid a disconnected action box below.
2. Organize/demote New Search, Save Search, My Campaigns and Saved Deals as secondary actions without deleting or breaking their functions. This is a small composition correction, not another redesign.
3. Preserve strict min/max price and unrounded radius, unknown-result separation, visible validation, saved any-terms/categories/condition/row order, and existing Save/PIN boundary.
4. Test actual rendered forms and capture real desktop/mobile first-viewport and full-page screenshots on the exact committed artifact. Identify viewport, URL/port, filters, UTC capture time, cache hash/as-of and actual store type. Show where Search Now sits and demonstrate submitted values affect results. Report code/test/staging separately.

## Source-backed auction labels, bounded follow-on only
Distinguish current bid, next minimum bid, and reserve status Yes / No / Unknown using fields actually available in the existing source data. Reserve Yes with an unavailable amount must say reserve amount undisclosed; do not derive a floor from retail price or next minimum bid.
Parent directly observed GSA listing 379280 at approximately 17:27 UTC: reserve Yes, amount not displayed, next bid $85. This is a timestamped observation, not a new cached source record or a lasting price guarantee.
Inspect existing adapter/cache support before implementation. If those fields are unavailable, name the exact data dependency and show honest unknown/undisclosed wording; do not invent values, add scraping, new providers, credentials or external fetch scope. Do not delay the Search Now placement correction for unsupported source enrichment.

## Boundaries and receipt
Authorized: source/code work and isolated staging acceptance in the existing approved workflow. The one-time live :8766 reload was completed under A-56; this message does NOT authorize another live reload. No other service/process changes, cache fetch, bid, spend, contact, installation or credential handling.
ACK this message, record the existing lane/queue scope and actual worker START separately, then publish final SHA, tests, screenshots and any blocker. Do not call an ACK or docs-only completion implementation completion.
