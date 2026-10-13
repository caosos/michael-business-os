# DealSniffer — Active Product Checklist

Updated: Tuesday, October 13, 2026 — 12:07 AM America/Chicago

This is the short working checklist. Completed engineering/watchdog history remains intact in [the archive](archive/DEAL_SNIFFER_BUILD_CHECKLIST_through_2026-10-12.md). Receipts remain append-only in `docs/receipts/`.

## Product outcome

A listings-first marketplace for Conway-area resale opportunities, with real source links and photos, remembered location/radius/category/source choices, personal saved listings and bids, ranked deal suggestions, and a human-reviewed selling path. DealSniffer never bids, buys, contacts sellers, publishes a seller listing, or spends money without separate owner authorization.

## Proven working now on the EliteDesk

- [x] Customer navigation is limited to **Browse, Saved, My bids, Sell, Settings**. Queue, Wanted, Intake, receipt ledger, DRY-RUN, system state, and other operator controls are absent from customer pages.
- [x] Marketplace sources and categories use independent checkboxes; several may be selected together and applied with one control.
- [x] Search is separate from filtering. Bright Data Facebook retrieval is configured; the latest host proof contains 20 Facebook URLs and 20 photos for the `trailer` / `72032` / 30-mile provider query.
- [x] Loaded cards show photos, readable source names, View, Save, Hide, and responsive desktop/mobile layouts. The observed owner page showed 10 listing cards from Facebook Marketplace and regional auction sources.
- [x] Per-account preference storage and Settings UI exist for city/ZIP, radius, and categories. Local owner mode preserves Michael's existing choices; a new authenticated account does not inherit them.
- [x] My Bids supports manual, imported-listing, and verified email-alert records with source, original link, bid/max, current bid when known, closing, status, next action, and provenance. It does not log into a source account.
- [x] Per-account opaque vendor-alert and buyer/seller-contact addresses are derived, but truthfully remain **NOT CONNECTED** until real mail-provider routing and delivery receipts exist.
- [x] The Sell page accepts owner/authorized-representative/scout submissions into a review-only inbox. It does not publish, contact an owner, promise a sale, or start an auction.
- [x] Google account/session primitives and strict configuration checks exist. Google sign-in remains **NOT CONFIGURED** until public-domain, HTTPS, Google-client, callback, and consent requirements are completed.

Loaded proof:

- DealSniffer UI revision: `2a8cd4d38a844b4d909f7ebad0cbdc6ec75bf3ef`
- Deployment commit: `937db08706f4eb1bb4dd2abfd2e6e589363f23d4`
- GitHub Actions proof: https://github.com/caosos/michael-business-os/actions/runs/38349536811
- EliteDesk observation: Tuesday, October 13, 2026 — 12:05:11 AM America/Chicago
- Host: `127.0.0.1:8766`, HTTP 200, Google Chrome available
- Browser proof: desktop 1440×900 and mobile 390×844
- Focused account/delivery/bid/sell/settings/market tests: 51 passed

## Current work — in order

- [ ] **Domain and Google prerequisites:** finish `dealsniffers.com` registration/DNS, verify the domain in Google Search Console, publish HTTPS home/privacy/terms pages, and configure the Google OAuth brand, authorized domain, client, and callback.
- [ ] **Public multi-user delivery:** replace local-owner-only operation with production sessions and a database that enforces account isolation for preferences, saved/hidden listings, bids, contacts, and seller submissions.
- [ ] **Mail delivery:** configure DNS/MX and a mail provider for the opaque vendor-alert/contact addresses; prove inbound routing and outbound delivery with real receipts before changing `NOT CONNECTED` / `NOT ACTIVE`.
- [ ] **Source onboarding:** add genuine alerts/imports for GovDeals, Public Surplus, HiBid/Wooley, Craigslist, and OfferUp; preserve original links and truthful connection labels.
- [ ] **More local sources:** add Nahlen, AuctionZip, liquidation/pallet sellers, estate and bin-store/event intelligence, plus authorized official feeds where available.
- [ ] **My Bids live evidence:** connect authorized source-alert/import paths and prove updates without requesting or storing source-account passwords.
- [ ] **Suggestions:** show buy/max-bid, repair allowance, resale, profit, turnover, distance, reasoning, uncertainty, and pallet-specific economics.
- [ ] **Selling workflow:** add durable production storage, photo upload, reviewer tools, seller agreements, and explicit human approval gates before any listing publication or outreach.

## Michael's next action

Nothing is needed to keep the current EliteDesk Marketplace running.

After GoDaddy shows `dealsniffers.com` as active, add the Google Search Console TXT verification record in GoDaddy DNS. Do not paste Google OAuth client secrets, Facebook credentials, source passwords, or mail-provider secrets into GitHub or chat.

## Connection labels

Use only: `LIVE CONNECTED`, `EMAIL CONNECTED`, `IMPORTED`, `MANUAL`, `NOT CONNECTED`, or `BLOCKED`. Fixtures, configuration, and screenshots alone never count as live.
