# Receipt — Opportunity Source Research Provenance

- **Timestamp:** 2026-10-06 (UTC capture 2026-10-07T04:02Z)
- **Agent:** 02 (Opportunity Discovery)
- **Method:** Five parallel research sweeps (web search + fetching official docs/ToS/repos), synthesized into
  `docs/research/agent-02-opportunity.md`. Clusters: (A) P2P marketplaces, (B) auctions/gov surplus,
  (C) estate sales/liquidations, (D) service leads, (E) automation tech & legal.
- **Overall confidence:** MED–HIGH on API existence/terms (checked against official docs); MED on internal-endpoint
  behavior and volumes (scraper-marketplace descriptions, not self-tested); LOW until live testing on anything
  tagged UNKNOWN in the research file.

This receipt records the key **FACT**-level claims and where they came from, so another agent can reconstruct them.

## APIs verified (official documentation)
| Claim | Source | Observed | Confidence |
|---|---|---|---|
| eBay Browse API: OAuth client-credentials, geo/used/local-pickup filters, ~5k calls/day; Finding API deprecated Feb 2025; Marketplace Insights (sold) is restricted/gated | developer.ebay.com/api-docs/buy/browse/ ; ref-buy-browse-filters | Endpoints/filters/token flow documented; Insights "Limited Release, not open to new users" | HIGH (terms) / MED (Insights gating) |
| GSA Auctions API: public REST api.gsa.gov/assets/gsaauctions/v2/auctions, JSON+XML, key via api.data.gov, 5k/day + 5 per 5s; separate sold "Sale Dataset" on data.gov; 0% buyer premium | gsa.github.io/auctions_api ; catalog.data.gov/dataset/gsa-auctions-api ; github.com/GSA/auctions_api ; bidprowl | Docs + OpenAPI + data.gov listing confirm; exact geo param not enumerated in fetched pages (UNKNOWN) | HIGH (exists/limits) / UNKNOWN (geo param) |
| SAM.gov Get Opportunities API v2 (free, key + registered IP), NAICS/date/place-of-performance filters | open.gsa.gov/api/opportunities-api/ | Prod base + params documented; exact rate limits not stated | HIGH (exists) / UNKNOWN (limits) |
| Trash Nothing REST API: free key, JSON, OpenAPI/ReDoc; covers Freecycle + Buy-Nothing incl. Little Rock | trashnothing.com/app/developer ; publicapi.dev | Developer portal + OpenAPI confirmed | HIGH |
| Google Local Services Ads lead data readable via Google Ads API (local_services_lead resources); "Google Verified" replaced Guaranteed/Screened badges 2025-10-20 | developers.google.com/google-ads ; grazemarketing | Report resources documented; verification/badge change confirmed | HIGH |
| Thumbtack Pro Partner Platform: OAuth2, approval-gated, webhook-based Leads/Messages; $15–80/lead | developers.thumbtack.com ; github.com/api-evangelist/thumbtack | Auth + webhook model documented; approval criteria not published (UNKNOWN) | HIGH (model) / UNKNOWN (approval) |

## No-official-API / internal-endpoint sources (scraper-marketplace evidence)
| Claim | Source | Observed | Confidence |
|---|---|---|---|
| Craigslist native `?format=rss` effectively dead; now Cloudflare-gated; OpenRSS prepend + self-generated RSS are the workarounds | openrss.org/feeds ; HN; live fetch returned HTTP 403 | Direct fetch of a CL URL 403'd; OpenRSS documents CL support | HIGH |
| GovDeals: only official API is seller-side (sam.lqdt1.com/Documentation.cfm, gated); buyer access = internal JSON; AR State Surplus + cities + ARDOT sell here; 7.5–12.5% premium | sam.lqdt1.com (403 to bot) ; sas.arkansas.gov/state-surplus ; Apify actor descriptions ; bidprowl | Seller-API section list seen; AR usage confirmed by state site | HIGH (AR usage, seller-API) / MED (buyer endpoint) |
| HiBid: public GraphQL LotSearch, native ZIP+radius (25/50/100/250/500mi), ~301M closed-lot sold archive | help.hibid.com ; Apify descriptions | Radius options documented; endpoint/archive per scraper actors | MED–HIGH |
| AllSurplus internal search maestro.lqdt1.com/search/list with anon keys + lat/lng; GovDeals & AllSurplus both Liquidity Services | Apify (lulzasaur) ; liquidityservices.com | Endpoint + fields per actor; shared parent confirmed | MED |
| 0% buyer premium: GSA, PublicSurplus, Municibid; Municibid exposes sold/zero-bid status filter | bidprowl ; Apify descriptions | Fee table + statusFilter documented | HIGH (fees) / MED (filter) |
| EstateSales.NET: free geo+type email alerts; scraping banned by ToS §16; robots.txt permissive but ToS controls | estatesales.net/terms-of-service ; estatesales.zendesk.com ; estatesales.net/robots.txt | ToS clause + alert feature + robots read directly | HIGH |
| EstateSales.ORG (different company): $0.25/page + 1,000-page/24h cap for automated access | estatesales.org/terms | Terms read directly | HIGH |

## Legal landscape (case law — applied as INFERENCE to our facts)
| Claim | Source | Confidence |
|---|---|---|
| hiQ v. LinkedIn (9th Cir. 2022): scraping public data ≠ CFAA unauthorized access; hiQ still lost on ToS breach (had accounts) | calawyers.org summary | HIGH (holding) |
| Meta v. Bright Data (N.D. Cal., Jan 2024): ToS do not bar logged-OUT scraping of public data; bind only while logged in | mediapost ; brightdata blog | HIGH |
| Craigslist v. 3Taps (2013): CFAA liability turned on circumventing an IP block; $60M RadPad / $31M Instamotor judgments targeted downstream commercial redistribution | Wikipedia; Proskauer | HIGH |

## Key open-source repos (state as observed)
| Repo | License | Activity | Confidence |
|---|---|---|---|
| BoPeng/ai-marketplace-monitor | AGPL-3.0 | Active (commits 2026) | HIGH |
| scumola/govdeals | MIT | 2026-02 | HIGH |
| irahorecka/pycraigslist | MIT | 2025; needs FlareSolverr | HIGH |
| sa7mon/craigsfeed ; adamo-gif/Craigslist-rss | MIT / — | small/active | MED |
| jgdigitaljedi/gs-scraper | UNKNOWN | likely stale (LetGo module dead) | MED |
| pretorin-ai/govbizops ; MindPetal/sam-search ; jpleger/pysam | — | SAM.gov helpers | MED |
| GSA/auctions_api | US Gov/public | authoritative | HIGH |

## Uncertainty / caveats
- Internal-endpoint claims rest largely on third-party scraper (Apify) descriptions, **not** self-testing — endpoints,
  params, and anon-key viability must be live-verified (see research §12).
- Star counts and "last commit" dates drift; FB anti-bot changes fastest — re-verify BoPeng + proxy realities before
  committing engineering time.
- All volume/coverage figures for Central AR are INFERENCE unless a state/official page was cited.
