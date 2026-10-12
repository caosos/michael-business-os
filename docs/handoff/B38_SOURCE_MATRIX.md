# B-38 — Other apps where people sell stuff in Arkansas: source matrix (Agent 07, 2026-10-12)

Read-only research, no logins, no scraping, no bot-block evasion, no code. Pages were fetched once each through a summarising fetch tool, so quotes are the tool's quotes of the primary page; a legal reader should re-read the live page before any adapter ships. Provenance: **FACT** = stated on a primary page I fetched (URL + date given); **INFER** = my reading; **UNK** = not established (page unreachable, or only third-party sources). Owner goal (2026-10-12 ~14:30 CDT): GSA-style search across FB Marketplace, Craigslist and other selling apps, Arkansas first, later "wherever they log in".

## Route vocabulary
API = official documented API · ALERT = the platform's own saved-search / notification e-mail into the existing read-only mailbox seam (label DealSniffer/Alerts) · FEED = published RSS/feed · PERMISSION = automated access needs the platform's written permission · NO = terms prohibit automated access and no sanctioned route exists · MANUAL = owner pastes/shares (F-141).

## Matrix
| Source | Class | Route verdict | Cost | Arkansas coverage | Narrowest lawful route | Evidence |
|---|---|---|---|---|---|---|
| Craigslist | classifieds | ALERT | free | littlerock, fayar, fortsmith, texarkana, memphis, etc. | owner saved-search alerts (B-36); no page fetch | FACT (B12 doc, ToU Aug 16 2019) |
| Facebook Marketplace | classifieds | PERMISSION | n/a | strong | none verified; Meta written permission, or owner-authorised provider; MANUAL meanwhile | FACT (Meta terms eff. Oct 7 2024, per B12 doc) |
| OfferUp | classifieds | NO / UNK | n/a | present, unquantified | MANUAL only. Plain requests got 403 (B-34 research). Current ToS text NOT retrieved (offerupnow.com/terms redirects to the homepage; only a 2016 archived privacy policy was readable). No public API found | FACT 403; UNK terms |
| Mercari | national resale (shipped) | NO / UNK | n/a | none local (shipped goods) | skip for local deals; MANUAL comps only. ToS fetch returned 403; no official API found (search showed only third-party scrapers) | FACT 403; INFER |
| Poshmark | national resale (shipped) | NO | n/a | none local | do not connect. Terms 4(b) bar "copy, scrape, harvest, crawl or use any technology, software or automated systems" (v4.6, eff. June 3 2025) | FACT |
| Nextdoor For Sale & Free | neighbourhood | UNK → MANUAL | n/a | Conway/Little Rock neighbourhoods likely | needs login to see anything; terms URLs 404'd, no API for listings found. MANUAL. Ask Nextdoor only if owner wants it | UNK |
| Kijiji-style (Canada) | classifieds | N/A | n/a | none | out of scope; Arkansas analogues are Craigslist, FB, OfferUp | INFER |
| Trash Nothing | freecycle (free items) | API (registered app) | unstated | free-item groups, includes AR | register an app while logged in; REST/OpenAPI 2.0 v1.4. Auth conflict between aggregators (apiKey vs OAuth2). Terms (Apr 2 2025): "made available for your personal use only"; may not "resell or redistribute content ... other than by means made available by Trash Nothing" | FACT page + terms; auth UNK |
| HiBid (Wooley, Wilson-simulcast, many AR houses) | auction platform | ALERT only | free | broad | HiBid's own e-mail (B-35). Terms §9: no "web scraping", "robot, spider, scraper", no bypassing robot headers, no extracting reports other than own bid history; no API clause (Last Updated 22 Nov 2022) | FACT |
| Proxibid (Blackmon et al.) | auction platform | NO for fetch | free | Blackmon, Lonoke | never fetch *.proxibid.com (project rule); use house's own site (B-29). Terms page not retrievable here | FACT rule; UNK terms |
| AuctionZip | auction aggregator (25,000+ auctioneers) | ALERT candidate | free account | all AR auctioneers listed | footer shows Terms, Privacy, Subscription Agreement; no API/alerts link in footer; saved searches only as "Following" in the account menu. Terms URL guesses 404'd | FACT homepage; terms UNK |
| Auctioneers' own sites (Wooley, Wilson, Blackmon, Nahlen, others) | auction EVENTS | FEED/own site | free | AR | existing B-26/28/29 pattern: own site, robots/crawl-delay respected. More AR houses: UNK until each robots/terms is read | FACT (project receipts) |
| AR State Surplus (sas.arkansas.gov, formerly M&R) | state surplus | ALERT + MANUAL | free | statewide; warehouse 6620 Young Rd, Little Rock | online sales run on GovDeals (browse free, register to bid); vehicles/computers only on GovDeals; public retail sale every Wednesday 7:30–3:00; FB photos every Tuesday; "State Surplus E-News Sign Up" link exists (content UNK) | FACT FAQ |
| GovDeals | gov surplus | ALERT | free | AR state, Fort Smith, AGFC real estate (moved to GovDeals Jul 2026 per Liquidity Services release) | owner saved-search/seller alerts; already in B-34/F-161. Did not confirm GovDeals' own terms on automation | FACT (state FAQ); terms UNK |
| Public Surplus | gov surplus | ALERT | free | no AR agency confirmed | registered users get e-mail on new items and interest lists (vendor overview). AR sellers: UNK | FACT vendor; AR UNK |
| City/county surplus (Fort Smith, Little Rock, Conway, Faulkner Co.) | local gov | MANUAL / GovDeals | free | Fort Smith is on GovDeals ($800k+ sold per release) | find each seller on GovDeals and alert on it; others UNK, check each city site | FACT Fort Smith; others UNK |
| Universities/schools (UAFS, UA, SAU, UCA) | edu surplus | GovDeals / on-site | free | UAFS policy allows on-site or an approved online platform | no standing feed found; UCA: nothing found. Watch via GovDeals seller search / MANUAL | FACT UAFS policy; rest UNK |
| eBay local | marketplace | API | free tier | local pickup by ZIP | B-37 (Browse API, existing) | queue row |
| Pallet/bin vendors | retail liquidation | per B-34 table | — | Conway/NLR | see B12 doc; unchanged | FACT |

## Pattern across the matrix
INFER: every mainstream consumer marketplace prohibits automated collection. The two supportable routes are (a) the platform's own alert e-mail through the existing read-only mailbox, and (b) sources that publish an API or feed. The "whoever logs in" goal therefore means each user connects their own alerts/accounts, not a central crawler.

## Ranked next 3 connectable sources, with exact NEEDs
1. **AuctionZip "Following" alert e-mails (Arkansas auctioneers).** Widest auction coverage with no scraping. NEED (owner): create/log in to a free AuctionZip account, follow the Arkansas auctioneers and categories wanted, and forward or deliver one genuine notification into the DealSniffer/Alerts label; confirm in the account menu that e-mail notices exist (UNK). NEED (lane 02): a fixture-first alert parser on the email_alerts seam (same shape as GovDeals/Craigslist), after the owner supplies the sample. NEED (legal): read the Terms of Use at its live URL, which I could not retrieve.
2. **Arkansas State Surplus E-News + GovDeals seller alerts.** Statewide, free, official. NEED (owner): sign up for "State Surplus E-News" (link on sas.arkansas.gov) and, on GovDeals, save an Arkansas seller/category search with e-mail alerts; deliver one real e-mail of each. NEED (lane 02): reuse the GovDeals parser (no new code if alerts match B-34); add an E-News parser only after a sample exists. Wednesday retail sales are MANUAL unless E-News announces them.
3. **Trash Nothing (free items), via its official API.** An adapter reportedly exists; I could not find it on origin branches, so its status is UNK. NEED (owner): register an app at trashnothing.com/developer while logged in, then decide on the "personal use only" term: since the data feeds a business flip workflow, e-mail Trash Nothing support (help page) for written confirmation of allowed use before any live poll. NEED (lane 02): confirm auth type from the OpenAPI spec and rate limits. Value is low (free items), so rank last.

Not recommended: Poshmark, Mercari (no local, terms ban automation), HiBid fetching, Proxibid fetching, Facebook (until Meta permission), OfferUp and Nextdoor (no sanctioned route; keep MANUAL).

## Unresolved (honest gaps)
OfferUp, Mercari, Nextdoor, Proxibid and AuctionZip terms pages could not be retrieved. Nextdoor's and OfferUp's absence of an API is INFER from a search. Trash Nothing auth, cost and rate limit are UNK. The adapter's existence was not verified in the repo. Re-read each live terms page before building.

## Sources
poshmark.com/terms · hibid.com/home/termsofuse · trashnothing.com/developer and /terms · auctionzip.com (home) · sas.arkansas.gov/state-surplus/frequently-asked-questions · uafs.edu surplus property policy · investors.liquidityservices.com/node/22136 and /22141 · thepublicgroup.com overview · docs/handoff/B12_CRAIGSLIST_FACEBOOK_SOURCE_STATUS.md (coordinator branch).
