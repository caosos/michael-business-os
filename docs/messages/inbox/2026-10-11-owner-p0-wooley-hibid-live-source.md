# OWNER DELIVERY — P0 real Wooley / HiBid listings in DealSniffer

- **Delivered:** 2026-10-11T23:48:30Z
- **Owner:** Michael
- **Coordinator:** existing Agent 01 only
- **Priority:** P0, next eligible source objective
- **Protocol:** one bounded item at a time; DELIVERED -> ACK -> WORKING -> DONE/NEED; no duplicate coordinator or worker
- **Owner wording / objective:** "I want other platforms. I want to be able to see deals from that place and others, Wooly Auction." Michael wants real local auction listings in DealSniffer, not fixture data, manual link entry, or another source plan.

## Reconciliation at delivery

- F-143 is LIVE_VERIFIED at `315ddfa`.
- F-144 + F-145 are STAGING_ACCEPTED at `179bd62cec8c6e6db5eb16760441321349e3d619` and await the already-documented combined UI reload. That release NEED does **not** block compatible source implementation.
- B-12 live GovDeals/PublicSurplus email acceptance remains blocked on mailbox prerequisites.
- Lane 02 B-23 already provides fixture-only Arkansas auction normalization. Reuse it; do not create a competing source architecture.
- Current product truth: GSA is the only live connected Marketplace source. F-141 manual links do not count as discovery.

## Owner source decision

Michael authorizes read-only discovery from publicly accessible Wooley Auctioneers / HiBid listing pages for DealSniffer. This authority covers reading public auction and lot data required for discovery and showing the original source link. It does **not** authorize login automation, credential use, bid placement, seller contact, bypassing access controls, or inventing data.

The immediate real target is:
- Wooley Auctioneers
- T.J. Bruck Estate Heavy Equipment & Machinery Auction
- Perryville, Arkansas
- scheduled close Tuesday 2026-10-13 at 6:00 PM CDT
- example acceptance lot: Lot 34, CountyLine 32-Ton Towable Log Splitter

## Claim

Create/reconcile one P0 bounded vertical item, suggested ID **B-26/F-146 — Wooley/HiBid real read-only source**, owned by Agent 01 and executed serially through existing lanes. Claim one worker at a time. Begin with the discovery/source implementation needed to convert the B-23 fixture seam into an explicitly enabled read-only live route for this source; then wire that exact output into Marketplace as the next task boundary. Do not launch parallel duplicate source workers.

## Acceptance test

DONE requires all of the following evidence:

1. A real source response is observed and archived privacy-safely; exact retrieval route, HTTP/result status, timestamp, and source URL are in the receipt.
2. At least the current Wooley/Perryville auction and Lot 34 are discovered from the real source, not copied from a fixture or manually entered. Capture when the source provides it:
   - auctioneer/platform
   - title and lot number
   - current bid
   - bid count
   - closes_at
   - location
   - buyer premium
   - primary image URL
   - original auction/lot URL
   - observed_at/freshness
   Unknown fields remain UNKNOWN.
3. Results normalize through the existing B-23/source seam with stable source IDs and original-link provenance. Repeat fetch does not duplicate lots.
4. Source failure, stale data, or blocked access is shown honestly; no fixture is displayed as live.
5. Real Wooley/HiBid cards appear in an isolated `/market` staging run and respond to source, distance, category, keyword, price, and Search Now controls.
6. Agent 01 independently reviews code and runs focused tests plus actual Claude Chrome desktop/mobile checks. Include screenshots and exact pass/fail counts.
7. Only after clean verification, prepare one bounded release artifact/command. Do not silently replace the currently loaded service.
8. DONE receipt includes exact commits, tests/results, browser evidence, loaded state, host observation, user-visible result, cost if known, timestamp, and next queue item.

## If public retrieval is not supportable

Do not stop at a generic policy statement. Post a structured NEED with the exact observed technical or source restriction and the narrowest owner action. Continue compatible implementation: complete the reusable parser/normalizer against an archived real response when lawful and available, plus the Marketplace wiring and tests, while leaving the source status NOT CONNECTED until live proof exists.

## Ordered source queue after this item

Do not start these yet; record them as the next bounded candidates:

1. Expand the working HiBid route to Conway/Central Arkansas auctioneers and radius-based Arkansas lots, including Nahlen Liquidation and other Conway/nearby HiBid houses.
2. Wilson Auctioneers / Little Rock.
3. Blackmon Auctions / Arkansas equipment, truck, and trailer events.
4. AuctionZip Arkansas index.
5. Craigslist Little Rock/local listings through a separately approved supported route.
6. Facebook Marketplace through a separately supported user-account route; manual F-141 links remain distinct and do not count as connected discovery.

No action without a receipt. No receipt without provenance.
