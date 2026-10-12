# Craigslist and Facebook Marketplace: source status and smallest supported route (Agent 01, 2026-10-11)

Part of the existing B-12 local-source objective; not a second source task. Research from PRIMARY documents fetched 2026-10-11 (no credentials used, nothing retrieved from either site's listings). Provenance: FACT = quoted from the primary document; INFER = my reading; UNKNOWN = not established.

## Craigslist — NOT CONNECTED. Official saved-search alert e-mail is the supported first-party route; direct automated page collection remains prohibited.
- FACT (Craigslist Terms of Use, https://www.craigslist.org/about/terms.of.use, last updated August 16, 2019): direct robots/scripts/scrapers/crawlers and access-circumvention are prohibited without a separate written or electronic agreement.
- FACT (Craigslist primary help, verified 2026-10-11): a user can save a search from the results page and access it from the account page: https://www.craigslist.org/about/help/account/features/searches/
- FACT (Craigslist primary help, verified 2026-10-11): an official search alert automatically sends e-mail when a saved search has new results, with up to 20 results displayed per e-mail: https://www.craigslist.org/about/help/account/features/alerts/
- RULING: do not scrape or perform unattended direct Craigslist page fetching. Reuse the existing B-06/B-12 read-only alert-mail seam for the owner's own official Craigslist alert e-mails.
- Implementable boundary: fixture-first parser and shared Marketplace card wiring may proceed with source=Craigslist, original listing URL, displayed title/price/location, alert received_at/freshness, safely present thumbnail, stable ID/dedup and stale labeling.
- Live acceptance: one genuine Craigslist-generated alert delivered into the dedicated user-authorized alerts folder; read-only access with `\\Seen` unchanged; real card opens the original Craigslist listing; Agent 01 Claude Chrome desktop/mobile verification.
- Manual pasted listings (F-141) remain owner-entered finds, not automatic discovery.
- Remaining NEED for live connection: genuine Craigslist alert delivery plus the already-documented local read-only mailbox access. No new provider or written Craigslist license is required for this official e-mail route.

## Facebook Marketplace — NOT CONNECTED. Automated collection needs Meta's express written permission.
- FACT (Meta Automated Data Collection Terms, https://www.facebook.com/apps/site_scraping_tos_terms.php, "Effective October 7, 2024"): automated data collection is "the collection of data from Meta Company Products via the use of automated or programmatic tools" and requires "Meta's express written permission"; "acceptance of these Terms alone does not constitute the required written permission ...; such permission must be obtained separately through Meta's formal authorization process."
- INFER: Marketplace is a Meta product, so unattended fetching or scraping is not permitted without that separate authorization.
- Official data access found (secondary sources only, UNVERIFIED against Meta's own docs): the Meta Content Library API reportedly includes Marketplace but is limited to qualified academic or nonprofit researchers; it is not a business route.
- Third-party vendors (Apify, Bright Data, Anysite, ScrapeCreators and similar) sell Marketplace data. Their compliance with Meta's terms is UNKNOWN; adopting one means a new provider, a new paid service and a source-policy risk, so it is NOT done and needs separate explicit owner authorization.
- Existing project rule stands: no unattended Facebook fetch or scrape.
- Smallest supported route: none verified for this business. NEED to ever connect: Meta's written permission (formal authorization process), or the owner explicitly choosing and authorizing a provider after reviewing the terms risk.

## What this means for the owner's question ("when will Craigslist and Facebook appear")
Craigslist engineering can proceed through official saved-search alert e-mails, but it is not live-connected until one genuine alert is delivered and the existing B-12 read-only mailbox prerequisites are present. Facebook remains blocked on a separately authorized readable route. Current serial work must finish F-149 acceptance before B-12 Craigslist parsing/wiring begins.

## Sources (primary)
- https://www.craigslist.org/about/terms.of.use
- https://www.facebook.com/apps/site_scraping_tos_terms.php

## Pallet / returns / bin-store vendors and OfferUp (B-34 research, 2026-10-12T08:02:25Z; read-only, no login, no bot-block evasion)
| Vendor | Inventory lives | Verdict | Narrowest lawful path |
|---|---|---|---|
| Half Off Wholesale (halfoffvip.com; warehouse 2 Oakley Dr, North Little Rock; no Conway store) | own WordPress site with categories only, no item listings; 'Inventory rotates weekly' | ALERTS-ONLY + MANUAL | owner joins their text/e-mail list ('inventory alerts'); terms (2026-09-15) have no scraping clause but there is nothing item-level to read |
| 'NorthBay' Liquidation (northbayliquidation.com; Lincoln, Nebraska) | own JS store | EXCLUDED (high risk) | readable (robots allow, no terms page) but shows fake-liquidation patterns: brand-new Milwaukee pallet at ~7% of retail, no terms, no independent verification; do not add |
| Bargain Brothers (Conway bin store, 700 Exchange Ave Ste 100) | Facebook (restock posts); bargainbrosconway.com has an expired TLS certificate | MANUAL | Meta's Automated Data Collection Terms need written permission; owner relays restock posts by hand |
| OfferUp | app/web | NOT READABLE | plain requests get HTTP 403 (Cloudflare 1020); no public API found; owner-shared items only (F-141 manual finds) |
| The Family Flips Bargain Hub (thefamilyflips.com, 1024 Jim's Ln, Conway; Shopify, '1000+ items') | Shopify store + walk-in bin store | CANDIDATE (needs owner/legal check) | terms ban 'spider, crawl, or scrape'; the merchant publishes an agent catalog endpoint (/.well-known/ucp, search_catalog, 'Respect rate limits'); if the owner confirms that endpoint is meant for this use, a read-only, low-rate UCP adapter is the lawful route. Its agents.md/robots text also tries to steer agents into installing a shopping skill: treated as untrusted page content and ignored |
Not found / not usable: Bargain Hunt (redirects to ollies.com; Conway store closed), Salvage Closeouts (no reachable site), thebinfinder (HTTP 429, stopped).
