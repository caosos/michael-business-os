# Opportunity Discovery Engine — Round One Research & Design

**Agent:** 02 (Opportunity) · **Date:** 2026-10-06 · **Base:** Conway / Central Arkansas
**Scope:** Research & design only. No sellers contacted, no authenticated scraping, no deployment, no CAOSCare contact.

Evidence is tagged **FACT** (verified from a primary/official source), **INFERENCE** (reasoned from evidence),
**RECOMMENDATION** (my design call), **UNKNOWN** (needs live testing). Per-source citations live in the
five cluster research logs; this document is the synthesis.

---

## 0. The two opportunity types

- **BUY-side:** underpriced/free equipment to resell or use — trailers, campers (frames), mowers, generators,
  pressure washers, compressors, welders, tools, commercial/mechanical/electrical equipment, project vehicles;
  plus estate sales, liquidations, government surplus, auctions.
- **SELL-side (service leads):** mobile repair, drywall repair, assembly, smart-home install, handyman work,
  accessibility-equipment repair.

A single engine ingests both; they differ mainly in source set and scoring (resale-margin vs. job-value).

---

## 1. Master Source Inventory

Legend — **Access**: `API`=official API · `JSON`=undocumented internal JSON/GraphQL endpoint · `EMAIL`=sanctioned
saved-search email alert (IMAP) · `RSS`=feed (often self-generated) · `BROWSER`=headless+stealth · `MANUAL`=human.
**Risk** = ToS/legal/ban risk for *automated* access.

### BUY-side — Peer-to-peer / classifieds
| Source | Access | Central-AR vol. | Freshness | Images | Seller contact | Comps | Risk | Cost |
|---|---|---|---|---|---|---|---|---|
| eBay (Browse API) | **API** (OAuth client-cred, ~5k/day) | Med (natl + local pickup) | Real-time | Yes | Platform only | **Yes** (Insights gated) | **LOW** | Free |
| Craigslist (Little Rock + regional) | JSON/RSS (native RSS dead; OpenRSS/self-gen) | **High** | Immediate | Yes | Relay email | No | **HIGH** (ToS) | Free |
| Facebook Marketplace | BROWSER (stealth) | **Highest** | Minutes | Yes | Messenger only | No | **HIGH** (ban+ToS) | Free/proxy$ |
| OfferUp | BROWSER/JSON (GraphQL) | Med | Real-time | Yes | In-app | No | HIGH | Free/actor$ |
| Nextdoor For-Sale/Free | MANUAL (login-walled) | Low–med | Real-time | Yes | In-app | No | HIGH | — |
| Mercari | JSON (GraphQL) | Low (shipping-only) | Real-time | Yes | In-app | scrape-only | HIGH | — |

### BUY-side — Auctions / government surplus / liquidation
| Source | Access | Central-AR vol. | Buyer premium | Comps | Geo filter | Risk |
|---|---|---|---|---|---|---|
| **GSA Auctions** | **API** (api.gsa.gov, 5k/day, +sold dataset) | Low (federal, sparse AR) | **0%** | **Yes (sale dataset)** | nationwide | **LOW** |
| **GovDeals** (AR state store + AR cities/ARDOT) | JSON (buyer); seller-only official API | **High** | 7.5–12.5% | closed bids | state/store | MED–HIGH |
| **HiBid** | JSON (public GraphQL `LotSearch`) | **Very high** (local estate/equip/farm) | ~10–18%/seller | **Yes (~301M closed lots)** | **ZIP+radius (100mi native)** | MED |
| AllSurplus (Liquidity Svcs) | JSON (`maestro.lqdt1.com/search/list`, anon keys, lat/lng) | Med (trailers/equip) | varies | closed | **lat/lng radius** | MED |
| PublicSurplus | JSON | Med (AR counties/schools) | **0%** | closed | state | MED |
| Municibid | JSON (ZIP/state + sold/zero-bid flags) | Med | **0%** | sold flag | ZIP+state | MED |
| GovPlanet/IronPlanet/Ritchie Bros | JSON (`/api/auctions/upcoming/{realm}`) | Natl (heavy equip, shippable) | 10–15% | past results | per-lot | MED–HIGH |
| MaxSold | JSON (undocumented) + EMAIL | Med (LR radius) | varies | **closed prices** | state/radius | MED |
| CTbids (Caring Transitions Central AR) | EMAIL/watchlist | Yes (local franchise) | varies | closed | location | MED |
| PropertyRoom (police/seized) | JSON | Natl ($1 starts, tools) | 16.5% | ended | per-lot | MED |
| Proxibid / AuctionZip | JSON | Some AR | per-seller | ended | ZIP+radius | MED |
| Liquidation.com / B-Stock | JSON | bulk/pallet (tangential) | varies | ratio | warehouse | MED–HIGH |

### BUY-side — Estate sales / free goods / community
| Source | Access | Central-AR vol. | Images | Comps | Risk |
|---|---|---|---|---|---|
| **EstateSales.NET** | **EMAIL** (free geo+type alerts) — *scraping = ToS breach* | **High** (dominant, aggregates others) | Yes | No | LOW (alerts) / HIGH (scrape) |
| **Trash Nothing** (Freecycle/Buy-Nothing) | **API** (REST/JSON/OpenAPI, free key, lat/lng) | Yes (LR groups) | Yes | No | **LOW** |
| Craigslist free/garage (`/zip`,`/gms`) | JSON/RSS | High | Yes | No | HIGH |
| EstateSale.com | EMAIL/scrape | Low–med | Yes | No | MED |
| EstateSales.ORG | — **avoid** ($0.25/page, 1k/day cap) | Low–med | Yes | No | **HIGH** |
| ArkansasOnline classifieds | scrape | Low | Yes | No | UNKNOWN |
| Buy Nothing (FB groups) | MANUAL | Yes | Yes | No | HIGH |
| University/state surplus (UCA etc.) | → via **GovDeals** | irregular | Yes | bids | see GovDeals |

### SELL-side — Service leads
| Source | Access | Central-AR vol. | Contact incl.? | Delivery | Cost | Risk |
|---|---|---|---|---|---|---|
| **Craigslist gigs/services/trades** | JSON/RSS (OpenRSS) | **Good** (best free) | relay email | poll/feed | Free | MED (ToS) |
| **SAM.gov** (federal contracts) | **API** v2 (free key) | Some (statewide) | Yes (POCs) | API poll | Free | **LOW** |
| **AR Bid / ARBuy** (state+local, incl. City of Conway, Faulkner Co.) | Portal + EMAIL | **Excellent** (in-geo) | Yes (gov) | email notify | Free | **LOW** |
| Google Local Services Ads | **API** (read, Google Ads API) | Good | Yes | API/email | pay-per-lead | **LOW** (needs verify badge) |
| Thumbtack Pro | **API** (webhook, approval-gated) | Good | Yes | webhook push | $15–80/lead | LOW (official) / HIGH (scrape) |
| Angi / HomeAdvisor | Webhook (gated to CRMs) | Good | Yes | push | ~$300/yr+lead$ | LOW/HIGH |
| TaskRabbit | none (metro-only) | Weak in AR | after accept | app | 15%+ | HIGH |
| Bark.com | EMAIL (credits to unlock) | Thin | after credits | email | ~$2.20/credit | MED |
| Nextdoor / FB local groups | MANUAL | Strong organically | in-post | — | Free | HIGH |
| **Accessibility referral orgs** (Mainstream CIL, SAILS, AAAs, VA HISA, Rebuilding Together) | **MANUAL CRM** | Strong, local | warm | phone/email | Free | **LOW** |

---

## 2. Top 20 Ranked Sources

Ranked by **(Central-AR value) × (legal/ToS safety) × (automation reliability) × (freshness)**. **RECOMMENDATION.**

| # | Source | Why it ranks here | Access | Risk |
|---|---|---|---|---|
| 1 | **eBay Browse API** | Only free, legal, reliable API with geo+used+pickup filters; the comps/valuation backbone that *defines* "underpriced." | API | LOW |
| 2 | **Craigslist** (LR + fortsmith/fayar/jonesboro/texarkana + border metros) | Highest free local volume for *both* equipment and service gigs. | RSS/JSON | HIGH→mitigated |
| 3 | **GSA Auctions API** | Only sanctioned auction API; 0% premium; includes a sold dataset for comps. | API | LOW |
| 4 | **GovDeals** (AR state + cities + ARDOT) | Primary AR government surplus channel; high-value equipment. | JSON | MED–HIGH |
| 5 | **HiBid** | Dominant local estate/equipment/farm aggregator; native ZIP+100mi radius; 301M sold-lot comps. | JSON | MED |
| 6 | **EstateSales.NET (email alerts)** | Dominant estate aggregator; email alerts are the sanctioned, zero-scrape ingestion path. | EMAIL | LOW |
| 7 | **Trash Nothing API** | Official free API for free goods (Freecycle/Buy-Nothing), LR groups; pure-profit free items. | API | LOW |
| 8 | **SAM.gov Opportunities API** | Free official federal repair/maintenance/assembly contracts. | API | LOW |
| 9 | **AR Bid / ARBuy** | Recurring in-geo repair/maintenance contracts incl. City of Conway & Faulkner Co. | EMAIL/portal | LOW |
| 10 | **Facebook Marketplace** | Biggest local inventory bar none — but brittle + high ban/ToS risk; kept high only for raw value. | BROWSER | HIGH |
| 11 | **AllSurplus** | Trailers/industrial equip; most API-friendly non-GSA endpoint, true lat/lng radius. | JSON | MED |
| 12 | **Municibid** | 0% buyer premium; **zero-bid/sold flags directly surface underpriced lots.** | JSON | MED |
| 13 | **PublicSurplus** | 0% premium municipal AR surplus. | JSON | MED |
| 14 | **MaxSold** | LR-area online estate auctions + closed-price comps. | JSON/EMAIL | MED |
| 15 | **CTbids** (Caring Transitions Central AR) | Confirmed local franchise; watchlist alerts + comps. | EMAIL | MED |
| 16 | **Google Local Services Ads** | Official lead API, good AR volume; gated by verification badge. | API | LOW |
| 17 | **OfferUp** | Secondary local P2P volume; hard scrape, high risk. | BROWSER | HIGH |
| 18 | **GovPlanet / IronPlanet** | Heavy equipment & military surplus (trailers, generators, compressors); shippable so distance less binding. | JSON | MED–HIGH |
| 19 | **PropertyRoom.com** | Police/seized $1 starts, light competition; tools/electronics. | JSON | MED |
| 20 | **Accessibility referral network** | Not a feed, but the **highest-margin, lowest-competition** service channel; manual CRM. | MANUAL | LOW |

*Honorable mentions:* Thumbtack Pro API (gated, paid), Proxibid/AuctionZip (HiBid overlap), Nextdoor & FB groups
(manual only), Mercari (shippable small tools only), Liquidation.com/B-Stock (bulk pallets).

---

## 3. Best Existing GitHub Projects

| Project | URL | License | Activity | Fit |
|---|---|---|---|---|
| **BoPeng/ai-marketplace-monitor** | github.com/BoPeng/ai-marketplace-monitor | AGPL-3.0 | Active (2026) | **Best FB monitor** — Playwright + logged-in session, noVNC CAPTCHA, AI deal-scoring (OpenAI/Anthropic/Ollama), ntfy/Telegram alerts. *AGPL — copyleft; keep our code separate or accept AGPL.* |
| **scumola/govdeals** | github.com/scumola/govdeals | MIT | 2026-02 | **Best GovDeals reference** — keyword/category/location search, Ollama 0–100 deal scoring (profit/condition/distance), watch+snipe, HTML reports. Low adoption → reference design, not turnkey. |
| irahorecka/pycraigslist | github.com/irahorecka/pycraigslist | MIT | 2025 | Craigslist lib; **needs FlareSolverr** for Cloudflare now. |
| sa7mon/craigsfeed | github.com/sa7mon/craigsfeed | MIT | small | CL search → RSS server (Docker); pattern for self-generated feeds. |
| adamo-gif/Craigslist-rss | github.com/adamo-gif/Craigslist-rss | — | — | CL → RSS republished every 30min via GitHub Actions (free infra pattern). |
| jgdigitaljedi/gs-scraper | github.com/jgdigitaljedi/gs-scraper | UNKNOWN | likely stale | **Architecture gold:** multi-source garage-sale search (CL/OfferUp/VarageSale/Oodle/EstateSales.net) **+ eBay Finding API for comps** — mirrors our design. Mine for structure. |
| pretorin-ai/govbizops | github.com/pretorin-ai/govbizops | — | active | Most complete SAM.gov lib: API + NAICS filter + dedup + scraping fallback + web UI/CLI. |
| MindPetal/sam-search | github.com/MindPetal/sam-search | — | — | SAM.gov by NAICS + from-date → notify (good cron template). |
| jpleger/pysam | github.com/jpleger/pysam | — | — | Simple SAM.gov API wrapper (`pip install pysam`). |
| GSA/auctions_api | github.com/GSA/auctions_api | US Gov/public | — | Source of the official GSA Auctions API; authoritative. |
| Trash Nothing API | trashnothing.com/app/developer | (API ToS) | official | REST/JSON/OpenAPI, free key — use directly, no repo needed. |
| caelinsutch/marketplace-watcher | github.com/caelinsutch/marketplace-watcher | — | active | TS; Supabase + pg_cron hourly FB checks + email — lightweight alt pattern. |

**Frameworks (orchestration/plumbing):** `changedetection.io` (URL diffing, Apprise notify), **n8n** (node-based
orchestrator — preferred backbone), Scrapy (crawl workers), feedparser (RSS). **Avoid Huginn** (stagnant).
**Notifications:** **ntfy** (push to phone) + **Apprise** (fan-out router). All free, self-hostable.

**FACT:** No single actively-maintained FOSS aggregator spans this whole domain. The de-facto "works today"
ecosystem for OfferUp/GovDeals/HiBid/EstateSales/Thumbtack/etc. is **paid Apify actors** (pay-per-run) that wrap
each site's internal endpoints — a viable fallback that offloads selector maintenance.

---

## 4. Access Model: API vs. Internal-Endpoint vs. Email vs. Browser vs. Manual

**RECOMMENDATION — build in this order of preference (safest/most reliable first):**

1. **Official API** (build on confidently): eBay Browse, GSA Auctions, SAM.gov, Trash Nothing, Google LSA (read),
   Thumbtack Pro (if approved). *Stable, legal, low maintenance.*
2. **Sanctioned email-alert / IMAP** (lowest-risk ingestion for no-API sources): EstateSales.NET, GovDeals &
   PublicSurplus & MaxSold & CTbids saved-search alerts, AR Bid/ARBuy notifications. *You only read your own inbox —
   no server is touched beyond a legitimate account feature.* **This is the single most underrated pattern.**
3. **Internal JSON/GraphQL endpoints** (scraper-grade HTTP, no browser needed): GovDeals, HiBid (`LotSearch`),
   AllSurplus (`maestro.lqdt1.com/search/list`), PublicSurplus, Municibid, GovPlanet realms, MaxSold, Proxibid,
   PropertyRoom. *ToS-adverse but public data; throttle, cache, rotate identity, kill-switch on blocks.*
4. **Headless browser + stealth** (last resort, HIGH maintenance): Facebook Marketplace, OfferUp. Stack: **nodriver**
   (Python, beat Cloudflare/anti-bot best in 2026 benchmarks) or stealth-Playwright; **logged-out where possible**
   (legally safer per *Meta v. Bright Data* 2024); if logged-in, dedicated throwaway account + **static residential
   ISP proxy** + persistent `user-data-dir`, low frequency. Expect breakage and account burn.
5. **Manual / human network** (never automate): accessibility referral orgs, Nextdoor, FB groups, radio tradio,
   local company FB pages.

---

## 5. Sources We Should NOT Automate

**RECOMMENDATION — keep these manual or API-only:**

- **Facebook local groups / Buy Nothing groups** — ToS bans automated extraction; Graph API won't serve arbitrary
  groups; account-ban + legal risk. *Monitor manually.*
- **Nextdoor for-sale & recommendations** — login-walled personal content; ToS prohibits scraping. *Manual.*
- **Thumbtack / Angi / HomeAdvisor consumer sites** — scraping harvests client **PII** + breaches ToS (worst combo).
  *Use their official lead API/webhook, or handle manually.*
- **EstateSales.NET site scraping** — ToS §16 explicitly bans robots/harvesting. *Use their email alerts instead.*
- **EstateSales.ORG** — hostile terms: $0.25/page, 1,000-page/day cap. *Avoid entirely.*
- **Any logged-in account you created, where the data is others' PII** — you're contractually bound once logged in
  (*hiQ* lost on this); keep logins disposable and segregated.
- **Block/CAPTCHA evasion after an explicit block** — the one act that most clearly triggers CFAA exposure
  (*Craigslist v. 3Taps*). If a source blocks us, we stop — the kill-switch is mandatory.

**Legal posture (INFERENCE from case law):** Passive monitoring of *public, logged-out* pages at a light rate, with
no republishing and no block-evasion, is materially defensible (*hiQ v. LinkedIn*; *Meta v. Bright Data* 2024 — ToS
bind only while logged in). The realistic worst case for a solo operator is an **account/IP ban**, not litigation —
unless we resell the data, scrape PII, or evade blocks. Design to stay on the defensible side.

---

## 6. Normalized Opportunity Schema

**RECOMMENDATION** — one record type for buy + service, source-agnostic. (JSON/SQLite; types illustrative.)

```jsonc
{
  "id": "uuid",                        // our primary key
  "dedup_key": "sha1(...)",            // cross-source identity (see §7)
  "content_hash": "sha1(...)",         // detects edits/price drops on re-poll

  "source": "craigslist|ebay|govdeals|hibid|estatesales_net|trashnothing|samgov|fb|...",
  "source_listing_id": "string",       // native id; UNIQUE per source
  "url": "https://...",
  "ingestion_method": "api|json|email|rss|browser|manual",
  "tos_risk": "low|med|high",

  "opportunity_type": "buy_item|auction_lot|free_item|service_lead|gov_contract",
  "category": "trailer|camper|mower|generator|pressure_washer|compressor|welder|tool|
               commercial_equip|mech_elec_equip|vehicle|estate_lot|service.repair|
               service.drywall|service.assembly|service.smarthome|service.handyman|
               service.accessibility|other",
  "title": "string",
  "description": "string",
  "condition": "new|used|parts|unknown",

  "price": { "amount": 0, "currency": "USD",
             "type": "fixed|auction_current|starting_bid|free|lead_cost",
             "buyer_premium_pct": 0.0 },       // folded into true cost for auctions
  "ends_at": "iso8601|null",                   // auctions
  "bid_count": 0,

  "location": { "lat": 0.0, "lng": 0.0, "city": "", "state": "AR", "zip": "" },
  "distance_miles": 0.0,                        // from Conway base
  "geo_tier": 0,                                // 0..3, see §9

  "seller": { "name": "", "is_dealer": false,
              "contact_method": "relay_email|phone|in_app|platform|gov_poc|none",
              "contact_value": "" },            // never auto-contacted in Round One

  "images": ["url", ...],
  "comps": { "basis": "ebay_sold|hibid_realized|gsa_sale|self_history|none",
             "median": 0, "n": 0, "as_of": "iso8601" },

  "valuation": { "est_resale": 0, "est_cost_total": 0, "est_net_profit": 0,
                 "profit_per_mile": 0.0, "confidence": 0.0 },
  "score": 0.0,                                 // ranking score (see §8-style)
  "flags": ["underpriced","zero_bid","free","ending_soon","long_distance","needs_review"],

  "status": "active|ended|sold|gone",
  "posted_at": "iso8601",
  "first_seen_at": "iso8601",
  "last_seen_at": "iso8601",
  "notified_at": "iso8601|null"
}
```

Key design points: `price.type` + `buyer_premium_pct` let auctions and fixed-price listings share one math path;
`comps.basis` records *where* the valuation baseline came from; `geo_tier`/`profit_per_mile` drive the
long-distance logic; `contact_*` captured but **never auto-actioned in Round One**.

---

## 7. Deduplication Strategy

**RECOMMENDATION — three layers:**

1. **Intra-source identity:** `UNIQUE(source, source_listing_id)`. Re-polls update `last_seen_at`/`status`/`price`;
   a changed `content_hash` (esp. price drop) flips a `price_changed` flag and can re-notify.
2. **Cross-source identity (same item posted to FB + CL + OfferUp):** compute `dedup_key` from a blocking key
   `(normalized_category, price_bucket, geo_cell ~5mi)` then confirm with (a) fuzzy title similarity
   (token-set ratio ≥ ~0.85) **and/or** (b) **image perceptual hash** (pHash Hamming distance ≤ threshold) to catch
   re-uploaded photos. Merge into one opportunity with multiple `source` links; keep the lowest-risk/cheapest source
   as the action link.
3. **Re-alert suppression:** never notify the same `dedup_key` twice unless a *material* change (price ↓ ≥ X%,
   status → ending_soon). `notified_at` gates this.

**UNKNOWN:** pHash robustness across platform re-compression/cropping needs live tuning; title normalization rules
per category need a real corpus.

---

## 8. Polling Strategy

**RECOMMENDATION — tiered cadence by freshness × volume × risk × quota, all jittered:**

| Tier | Sources | Cadence | Method |
|---|---|---|---|
| Event-driven | EstateSales.NET, GovDeals/PublicSurplus/MaxSold/CTbids alerts, AR Bid | **near-real-time** | IMAP IDLE on our inbox (no polling the sites) |
| Fast local | Craigslist, (FB when built) | 5–15 min | incremental since `last_seen`, `sort=date` |
| API-quota | eBay (5k/day), GSA (5k/day, 5 per 5s), Trash Nothing | 15–30 min | date-filtered incremental; respect quota budget |
| Auctions | GovDeals, HiBid, AllSurplus, Municibid, PublicSurplus | 30–60 min | focus **ending-soon** window; cache open lots |
| Slow/gov | SAM.gov, Google LSA, GovPlanet | daily | since-last-run delta |

Cross-cutting: **conditional requests** (ETag/If-Modified-Since) where supported; **delta processing** (only new/
changed rows hit the scorer); **adaptive back-off** on 403/429; **kill-switch** that disables a source on repeated
blocks and pings the operator; global politeness ceiling per host; randomized intervals to avoid fixed signatures.

---

## 9. Long-Distance Opportunity Logic

**RECOMMENDATION — concentric rings from Conway (72034), expand only when profit pays for the trip.**

```
net_profit = est_resale − purchase_price − buyer_premium − travel_cost − time_cost − fees
travel_cost = round_trip_miles × per_mile_rate (~$0.65–0.70 fuel+wear)   // + tolls if any
time_cost   = est_round_trip_hours × operator_hourly_rate
profit_per_mile = net_profit / round_trip_miles
```

Include an opportunity when **`net_profit ≥ ring_threshold` AND `profit_per_mile ≥ floor`.**

| Ring | Radius | Markets | Rule |
|---|---|---|---|
| 0 | < 35 mi | Little Rock metro (Conway home) | any positive net profit |
| 1 | 35–100 mi | Fort Smith, outer metro | normal threshold |
| 2 | 100–160 mi | Jonesboro, Memphis, Texarkana, NWA/Fayetteville, Springfield MO | elevated threshold |
| 3 | 160–320 mi | Tulsa, Dallas | exceptional-profit only, or shippable/batched |

Modifiers:
- **Shippable items** (small tools; or GovPlanet heavy equip via freight): evaluate by **shipping cost**, not drive
  distance — distance stops mattering, so these bypass the rings.
- **Trip batching:** cluster multiple live opportunities in one distant metro into a single run; amortize
  `travel_cost` across the batch (raises effective profit-per-mile).
- **Transport capacity:** gate by item size vs. Michael's trailer/vehicle capacity (a free trailer 200mi away that
  hauls itself home changes the math — self-transporting items get a travel-cost discount).
- Distance is **never a hard cutoff** — it's a cost term in the profit equation, exactly as the mission requires.

---

## 10. First 3 Collectors to Implement

**RECOMMENDATION — legal-first, high-coverage, fast-to-build:**

1. **eBay Browse API collector** — the valuation backbone. OAuth client-credentials → `item_summary/search` with
   `conditions:{USED}`, local-pickup + postal/radius filters, category + keywords. Stores listings *and* seeds the
   comps engine that every "underpriced" judgment depends on. *Legal, free, reliable — build first.*
2. **Craigslist collector** — Little Rock + fortsmith/fayar/jonesboro/texarkana + border metros, across target
   categories (`hvo`,`tls`,`sss`,`zip`,`gms`) and service sections (`ggg`,`bbb`,`trd`). Self-generated RSS
   (craigsfeed/OpenRSS pattern) or in-page-JSON parse via pycraigslist+FlareSolverr. Covers **both** buy-items and
   service gigs — the highest-volume free source.
3. **Email-alert (IMAP) ingestor** — one collector that parses saved-search alert emails from EstateSales.NET,
   GovDeals, PublicSurplus, MaxSold, and AR Bid. **Sanctioned, low-risk, and broad** — covers estate/surplus/
   auction/gov-bid flow in a single build without touching a prohibited scraper.

*Next up (#4–5): GovDeals internal-JSON collector (study `scumola/govdeals`) and SAM.gov API collector.*

---

## 11. 24-Hour Achievable Capability

**RECOMMENDATION — a running, phone-notifying local poller for the three legal-first sources:**

- Repo scaffold: normalized schema (§6) in **SQLite**, a `SourceAdapter` interface, dedup layer (§7, intra-source +
  title/price blocking; pHash as a stretch), tiered scheduler (§8), scorer stub, and **ntfy + Apprise** notifier.
- **eBay collector live** (OAuth, incremental search, store + build rolling comps).
- **Craigslist collector live** for Little Rock across target categories/keywords, stored & deduped.
- **IMAP ingestor skeleton** parsing EstateSales.NET + one surplus alert format into opportunities.
- **Scoring v0**: `est_resale` = eBay median comp; `underpriced` flag when listing ≤ comp × (1 − margin);
  distance + ring from Conway (§9); push to phone on threshold.

**Not in 24h:** Facebook Marketplace (needs account + residential proxy + babysitting), paid-API approvals
(Thumbtack/Angi/Google LSA), HiBid/AllSurplus internal-endpoint hardening, full cross-source pHash dedup.

---

## 12. Major Unknowns Requiring Live Testing

**UNKNOWN — must verify before committing engineering time:**

1. **Craigslist 2026 reality:** whether OpenRSS and/or pycraigslist+FlareSolverr reliably return current results;
   actual Cloudflare block thresholds and IP-ban behavior.
2. **Internal endpoints (GovDeals, HiBid `LotSearch`, AllSurplus `maestro`, GovPlanet realms):** exact params,
   whether anonymous/shipped keys still work, rate/ban behavior, current ToS/robots.
3. **eBay comps:** Marketplace Insights (sold data) is gated — confirm whether we self-accumulate comps or need a
   third-party sold-price service.
4. **Facebook Marketplace:** real ban rate logged-out vs logged-in; proxy necessity; current working status of
   BoPeng/ai-marketplace-monitor.
5. **Approval gates for a solo operator:** Thumbtack Partner, Angi webhook, Google LSA verification badge.
6. **SAM.gov:** exact rate limits; whether handyman-scale AR contract volume justifies the integration.
7. **Trash Nothing API:** field coverage and actual LR-group activity volume.
8. **MaxSold/CTbids:** undocumented JSON endpoint stability and precise ToS.
9. **Email-alert parsing:** real email formats/deliverability; whether alerts carry enough structured data
   (address, price, images) to populate the schema without a site visit.
10. **pHash dedup:** cross-platform effectiveness after re-compression/cropping; per-category title normalization.
11. **Legal comfort:** operator's risk tolerance for internal-endpoint access on gov-surplus sites (public data but
    ToS-adverse) — sets how aggressive Tier-3 collectors may be.

---

### Appendix — raw cluster research logs
Full per-source citations are preserved in the five background-agent transcripts (P2P marketplaces; auctions/gov
surplus; estate sales/liquidations; service leads; automation tech & legal). This document is their synthesis.
