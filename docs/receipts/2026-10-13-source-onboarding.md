# DealSniffer source onboarding — 2026-10-13

## Implemented

- Extended the existing authoritative source registry with user setup metadata; no parallel registry was created.
- Added truthful setup entries for GovDeals, Public Surplus, HiBid/Wooley, Craigslist, OfferUp, Nahlen, AuctionZip, Half Off Wholesale, NorthBay Tool Liquidation Pallets, and Bargain Brothers.
- Added an **Add sources** section to Settings. It links only verified public source pages and tells the user whether to forward genuine alerts or paste an original listing URL.
- Extended **Your finds** so each named manual source can be selected. The exact original URL is retained, along with owner-import provenance and timestamps.
- Manual-source counts are source-specific. A manual import remains `MANUAL`; it never upgrades a source to `LIVE CONNECTED`.

## Honest connection state

- GovDeals, Public Surplus, and Craigslist have existing alert-parser seams, but remain `NOT CONNECTED` until a real mailbox read/receipt exists.
- HiBid alert parsing is `NOT IMPLEMENTED`; direct HiBid lot retrieval remains `BLOCKED` pending written permission.
- Wooley remains event-level only; lot number, current bid, and bid count are not inferred.
- OfferUp, Nahlen, AuctionZip, and the local liquidation/event candidates are `MANUAL`; DealSniffer does not log in or fetch their pages.
- NorthBay and Bargain Brothers have no stored official link because a current official source was not verified. Half Off Wholesale uses its public Little Rock page, but its inventory is still treated as manual store/pallet/event information rather than a live item feed.

## Verification

Focused tests cover registry metadata, honest state labels, per-account alert-address display, settings rendering, per-source counts, and exact URL/provenance retention. Compile and whitespace checks are required before integration.
