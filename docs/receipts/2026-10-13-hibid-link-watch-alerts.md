# DealSniffer HiBid link watch and closing alerts

- Owner request: paste a HiBid lot link into My Bids, see a visible bid count, and receive escalating on-page alerts before the lot closes.
- Safety boundary: DealSniffer does not sign in to HiBid, fetch the lot page, determine authenticated winning state, or place a bid. The owner remains the only bidder.
- Public observation, 2026-10-13 about 15:39 America/Chicago: Wooley/HiBid Lot 34, CountyLine 32-Ton Towable Log Splitter; public high bid $800; 33 bids; next bid $825; scheduled close 18:10 America/Chicago. A bid in the final minute extends that lot by one minute.
- Implementation:
  - recognized HiBid lot URLs now canonicalize to a stable account-local watch with inferred title and source;
  - the My Bids navigation shows the active watch count and becomes urgent for OUTBID or the final 15 minutes;
  - the My Bids page updates countdowns in place and emits deduplicated 2h, 1h, 45m, 30m, 15m, 5m, 2m, and 1m on-page/browser alerts;
  - `localStorage` and `BroadcastChannel` suppress duplicate alerts across two open tabs;
  - this owner-authorized lot is seeded once as MANUAL with the observed close and price; a durable marker prevents later deployments from resurrecting it after the owner stops tracking.
- Acceptance evidence: focused tests, syntax checks, exact loaded revision, host HTTP proof, and browser screenshots are captured by the EliteDesk deployment run.
