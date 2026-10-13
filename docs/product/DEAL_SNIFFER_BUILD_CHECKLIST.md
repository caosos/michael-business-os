# DealSniffer — Active Product Checklist

Updated: Sunday, October 12, 2026 — 11:38 PM America/Chicago

This is the short working checklist. Completed engineering/watchdog history was moved intact to [the archive](archive/DEAL_SNIFFER_BUILD_CHECKLIST_through_2026-10-12.md). Receipts remain append-only in `docs/receipts/`.

## Product outcome

A listings-first marketplace for Conway-area resale opportunities, with real source links and photos, remembered location/radius/category/source choices, personal saved listings and bids, and ranked deal suggestions. DealSniffer never bids, buys, contacts sellers, or spends money.

## Working now on the EliteDesk

- [x] Marketplace is the primary UI; internal operator links are under the Admin dropdown.
- [x] Multi-select categories and sources use checkboxes.
- [x] A visible **Apply filters** control applies several checkbox changes together.
- [x] **Search** is the only control that requests fresh Facebook data; filter, sort, view, quick-view, and page navigation use the loaded cache.
- [x] Facebook Marketplace is connected through Michael's Bright Data account.
- [x] Facebook records with missing locations remain usable as `distance UNKNOWN` and cannot crash the page.
- [x] Rental ads are excluded by default; searching explicitly for `rent` or `rental` can show them.
- [x] Source names are readable below the listing content rather than over photographs.
- [x] Every card has visible **View**, **Save**, and **× Hide** controls.
- [x] Pagination is 12 listings per page.
- [x] Desktop and mobile Chrome render the loaded revision.

Loaded proof:

- DealSniffer UI revision: `0970b6eb3edab88cceda266eb0771ee1fa49c6a2`
- Deployment commit: `0c1acfc46b703a7cb0a5c301a61ac251ec8a71ca`
- GitHub Actions proof: https://github.com/caosos/michael-business-os/actions/runs/38347267346
- EliteDesk observation: Sunday, October 12, 2026 — 11:38:29 PM America/Chicago
- Host: `127.0.0.1:8766`, HTTP 200, Chrome available
- Facebook cache: 20 real Facebook URLs and 20 photos; Bright Data credential configured

## Current work — in order

- [ ] **Accounts:** add Sign in with Google, per-user identity, and per-user city/ZIP/radius/preferences.
- [ ] **Notifications:** add a per-user DealSniffer alert address/forwarding path and email/browser notifications. Do not request Gmail mailbox access unless forwarding cannot meet the need.
- [ ] **Source onboarding:** add genuine alerts/imports for GovDeals, Public Surplus, HiBid/Wooley, Craigslist, and OfferUp; preserve original links and truthful connection labels.
- [ ] **More local sources:** Blackmon, Nahlen, AuctionZip, liquidation/pallet sellers, estate and bin-store/event intelligence, plus authorized official feeds where available.
- [ ] **My Bids:** connected or imported source evidence, item, user's bid/max, current bid if known, close time, status, original link, and next action.
- [ ] **Suggestions:** buy/max-bid, repair allowance, resale, profit, turnover, distance, reasoning, and uncertainty; include pallet-specific economics.
- [ ] **Public delivery:** HTTPS domain, Google OAuth production configuration, privacy disclosures, and a multi-user deployment path.

## Michael's actions

Nothing is needed to keep the current Marketplace running.

For the next account milestone, Michael will need to choose the public DealSniffer domain and approve the Google Cloud OAuth app identity. Source accounts and saved-alert subscriptions remain owned by each user; no one gives DealSniffer a Facebook, Instagram, auction-site, or marketplace password.

## Connection labels

Use only: `LIVE CONNECTED`, `EMAIL CONNECTED`, `IMPORTED`, `MANUAL`, `NOT CONNECTED`, or `BLOCKED`. Fixtures and screenshots never count as live.
