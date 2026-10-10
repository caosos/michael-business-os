# Owner clarification: verified opening/minimum allowed bid, not no-bid ambiguity

Michael asks to know the minimum allowed bid when a listing says "No bids yet", so he can assess possible low-cost component/scrap value. Capture this as a minimal serial listing-label/photo follow-on through the existing coordinator; do not inflate A60 or launch another worker. F137 satisfied estimated cached bid labels, NOT this new requirement.

Read-only evidence:
- Official GSA field reference https://gsa.github.io/auctions_api/fields names HighBidAmount and AucIncrement, no separate opening-minimum field. It describes Reserve as numeric award threshold, but actual recorded v2 cache reserve is boolean true; do not coerce that boolean into a dollar amount or equate reserve with opening bid.
- Existing lane02 fixture no-bid lot379294 has highBidAmount:null, aucIncrement:8, reserve:true. This proves neither an $8 nor $0 opening bid. Original listing https://www.gsaauctions.gov/auctions/preview/379294 was inaccessible to Arya's ordinary web tool; no current minimum verified.
- Use an explicit source-provided opening/minimum allowed bid only if available through existing permitted data/original-listing evidence, with provenance/asof. Keep distinct currentbid, estimated nextbid, minimum allowed bid and reserve threshold/flag.
- If unavailable, show "Opening/minimum bid unknown — check original listing" with its verified link. Never substitute zero, increment, retail estimate, reserve flag or guessed calculation. No claim the auction will accept an amount unless verified.

Valuation guidance: distinguish gross scrap/component estimate from an actual net yard pickup offer. Pickup availability, deductions, towing/transport, disposal, fees, title/paperwork, condition and recoverable weight remain explicit unknowns until supported. No guaranteed yard pickup or sale; no contacting/calling a yard, bidding or buying is authorized by this request. Private owner example amounts/budgets are omitted.

Existing coordinator should inspect current source constraints and return smallest bounded next scope, reusing source labels/photos follow-on. No new provider/account integration, authentication bypass, cache refresh, live deployment, billing expansion or duplicate work.
