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
