# DealSniffer — Active Product Checklist

Updated: Tuesday, October 13, 2026 — evening, America/Chicago (owner direction: no paid listing providers; DS-SOURCE-01)

This is the short working checklist. Completed engineering/watchdog history remains intact in [the archive](archive/DEAL_SNIFFER_BUILD_CHECKLIST_through_2026-10-12.md). Receipts remain append-only in `docs/receipts/`.

## Product outcome

A personalized local-deal marketplace, beginning in Conway. It covers resale inventory and auctions **plus** everyday offers such as meat and groceries, restaurants, fuel, automotive service, entertainment, retail, local services, liquidation and wholesale. Every deal needs a real source/vendor, price and unit, location, freshness or expiration, availability, and honest uncertainty. DealSniffer never bids, buys, contacts sellers, publishes an offer, or spends money without separate owner authorization.

## Proven working now on the EliteDesk

- [x] Customer navigation is limited to **Browse, Saved, My bids, Sell, Settings**. Queue, Wanted, Intake, receipt ledger, DRY-RUN, system state, and other operator controls are absent from customer pages.
- [x] Marketplace sources and categories use independent checkboxes; several may be selected together and applied with one control.
- [x] Search is separate from filtering. **Superseded Oct 13 (owner direction): paid Facebook retrieval through Bright Data is OFF.** The listings it retrieved earlier remain as a labelled HISTORICAL CACHE with their retrieval time; no Search, Run, refresh, deploy or credential can start a paid request (DS-SOURCE-01).
- [x] The large search bar now explicitly submits its current text with the selected filters on click or Enter. Loaded host proof retained a guaranteed-no-match query in the field and changed the lineup to **0 results found** instead of leaving the prior cards onscreen.
- [x] The deployment proof can no longer overwrite Michael's remembered filters or My Bids. **Corrected Oct 13:** the one-time `PRE_TEST_PREFS` restore had stayed in the workflow and copied the 03:30Z snapshot over the owner file on every deploy (seen in P0). DS-SOURCE-01 removed it; run 38504661130 left the owner file byte-identical.
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

## Owner direction — October 13, 2026: a low-cost local buying-opportunity platform

Recorded from Michael's DS-SOURCE-01 brief. It amends the earlier Facebook/Bright Data plan; this checklist stays the single plan.

**Cost rule.** DealSniffer does not pay for listings: no scraping subscriptions, third-party listing APIs, data feeds or provider recharges, and no new billing commitments. Conserve AI subscription usage. Paid-provider requests are denied in code (S1, below).

**Goal.** Genuine local buying opportunities from several sources on one screen. Each opportunity shows, when genuinely known: source and original URL; photo where permitted; asking price or observed auction price; location and distance; observed time and freshness; estimated all-in acquisition cost (price, fees, transport); estimated repairs and their cost; likely resale range; expected profit; estimated time to sell; uncertainty and provenance. Anything missing is shown as **UNKNOWN**. Never invent photos, prices, expirations, distances, inventory, availability or sold comparables.

**Primary markets.** Around Conway, AR, default about **50 miles**. First: utility and equipment trailers; donor trailer frames and boat trailers; small engines and lawn equipment; tools and machinery; outboard motors and related equipment. A farther item needs enough extra margin to pay for travel, fuel and time.

**Economics.** Optimize actual expected profit, all-in acquisition cost, return on deployed capital, time to cash, repair effort and uncertainty, travel cost and capital turnover. Doubling the money is preferred, not required; a quick ~$400 profit can justify a larger purchase when capital turns fast. No rigid universal profit minimum.

### Source roadmap (documented; only S1 is implemented)

- [x] **S1 — Eliminate paid-provider execution** in the loaded app and the deploy (DS-SOURCE-01, below; two out-of-app paths remain listed there).
- [ ] **S2 — Prove one free, authorized source live.** Fresh records from one existing free route visible in the loaded app; prefer the existing GSA Auctions official-API adapter if its current terms and operation allow.
- [ ] **S3 — Permitted per-source integrations:** Craigslist, Facebook Marketplace, local auctioneers, GovDeals, Public Surplus, others. For each: verify current access terms; keep discovery, caching, display and republication separate; browser access is not API or scraping permission; never bypass logins, CAPTCHAs or blocks; owner approval before any outreach or credential.
- [ ] **S4 — Free auctioneer data:** CSV files, catalog exports, official feeds and permission-based inventory sharing. Keep auction EVENTS distinct from individual LOTS.
- [ ] **S5 — Reuse owner-entered finds and reviewed vendor imports,** keeping MANUAL / IMPORTED attribution. A manually saved link is not automatic discovery.
- [ ] **S6 — Remember several selected sources, categories, location and radius per account.**
- [ ] **S7 — "Auction ending within" filter** in hours or days.
- [ ] **S8 — Keep observing tracked auctions after OUTBID** through a verified final outcome where legitimate evidence exists (P1-01 manual history is the start).
- [ ] **S9 — Keep asking prices, observed high bids, estimated valuations and verified realized prices as separate fields.**

**Source acceptance (every future source task).** A genuinely current record renders in the LOADED Marketplace with original URL, source identity, observed timestamp, observed price when known, and real location and photo when available; missing fields read UNKNOWN. A repeat refresh creates no duplicates. Verify remembered source filters, account isolation, the loaded revision, and desktop and mobile browser evidence. Record the source and the exact record count. A cache does not prove live discovery.

### DS-SOURCE-01 — no-paid-provider enforcement (acceptance)

**15/15 PASS — loaded on the EliteDesk.** Release lane 06 `a9cabb070a6ac2b625992afef3c59d8996750a0e` (built on the P0 release `c6bd4b8`; the undeployed P1-01 is NOT included), merged into the lane branch as `174cf8b`; deploy commit `7ae1672`; run https://github.com/caosos/michael-business-os/actions/runs/38504661130 (success); `var/lanes/agent-06/ARTIFACT` sha=a9cabb0…; `reload_ui.sh --verify-only 8766` VERIFY OK. Proof artifact: `credential_configured=true`, `paid_provider_requests=DENIED`, 180 historical Facebook records (last retrieved 2026-10-13 21:07 UTC, before this task), 76 within 30 mi, 50 rendered with photos. Facebook cache file unchanged (mtime 16:07:01 CDT) through the deploy and every browser test; no pending marker; no provider line in `var/ui.log`. Owner `market_prefs.json` byte-identical across the deploy (1 bid, filters kept).

- [x] Initial Marketplace load — Chrome: Facebook row "historical cache · retrieval off", still selectable; test: zero attempts
- [x] Clicking Search — Chrome, Facebook ticked, Search clicked (go=1): 13 results, 12 Facebook cards stamped "cached 2026-10-13", cache unchanged
- [x] Pressing Enter — Chrome: "trailer" + Enter, results updated, nothing pending
- [x] Running a saved search — HTTP test against a real test server (`?run=<id>`), zero attempts. The live account has no saved search, so no live click was possible
- [x] Search all sources — Chrome: All sources + Search (go=1), 13 results, nothing pending
- [x] Selecting Facebook — Chrome and test
- [x] Refreshing — Chrome F5 on a go=1 page, unchanged; test reloads
- [x] Direct backend refresh — `market_facebook.load(refresh=True, client=…)` and `market_sources.load_source(..., _facebook_refresh=True)` call nothing
- [x] Direct client — `BrightDataClient(...)`, an instance that skipped `__init__`, `_call`, `search`, `search_many`, `resume` and `_urllib` all raise `PaidProviderDenied` before any request
- [x] Deployment workflow and proof paths — density loop and provider probe removed; a static test forbids them; the real run printed `paid_provider_requests=DENIED`
- [x] Configured credentials cannot bypass — env keys, key file and enable-style variables set in tests; host has a configured key and nothing was sent
- [x] Historical cache read-only and attributed — bytes and mtime unchanged in tests and on the host; source, retrieval time and age shown; registry state NOT CONNECTED
- [x] Ordinary filters still work — keyword, source, category and radius changes in Chrome; full suite has no new failures
- [x] Account isolation — test_account_isolation, test_accounts, test_account_settings, test_account_delivery pass on the release tree
- [x] Desktop and mobile — Chrome 1870 px desktop (screenshot `/tmp/claude-chrome-screenshots-Empe8q/screenshot-1791947457723-3.jpg`); headless Chrome 390×844 touch on the loaded app: label shown, Search tapped (go=1), page width 390 = viewport

**Still able to call Bright Data on this host (not changed by this task):**
- Lane 02 `mbos_discovery.adapters.BrightDataFbMarketplaceAdapter` through the manual `tools/b44_live_smoke.py` (another builder's lane; not imported by the app, the deploy or any scheduled job).
- The stage server on port 8790 (tmux `mbos-stage`, another session's, older lane 06 `bbc80ec`) still has the old Search-refresh code. Stopping it is the smallest fix.

## P0 — Marketplace acceptance (authoritative progress)

Task: P0 Marketplace acceptance, run by Agent 01 (DealSniffer). Started Tuesday, October 13, 2026 — 5:46 PM America/Chicago.
Tested against the LOADED app at `127.0.0.1:8766`: lane 06 `72d7a02721eaf728b6722ac58f4e846b72c2fa6a`, lane 02 `cda867347505ac8e27945b2aa1ae6a3823939ae2`.
Evidence: real clicks and typing in Claude in Chrome on the owner's desktop, plus headless Google Chrome (Playwright) at 390×844 for mobile, because the desktop Chrome window cannot shrink to phone width.
A checkpoint counts only when browser evidence proves it. Progress = verified PASS / 21.

**Status: 21/21 PASS = 100% (verified on the loaded app 9f5e14a, Tuesday, October 13, 2026 — 6:47 PM America/Chicago).** Initial assessment was 20/21 (95.2%); the first defect, 06, has been fixed and deployed.

- Fix: lane 06 `9f5e14ad063a7ae995d73973dfa43825d5ed4ac1`. When a radius applies, listings whose distance cannot be measured leave the grid and every facet count, and the page says "N listings with an unknown location left out … Choose Any to include them". Any radius and By State mode still show them. Files: `operator_ui/market_routes.py`, `operator_ui/market_search.py` (`radius_applies`), `operator_ui/market_view.py`, `tests/test_market_p0_distance.py` (4 tests; 2 fail on 72d7a02 and pass on the fix).
- Lane 06 full suite: on the fix, 98 failed / 673 passed / 1 skipped. On live baseline 72d7a02 (run concurrently), 120 failed / 648 passed. No new failures: every failure on the fix also fails on the baseline. These pre-existing failures are stale UI tests and are not part of P0-06.
- Deploy: https://github.com/caosos/michael-business-os/actions/runs/38485906872 (success, `refresh_marketplace: false`, so no paid provider call). The EliteDesk ARTIFACT shows `sha=9f5e14ad063a7ae995d73973dfa43825d5ed4ac1`; `reload_ui.sh --verify-only 8766` is OK; deploy proof: Facebook 76 filtered at 30 mi, 50 rendered, 50 photos.
- Re-verified after deploy:
  - **Desktop (Claude in Chrome):** Conway, 10 mi, Wooley + Facebook, Tools + Trailers gave 11 results, maximum 8.5 mi, 0 unknown cards, note "5 listings with an unknown location left out". Any radius gave 72, with the unknowns back. 50 mi, all sources, all categories gave 125, 50 per page; bottom page 2 shows 51–100, no overlap, filters kept, 0 unknown. Settings → Browse kept the filters.
  - **Mobile (headless Chrome 390×844, touch):** Filters drawer → 10 miles → Apply gave 11 results, maximum 8.5 mi, 0 unknown, page width 390 = viewport, 1 column, bottom pager fits.
- Michael's remembered Marketplace choices were restored byte-for-byte to the pre-test copy taken at 5:46 PM.

Open P0 finding (not fixed; separate task): every deploy copies `var/lanes/agent-06.prev-20261013T033042Z/var/market_prefs.json` over the owner's preference file (the workflow's `PRE_TEST_PREFS` step). So a release resets Michael's remembered filters to a 03:30Z snapshot. Observed: after run 38485906872 the page loaded at 41 mi with the old selections until the pre-test copy was restored by hand.

- [x] 01 Marketplace loads: /market HTTP 200, the grid renders, and the remembered filters are restored.
- [x] 02 Keyword search: typing `trailer` and pressing Enter gave 25 results, every title a trailer.
- [x] 03 Multiple sources: All unticked, Wooley + Facebook ticked: 71 results; cards from Facebook (49) and Wooley (1) only.
- [x] 04 Multiple categories: Tools + Trailers only: 48 results, all trailers or tools.
- [x] 05 Combined source + category: Wooley + Facebook with Tools + Trailers: Facebook only (the Wooley event is neither).
- [x] 06 Distance filtering: **FIXED and verified** (see above). Was FAIL: Conway AR, 10 mi: 16 results, of which 5 were 'distance UNKNOWN' Facebook listings (Hot Springs National Park ×3, Cleveland, Prim). At 25 mi, 1 of 13 was unknown. Cause: a listing whose town is not in the offline gazetteer has no distance, and the page appended these 'not verified' rows to the in-radius results.
- [x] 07 Min/max price: $100–$1,000 gave 19 results, prices from $100 to $1,000.
- [x] 08 Listing type: Auction event: 17 (Wooley 1, Wilson 10, Blackmon 6, all events). Fixed price: 127, all Facebook fixed price.
- [x] 09 Rentals excluded: the default lineup (132 results, 3 pages) has no rental titles. The 4 rental listings in the Facebook cache appear only when the owner searches `rent` (deliberate: `wants_rentals`).
- [x] 10 Fifty per page: 71 / 117 / 127 results show 50 cards on page 1; page 3 of 127 shows 27.
- [x] 11 Top pagination: top `2` gave "51-100 of 127 · Page 2 of 3", with no overlap with page 1.
- [x] 12 Bottom pagination: bottom `3` gave "101-127 of 127 · Page 3 of 3".
- [x] 13 Page change keeps filters: Wooley + Facebook, 13 categories (Land off), max $5,000, 50 mi: identical on page 2 (116 results).
- [x] 14 Photos: 50 of 50 cards rendered loaded images (Facebook 48, Wooley 1, Wilson 1); no 'No photo' placeholders.
- [x] 15 Source attribution: each card's label matches its record id and detail route (facebook→Facebook Marketplace, wooley→Wooley Auctioneers, wilson→Wilson Auctioneers). The Sources panel labels GovDeals, Public Surplus, Craigslist and eBay `not connected`, HiBid website `blocked`, and OfferUp, Nahlen and finds `manual`.
- [x] 16 Zero results: `qqzxnomatch` gave "0 results found" and the zero-results message, with no stale cards.
- [x] 17 Persist after refresh: Facebook only, Trailers only, 25 mi, then F5: the same, 13 results.
- [x] 18 Persist after navigation: Settings → Browse: the same filters.
- [x] 19 Persist across sessions: closed the tab and opened a new tab group (no cookies): the same filters (server-side owner preferences).
- [x] 20 Desktop layout: 1870 px window: 4-column grid, sidebar 253 px, no horizontal overflow.
- [x] 21 Mobile layout: 390×844 touch: 1 column, page width 390 = viewport (no horizontal scroll). The Filters drawer opens with a tap; tapping a category and Apply filters works; the bottom pager fits.

Note: one paid Bright Data job was started during testing. Clicking **Search** (rather than pressing Enter) sends `go=1`, which starts a provider search, for the test query `qqzxnomatch` at 6:07 PM. The Facebook cache is sharded per query, so existing listings were not affected. Later tests used Enter or Apply filters only.

## P1-01 — Auction history in My Bids (issue #2)

Lane 06 `ef18f91` (on top of the P0 release `9f5e14a`). **Status: built and accepted on staging. NOT deployed** (owner decision pending, see the hold note below).

- [x] Preserve existing watch records and bids (re-marking keeps history; pre-P1 records keep their snapshot as observation 1)
- [x] Watches stay active after OUTBID (counted in the nav)
- [x] Timestamped observed high bids (stated time, or "time you entered it" when not stated)
- [x] Observed bid counts
- [x] Source and provenance on every observation (MANUAL / SNAPSHOT / CONNECTED; source_account_access NONE)
- [x] Closing-time changes and extensions ("closing extended 1m: 6:10 → 6:11 PM CT")
- [x] Owner-entered historical observations (backdated entries sort into place and never replace current values)
- [x] Verified final selling price
- [x] History kept after bidding closes
- [x] Chronological history in My Bids
- [x] Price changes and bid-count deltas
- [x] Gaps between observations marked (GAP rows; intermediate bids never invented)
- [x] Manual data distinguished from connected evidence (BidWatchStore receipts, read-only)
- [x] Account isolation (per-account prefs; BidWatchStore now uses its own per-account file)
- [x] Regression tests: 11 new + 17 existing bid tests pass; full suite 82 failed / 700 passed / 1 skipped, every failure already in the P0 list
- [x] Desktop + mobile browser journey on STAGING (headless Chrome 1440×900 and 390×844 touch): 3 observations, 2 gaps, +$175, no horizontal scroll. Claude in Chrome reaches only port 8766, so it cannot open staging
- [ ] Deploy to EliteDesk
- [ ] Loaded revision verified

**Hold:** the deploy workflow's `PRE_TEST_PREFS` step copies `var/lanes/agent-06.prev-20261013T033042Z/var/market_prefs.json` over the owner's prefs on every run. My Bids records live in that file, so a deploy rolls the owner's bids and history back to the 03:30Z snapshot. Removing those two lines and backing up the owner's live prefs were both refused by the auto-mode permission check, so the deploy waits for the owner.

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

Use only: `LIVE CONNECTED`, `EMAIL CONNECTED`, `IMPORTED`, `MANUAL`, `HISTORICAL CACHE`, `NOT CONNECTED`, or `BLOCKED`. Fixtures, configuration, caches and screenshots alone never count as live. `HISTORICAL CACHE` means records retrieved earlier through a route that is now switched off: readable, attributed and dated, never live.
