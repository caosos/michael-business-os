# DealSniffer — Active Product Checklist

Updated: Tuesday, October 13, 2026 — 1:40 AM America/Chicago

This is the short working checklist. Completed engineering/watchdog history remains intact in [the archive](archive/DEAL_SNIFFER_BUILD_CHECKLIST_through_2026-10-12.md). Receipts remain append-only in `docs/receipts/`.

## Product outcome

A listings-first marketplace for Conway-area resale opportunities, with real source links and photos, remembered location/radius/category/source choices, personal saved listings and bids, ranked deal suggestions, and a human-reviewed selling path. DealSniffer never bids, buys, contacts sellers, publishes a seller listing, or spends money without separate owner authorization.

## Proven working now on the EliteDesk

- [x] Customer navigation is limited to **Browse, Saved, My bids, Sell, Settings**. Queue, Wanted, Intake, receipt ledger, DRY-RUN, system state, and other operator controls are absent from customer pages.
- [x] Marketplace sources and categories use independent checkboxes; several may be selected together and applied with one control.
- [x] Search is separate from filtering. Bright Data Facebook retrieval is configured; the latest host proof contains 20 Facebook URLs and 20 photos for the `trailer` / `72032` / 30-mile provider query.
- [x] Loaded cards show photos, readable source names, View, Save, Hide, and responsive desktop/mobile layouts. The observed owner page showed 10 listing cards from Facebook Marketplace and regional auction sources.
- [x] Per-account preference storage and Settings UI exist for city/ZIP, radius, and categories. Local owner mode preserves Michael's existing choices; a new authenticated account does not inherit them.
- [x] Customer-owned preferences, saved/hidden records, bid watches, mail delivery receipts, and seller submissions resolve through an opaque account storage key; customer form data cannot select another account.
- [x] My Bids has its own usable page and supports manual, imported-listing, and verified email-alert records with source, original link, bid/max, current bid when known, closing, status, next action, and provenance. It does not log into a source account.
- [x] Per-account opaque vendor-alert and buyer/seller-contact addresses are derived, but truthfully remain **NOT CONNECTED** until real mail-provider routing and delivery receipts exist.
- [x] Signed raw mail-delivery receipt validation, replay protection, account routing, and delivered/failed proof storage exist. No provider is claimed connected without a genuine receipt.
- [x] The Sell page accepts authority-attested owner/authorized-representative/scout submissions into an account-scoped, append-only review inbox. It validates public URLs and upload metadata, and does not publish, contact an owner, promise a sale, or start an auction.
- [x] Public Home, Privacy, and Terms pages exist. The Google OAuth path implements state, nonce, PKCE, signed sessions, and Google ID-token/JWK validation with only `openid email profile`; it remains **NOT CONFIGURED** until the external prerequisites are supplied and proven.
- [x] Settings now gives truthful setup/import instructions for GovDeals, Public Surplus, HiBid/Wooley, Craigslist, OfferUp, Nahlen, AuctionZip, Half Off Wholesale, NorthBay, and Bargain Brothers. Setup links never upgrade a source's evidence state.

Loaded proof:

- DealSniffer UI revision: `1fc7a27321d0ccc94e76bdc98a1adecd9d72a686`
- Deployment commit: `906d197572b43b0a47d85e0f740ce21681796e11`
- GitHub Actions proof: https://github.com/caosos/michael-business-os/actions/runs/38357681346
- Proof artifact: https://github.com/caosos/michael-business-os/actions/runs/38357681346/artifacts/11793407268
- EliteDesk observation: Tuesday, October 13, 2026 — 1:39:18 AM America/Chicago
- Host: `127.0.0.1:8766`, HTTP 200, Google Chrome available
- Browser proof: Marketplace desktop 1440×900/mobile 390×844, Settings desktop, and My Bids mobile
- Facebook provider proof: Bright Data credential configured; 20 original Facebook URLs and 20 photos in the provider cache
- Focused account/OAuth/delivery/source/bid/sell/settings/market tests: 94 passed, 2 skipped

## Current work — in order

- [ ] **Public launch prerequisites:** point `dealsniffers.com` at an HTTPS host, add the Google Search Console TXT record, configure the OAuth brand/client/callback, and prove a real Google sign-in. The domain is registered but currently resolves to GoDaddy parking; no TXT record is present.
- [ ] **Production multi-user storage:** move the now account-isolated local records to a production database/session deployment and prove two real accounts cannot read or mutate one another.
- [ ] **Mail and live-source proof:** configure DNS/MX and a mail provider, then prove genuine inbound alerts and outbound delivery for GovDeals, Public Surplus, Craigslist, HiBid/Wooley, and every source promoted beyond `MANUAL`, `NOT CONNECTED`, or `BLOCKED`.
- [ ] **Broader inventory:** add authorized current item/event data for Nahlen, AuctionZip, liquidation/pallet sellers, estate sales, and bin-store/restock intelligence while preserving original links and source timestamps.
- [ ] **Decision tools:** complete ranked Suggestions with buy/max-bid, repair allowance, resale, profit, turnover, distance, reasoning, uncertainty, and pallet-specific economics; then prove My Bids changes from a real connected alert/import.
- [ ] **Production selling path:** add durable production storage, actual photo upload, reviewer tools, seller agreements, and explicit human approval gates before any listing publication or outreach.

## Michael's next action

Nothing is needed to keep the current EliteDesk Marketplace running.

Point `dealsniffers.com` at the chosen public HTTPS host and add the Google Search Console TXT verification record in GoDaddy DNS. Then create the Google OAuth web client for the final HTTPS callback. Do not paste Google OAuth client secrets, Facebook credentials, source passwords, or mail-provider secrets into GitHub or chat.

## Connection labels

Use only: `LIVE CONNECTED`, `EMAIL CONNECTED`, `IMPORTED`, `MANUAL`, `NOT CONNECTED`, or `BLOCKED`. Fixtures, configuration, and screenshots alone never count as live.
