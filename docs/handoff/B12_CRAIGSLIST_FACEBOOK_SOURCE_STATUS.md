# Craigslist and Facebook Marketplace: source status and smallest supported route (Agent 01, 2026-10-11)

Part of the existing B-12 local-source objective; not a second source task. Research from PRIMARY documents fetched 2026-10-11 (no credentials used, nothing retrieved from either site's listings). Provenance: FACT = quoted from the primary document; INFER = my reading; UNKNOWN = not established.

## Craigslist — NOT CONNECTED. No supported automated route exists without a separate written license.
- FACT (Craigslist Terms of Use, https://www.craigslist.org/about/terms.of.use, "last updated August 16, 2019"): "You agree not to copy/collect CL content via robots, spiders, scripts, scrapers, crawlers"; "Unless licensed by us in a separate written or electronic agreement, you agree not to use or provide software" (except "our App and general purpose web browsers and email clients") that interacts with CL; also not to "combine or integrate CL or the API with any software ... not authorized by us" and not to "circumvent any functionality that controls access". Liquidated damages are stated: $3,000 per day for copying or exploiting content without express written consent; item L covers "requesting, viewing, or accessing more than 1,000 pages of CL in any 24-hour period".
- INFER: scraping, scripted search, or any unattended fetch of Craigslist is a terms violation. It must not be built, and a GovDeals mailbox does not connect Craigslist.
- Smallest supported route: only a **separate written license from Craigslist** (an external business agreement). There is no public self-serve API I could verify. UNKNOWN: whether Craigslist's own saved-search email alerts exist for this use and whether software parsing a user's own received alert mail is acceptable under the "email clients" carve-out. That is a terms/legal judgment, NOT claimed as a route; record it only as a question for the owner.
- Manual pasted listings (F-141) are owner-entered finds, not automatic discovery, and must keep that label.
- NEED to ever connect: owner decides whether to pursue a written Craigslist license (external agreement, possible cost). Until then: NOT CONNECTED.

## Facebook Marketplace — NOT CONNECTED. Automated collection needs Meta's express written permission.
- FACT (Meta Automated Data Collection Terms, https://www.facebook.com/apps/site_scraping_tos_terms.php, "Effective October 7, 2024"): automated data collection is "the collection of data from Meta Company Products via the use of automated or programmatic tools" and requires "Meta's express written permission"; "acceptance of these Terms alone does not constitute the required written permission ...; such permission must be obtained separately through Meta's formal authorization process."
- INFER: Marketplace is a Meta product, so unattended fetching or scraping is not permitted without that separate authorization.
- Official data access found (secondary sources only, UNVERIFIED against Meta's own docs): the Meta Content Library API reportedly includes Marketplace but is limited to qualified academic or nonprofit researchers; it is not a business route.
- Third-party vendors (Apify, Bright Data, Anysite, ScrapeCreators and similar) sell Marketplace data. Their compliance with Meta's terms is UNKNOWN; adopting one means a new provider, a new paid service and a source-policy risk, so it is NOT done and needs separate explicit owner authorization.
- Existing project rule stands: no unattended Facebook fetch or scrape.
- Smallest supported route: none verified for this business. NEED to ever connect: Meta's written permission (formal authorization process), or the owner explicitly choosing and authorizing a provider after reviewing the terms risk.

## What this means for the owner's question ("when will Craigslist and Facebook appear")
No date can be given: both depend on a permission that only the platforms can grant (a Craigslist written license; Meta written permission), not on engineering effort. The nearest real local source is GovDeals/PublicSurplus through the alert mailbox (B-12 NEED), and wiring for it is F-145.

## Sources (primary)
- https://www.craigslist.org/about/terms.of.use
- https://www.facebook.com/apps/site_scraping_tos_terms.php
