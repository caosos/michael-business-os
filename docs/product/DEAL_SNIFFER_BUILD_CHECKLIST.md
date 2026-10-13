# DealSniffer — Active Product Checklist

Updated: Tuesday, October 13, 2026 — 11:40 AM America/Chicago

This is the short working checklist. Completed engineering/watchdog history remains intact in [the archive](archive/DEAL_SNIFFER_BUILD_CHECKLIST_through_2026-10-12.md). Receipts remain append-only in `docs/receipts/`.

## Product outcome

A personalized local-deal marketplace, beginning in Conway. It covers resale inventory and auctions **plus** everyday offers such as meat and groceries, restaurants, fuel, automotive service, entertainment, retail, local services, liquidation and wholesale. Every deal needs a real source/vendor, price and unit, location, freshness or expiration, availability, and honest uncertainty. DealSniffer never bids, buys, contacts sellers, publishes an offer, or spends money without separate owner authorization.

## Proven working now on the EliteDesk

- [x] Customer navigation is limited to **Browse, Saved, My bids, Sell, Settings**. Queue, Wanted, Intake, receipt ledger, DRY-RUN, system state, and other operator controls are absent from customer pages.
- [x] Marketplace sources and categories use independent checkboxes; several may be selected together and applied with one control.
- [x] Search is separate from filtering. Bright Data Facebook retrieval is configured; the latest host proof contains 20 Facebook URLs and 20 photos for the `trailer` / `72032` / 30-mile provider query.
- [x] The large search bar now explicitly submits its current text with the selected filters on click or Enter. Loaded host proof retained a guaranteed-no-match query in the field and changed the lineup to **0 results found** instead of leaving the prior cards onscreen.
- [x] The deployment proof can no longer overwrite Michael's remembered filters. Repair run 38430391700 succeeded at 11:26 AM America/Chicago on October 13, restored the actual saved owner choices, loaded 11 listings with photos, and left the search field clear.
- [x] Loaded cards show photos, readable source names, View, Save, Hide, and responsive desktop/mobile layouts. The observed owner page showed 10 listing cards from Facebook Marketplace and regional auction sources.
- [x] Per-account preference storage and Settings UI exist for city/ZIP, radius, and categories. Local owner mode preserves Michael's existing choices; a new authenticated account does not inherit them.
- [x] Customer-owned preferences, saved/hidden records, bid watches, mail delivery receipts, and seller submissions resolve through an opaque account storage key; customer form data cannot select another account.
- [x] My Bids has its own usable page and supports manual, imported-listing, and verified email-alert records with source, original link, bid/max, current bid when known, closing, status, next action, and provenance. It does not log into a source account.
- [x] Per-account opaque vendor-alert and buyer/seller-contact addresses are derived, but truthfully remain **NOT CONNECTED** until real mail-provider routing and delivery receipts exist.
- [x] Signed raw mail-delivery receipt validation, replay protection, account routing, and delivered/failed proof storage exist. No provider is claimed connected without a genuine receipt.
- [x] The Sell page accepts authority-attested owner/authorized-representative/scout submissions into an account-scoped, append-only review inbox. It validates public URLs and upload metadata, and does not publish, contact an owner, promise a sale, or start an auction.
- [x] **F-166 — broader local-deal network LIVE_VERIFIED:** implementation `e4bef62c3dd217e33573e74483d7a66a403e6e00` adds selectable Meat & Groceries, Restaurants & Prepared Food, Fuel & Automotive, Entertainment & Tickets, and Retail & Local Services categories while preserving Michael's resale-focused defaults. It adds an account-isolated, append-only `Advertise a local deal` form for price/unit, regular price, availability, location, start/expiration, official link, business authority, contact consent, and a freshness commitment. All submissions remain `REVIEW_PENDING`, unpublished, and unverified. Run 38433431736 succeeded; the loaded page was visually inspected at desktop 1440×1000 and mobile 390×1200. This proves the intake and controls, not a connected vendor feed.
- [x] Public Home, Privacy, and Terms pages exist. The Google OAuth path implements state, nonce, PKCE, signed sessions, and Google ID-token/JWK validation with only `openid email profile`; it remains **NOT CONFIGURED** until the external prerequisites are supplied and proven.
- [x] Settings now gives truthful setup/import instructions for GovDeals, Public Surplus, HiBid/Wooley, Craigslist, OfferUp, Nahlen, AuctionZip, Half Off Wholesale, NorthBay, and Bargain Brothers. Setup links never upgrade a source's evidence state.

Loaded proof:

- DealSniffer UI revision: `e4bef62c3dd217e33573e74483d7a66a403e6e00`
- Deployment commit: `cec6c089f606e9598e1dafa8afd3827ecd53c5d4`
- GitHub Actions proof: https://github.com/caosos/michael-business-os/actions/runs/38433431736
- Proof artifact: https://github.com/caosos/michael-business-os/actions/runs/38433431736/artifacts/11830939381
- EliteDesk observation: Tuesday, October 13, 2026 — 11:49:01 AM America/Chicago
- Host: `127.0.0.1:8766`, HTTP 200, Google Chrome available
- Browser proof: Marketplace desktop 1440×900/mobile 390×844, Settings desktop, My Bids mobile, and Advertise a local deal desktop 1440×1000/mobile 390×1200
- Facebook provider proof: Bright Data credential configured; 20 original Facebook URLs and 20 photos in the provider cache
- Focused account/OAuth/delivery/source/bid/sell/settings/market tests: 94 passed, 2 skipped
- Search submission regression suite: 41 passed, 1 skipped

## Current work — in order

- [ ] **Public launch prerequisites:** point `dealsniffers.com` at an HTTPS host, add the Google Search Console TXT record, configure the OAuth brand/client/callback, and prove a real Google sign-in. The domain is registered but currently resolves to GoDaddy parking; no TXT record is present.
- [ ] **Production multi-user storage:** move the now account-isolated local records to a production database/session deployment and prove two real accounts cannot read or mutate one another.
- [ ] **Mail and live-source proof:** configure DNS/MX and a mail provider, then prove genuine inbound alerts and outbound delivery for GovDeals, Public Surplus, Craigslist, HiBid/Wooley, and every source promoted beyond `MANUAL`, `NOT CONNECTED`, or `BLOCKED`.
- [ ] **Broader inventory:** add authorized current item/event data for Nahlen, AuctionZip, liquidation/pallet sellers, estate sales, and bin-store/restock intelligence while preserving original links and source timestamps.
- [ ] **Decision tools:** complete ranked Suggestions with buy/max-bid, repair allowance, resale, profit, turnover, distance, reasoning, uncertainty, and pallet-specific economics; then prove My Bids changes from a real connected alert/import.
- [ ] **Production selling path:** add durable production storage, actual photo upload, reviewer tools, seller agreements, and explicit human approval gates before any listing publication or outreach.
- [ ] **Personalized morning feed:** rank fresh deals per account using explicit categories, radius, search/filter choices, saves, hides, `More like this`, `Less like this`, and later privacy-reviewed view/redemption signals. Show `Why you're seeing this`, permit hide/reset, enforce expiration, and never let learned ranking bypass a hard filter. The chat morning brief is scheduled daily around 8:00 AM America/Chicago beginning October 14; the in-product feed still needs connected everyday-deal sources.
- [ ] **Vendor deal network:** build verified vendor onboarding, reviewer approval, scheduled/daily offer updates, freshness expiry, inventory/claim limits, redemption proof, abuse controls, and business reporting before approved submissions can enter the live feed.
- [ ] **F-167 — interactive promotions:** ship deterministic flash claims first (for example, first three eligible claims after 3:12 PM). Add claim inventory, one-per-person rules, unique redemption codes, vendor confirmation, expiration, waitlist/claimed-out states, notifications, audit receipts, and fraud/rate controls. A scratch-style reveal may be visual, but chance-based prizes remain BLOCKED pending jurisdiction-specific legal review, official rules, eligibility/age/territory, odds and prize disclosures, a no-purchase entry path where required, tax treatment, and vendor funding. Never accept consideration for a chance to win.

## Michael's next action

Nothing is needed to keep the current EliteDesk Marketplace running.

Point `dealsniffers.com` at the chosen public HTTPS host and add the Google Search Console TXT verification record in GoDaddy DNS. Then create the Google OAuth web client for the final HTTPS callback. Do not paste Google OAuth client secrets, Facebook credentials, source passwords, or mail-provider secrets into GitHub or chat.

## Connection labels

Use only: `LIVE CONNECTED`, `EMAIL CONNECTED`, `IMPORTED`, `MANUAL`, `NOT CONNECTED`, or `BLOCKED`. Fixtures, configuration, and screenshots alone never count as live.
