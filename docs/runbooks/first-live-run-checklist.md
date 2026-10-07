# First live run — what it will confirm (B-12 prep)

Everything below is **read-only**: no seller contact, no bids, no purchases. Each live call is behind an explicit `live = true` (or credentials), a read-only transport that allows only the listed host, and the shared 403/429 freeze. If any source answers 403, 429 or a CAPTCHA, **stop**: the system freezes it (2 blocks or 1 CAPTCHA), and you do not retry or work around it.

**Ground rules for the run**
0. Start with `--dry` (see below).
1. Run from a clean data dir: `--data-dir var/live-smoke`. Nothing from the run touches the production store.
2. Raw payloads land in `var/live-smoke/raw/` (content-addressed). To make a fixture, copy a payload out by its `raw_ref`; scrub anything personal first (names, e-mails, phone numbers, partial VINs).
3. Record real fixtures *next to* the hand-built ones, then change the mapping and the tests together. Never edit a fixture to make a test pass.
4. Put keys in a `0600` env file outside the repo (`~/.config/mbos/*.env`), never in git or config.

## What Michael supplies (a 15-minute job)
| For | Needs | Where |
|---|---|---|
| eBay Browse (flip) | App ID + Cert ID (Production keyset) | `docs/runbooks/ebay-live-credentials.md` |
| eBay sold comps (optional, MICHAEL_DECISIONS #8) | Marketplace Insights **Limited Release approval** (apply separately) | eBay developer portal |
| GSA Auctions | `GSA_API_KEY` (free, api.data.gov) | api.data.gov signup |
| Trash Nothing | `TRASHNOTHING_API_KEY` (free). **Decide first** whether free-item flips are wanted (MICHAEL_DECISIONS #7) | TN developer page |
| SAM.gov | `SAMGOV_API_KEY` (free SAM.gov account) | sam.gov |
| IMAP alerts | a mailbox login or app password, `ImapReader(live=True)` and a DKIM-aware provider | env var named in config |
| CPSC, NHTSA | **nothing**: no key is documented | — |

## Per source: command, what to confirm, where to change things

### eBay Browse — `mbos-discover run --config … ` with `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET`
| Confirm | Pass looks like | If it differs, change |
|---|---|---|
| The filter names (`conditions:{USED}`, `pickupPostalCode`, `pickupRadius`, `pickupRadiusUnit`, `deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}`, `price:[..N]`) are accepted | `ok fetched=N`, no 400 | `EbayBrowseAdapter._search_url` |
| `distanceFromPickupLocation` is returned | `location.geo_tier` set on Items | `normalize` |
| **B-15 field names** `itemCreationDate`, `seller.feedbackPercentage`, `seller.feedbackScore` exist in `item_summary` results | `exposed_facts("ebay", payload)` returns `posted_at` and `rating` for ≥ 1 live payload | `enrichment._ebay` whitelist. If a field is absent, nothing else changes: the key is omitted. |
| Is there an `updated`/revision date or seller account age in `item_summary`? (Probably only in `getItem`, one call per listing) | recorded either way | add to the whitelist only if exposed |
| Daily quota (documented ~5,000 calls/day) | rate headers, if any | cadence in the config |
| Photos: `image.imageUrl` / `additionalImages` are fetchable read-only through an allow-listed host | `images.collect` retains ≥ 1 | the image fetcher (none live yet) |

### GSA Auctions — `GSA_API_KEY`, profile `live = true`
Confirm the JSON **types** of `LotNo`, `PropertyZip`, `HighBidAmount`, `BiddersCount` (number or string), that `X-API-KEY` in the header is accepted, and the rate limit headers (documented 5k/day, 5 per 5 s). Change `gsa_auctions.normalize`. Check the `AucEndDt` date-only assumption (INFERENCE: end of day UTC).

### Trash Nothing — `TRASHNOTHING_API_KEY`, profile `live = true`
Confirm `api_key` in the query string is accepted, the `radius` cap (80,500 m), `photos` shape, whether `date` is UTC, and that `outcome` is null for live posts. Change `trashnothing.py`.

### SAM.gov — `SAMGOV_API_KEY`, profile `live = true`
Confirm the shapes of `placeOfPerformance` / `officeAddress` (objects vs strings), `responseDeadLine` timezone, the daily limit for a non-federal key, and that `ptype=o,k,p,r` returns plausible leads. Change `samgov.normalize` and the NAICS table.

### Alert e-mails (GovDeals / PublicSurplus / EstateSales.NET)
Needs real alert e-mails first (UNKNOWN layouts): forward one of each into the mailbox, then run with `ImapReader(live=True)`. Confirm `Authentication-Results: dkim=pass` is present on genuine alerts (otherwise they are quarantined as spoofs), and tune the per-origin parser (`email_alerts.ORIGINS`). Confirm the folder is opened read-only (`EXAMINE`) and `\Seen` stays unset.

### CPSC recalls — no key
Confirm: the real **rate limit** and terms (the guide states none: watch for 429/`Retry-After`); that `Model` and `Manufacturers` are present for in-scope recalls; and how many real recalls reach the KB versus the review list (the **coverage** number Agent 03 asked for). Change `recalls.py`.

### NHTSA — no key
Confirm the terms and rate limits (UNKNOWN), and that complaint `components` is a comma-separated list. Then flip `KB_SUPPORTS_MODEL_YEARS` **only** after Agent 03's matcher supports years (B-18).

### eBay Marketplace Insights (only if approved)
Confirm the real `item_sales` response shape (`itemSales[]`, `lastSoldPrice`, `lastSoldDate`), the 90-day window and the category allow-list. Change `ebay_insights.normalize`. Until approved, sold comps come from manual entry.

## One command for every source (B-19)
`mbos-discover run --config <cfg> [--source NAME]... [--fixtures ROOT] [--dry]` covers every source: items (eBay, GSA, SAM.gov, Trash Nothing, intake inboxes, alert e-mails), comps (manual, eBay Marketplace Insights, eBay asking comps derived from stored listings) and knowledge (CPSC, NHTSA).
- **Before the first live run, look at what it will do:** `mbos-discover run --config <cfg> --dry`. It prints the exact requests, with secrets redacted, makes no network call, and writes no state. For e-mail it prints the read-only IMAP command sequence.
- **Live flags:** a profile does nothing on the network until its flag is on (`live = true`; `imap.live = true` for a mailbox; eBay Browse goes live only when its credentials are set). Without a flag you see a "config" error with zero requests.
- Knowledge output lands in `<data-dir>/knowledge/<source>.json` (entries plus the review list); comps in `<data-dir>/comps.json`.

## After the run (the ten-minute wrap-up)
1. `mbos-discover health` → no source FROZEN; record any `error` kinds.
2. Record fixtures for each confirmed shape and update the mapping and tests together.
3. Start the **live 7-day F2 sample**: the same cadence for 7 days, then count duplicates by hand on 50 sampled Items. (The corpus result of 0.00% is synthetic.)
4. Update the `UNKNOWN` items in `docs/implementation/agent-02-discovery-lane.md` (§10, §13–§16, §21–§23) from "from memory / unverified" to FACT with the date.
5. Tune the pHash thresholds on real seller photos (match ≤ 10 bits, different ≥ 20) and check the B-15 `stale_risk` thresholds (14/45 days) against real listing ages.
6. Report to Agent 01: confirmed fields, new rate limits, anything that returned 403/429.
