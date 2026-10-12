# B-42: Facebook Marketplace routes (b) paid provider and (c) Meta written permission

Task B-42, Agent 07 QA, 2026-10-12. Research and drafting only. No account created, nothing sent, no spend, no scraping, no login. Pages were read with a read-only fetch tool on 2026-10-12; a few figures come from search-result summaries and are marked.
Labels: FACT = stated on a primary page I read; INFER = my reasoning; UNK = not found, owner or provider must confirm.

## 0. Bottom line

- FACT: Facebook has no official Marketplace listings API for ordinary sellers/buyers (Apify actor FAQ, 2026-10-12). The only Meta-run data access that lists Marketplace is the Meta Content Library and API, which is a controlled research-access environment (section 3).
- FACT: Meta's Automated Data Collection Terms (effective 2024-10-07) require Meta's express written permission before any automated collection, and say that permission "must be obtained separately through Meta's formal authorization process". The page gives **no form, contact, or eligibility criteria** (read 2026-10-12). So the route (c) channel is UNK; section 3 gives the best candidate paths and the owner must confirm which one Meta accepts.
- FACT: route (b) providers are scrapers or data resellers. None showed Meta permission. Owner accepts compliance as UNKNOWN; this doc keeps it UNK.
- INFER: recommended order for (b): 1) Bright Data Scraper API (cheapest at the owner's volume, fully documented bearer-token API, free tier); 2) Apify `apify/facebook-marketplace-scraper` (most-used, simplest, search by URL); 3) Apify `blackfalcondata/facebook-marketplace-scraper` (only one that advertises location+radius inputs and recency filters, cheapest, but small publisher). Do (c) in parallel; it costs nothing.

## 1. Provider comparison (route b)

Volume assumption: ~2,000 listings/week = ~8,700/month (2,000 x 52 / 12).

| | Apify `apify/facebook-marketplace-scraper` | Apify `blackfalcondata/facebook-marketplace-scraper` | Bright Data Scraper API (Marketplace) | Bright Data Dataset (Marketplace) |
|---|---|---|---|---|
| Search spec | FACT: no location/radius/keyword fields; you pass `startUrls` (Marketplace URLs) e.g. `/marketplace/<city>/search/?query=<kw>`, `/marketplace/<city>/<category>`; radius not mentioned. INFER: radius via the URL query string `radius=` (Facebook's own site URL parameter) must be tested; UNK until the owner's first paid run | FACT (search summary, not full page): keyword + location with radius, price, condition, recency, category filters | FACT: dedicated "collect by keyword" scraper plus a by-URL scraper; location filter not documented on page read | FACT: bulk dataset, not a search; filter by fields via Dataset Filter API |
| Fields | FACT: title, listing URL, min/max and sale price, location, photo, video, seller details, live/sold/pending, delivery type; with `includeListingDetails`: description, coordinates, timestamp, attributes | FACT (summary): price, condition, description, photos, coordinates, location | FACT (docs): url, title, description, seller_description, initial_price, final_price, currency, product_id, condition, color, brand, location, country_code, images, videos, profile_id, listing_date | FACT: same family, 23 fields, 27.8M+ records (schema markup says 31M, mismatch) |
| Posted time | FACT: timestamp only in detail mode | UNK, recency filter advertised | FACT: `listing_date` | FACT: listing date |
| Freshness | INFER: live scrape at run time; UNK latency | INFER: live scrape; incremental monitoring advertised | FACT: scraper is on demand, webhook or cloud delivery; refresh rate not stated | FACT: refreshed monthly. Too stale for deal sniffing |
| Price seen 2026-10-12 | FACT: "from $2.60/1,000 listings"; README says $6.20/1,000 Free plan, $5/1,000 on the $19/mo Starter. Platform usage not charged separately. At 8,700/mo: ~$23 (at 2.60) to ~$54 (at 6.20), or $19 + 8.7 x $5 = ~$62/mo on Starter | FACT (summary): about $0.90/1,000 plus Apify usage; ~$8/mo + usage. UNK final | FACT: $1.50/1,000 pay-as-you-go, 5K free records/month, no card needed for the free tier. At 8,700/mo: ~(8,700-5,000) x 1.5/1,000 = ~$5.6/mo. Scale plan $499/mo is not needed | FACT: up to $0.0025/record, **$250 minimum order**; unsuitable |
| Auth | FACT: Apify account API token (bearer) | same | FACT: API token (bearer) | FACT: bearer token |
| Provider terms | FACT: DPA (updated 2026-07-08) puts on the customer responsibility that instructions comply with data-protection law and for the lawful basis. Actor FAQ says it does not extract private user data but results may include personal data and advises consulting a lawyer | same platform | FACT: page claims data is "ethically obtained and compliant with all privacy laws", "GDPR ready". UNK: acceptable-use, retention (not read) | same |
| Red flags | 3.91/5, ~948 monthly users; seller details are personal data; breaking changes possible; community actor, not Apify-operated; two other Apify Marketplace actors showed "Under maintenance" (fragility of this category); two listing prices on the same page disagree | small publisher; UNK reviews and reliability, verify the actor page before use | by-URL scraper needs listing URLs; discovery by keyword is a separate product and location support is UNK; vendor compliance claim is marketing, not Meta's permission | stale monthly data, $250 floor |

Other providers: FACT the search returned no Marketplace-specific products for Oxylabs, Zyte, or ScrapingBee; UNK, not evaluated. A 2026 comparison blog (scrapecreators.com) exists but is a vendor blog; not used.

Compliance, all providers (FACT/INFER): Meta's terms apply to whoever collects. Paying a vendor does not transfer permission to the owner; Meta's terms require the *collector* to hold written permission, and the owner chose to accept this UNK. Practical limiters: keep volume small (2,000/week), keep rate low, no resale, discard seller personal fields you do not need (INFER: drop seller name/profile fields at ingest).

### Owner steps (create account and token; do not paste the token anywhere but the host)

Do this yourself; the agent has not done any of it.
1. Bright Data (recommended): go to brightdata.com, sign up with your email, verify it. In the control panel open Web Scraper API / Scrapers, find "Facebook Marketplace" (by URL; also the by-keyword scraper), use the free tier (5K records/month, no card per the pricing page seen 2026-10-12). Account settings > API tokens > create a token with only scraper permission (UNK: exact menu names). Run one small trial: 20 listings, search "tools" near Conway AR; check whether location/radius is respected and `listing_date` is present.
2. Apify (alternative): console.apify.com, sign up, Settings > API & Integrations > copy the personal API token. Set a monthly usage limit ($10) in Billing so a mistake cannot spend more. Run `apify/facebook-marketplace-scraper` with a `startUrls` entry for Conway (city slug UNK, probably `conway`; confirm on facebook.com in a logged-out browser yourself), `resultsLimit` 50, `includeListingDetails` true.
3. Store the token on this host only: `install -m 600 /dev/null ~/.config/mbos/secrets/BRIGHTDATA_TOKEN` (or `APIFY_TOKEN`), then paste it into that file with an editor. Never put it in GitHub, chat, a status file, or a receipt. (Path is a suggestion; use whatever the coordinator's secrets convention names.)
4. Set a spend cap in the provider billing page before the first paid run.
5. Tell Agent 01 the provider name and that the token file exists; a lane builds the adapter. Until Meta permission (c) is granted, label every listing from this source `source_compliance: UNKNOWN` (INFER, matches the owner's acceptance).

## 2. Cost per week at ~2,000 listings (date seen 2026-10-12)

- Bright Data: about $1.30/week after the free tier (INFER, from $1.50/1,000, 5K free per month).
- Apify official-actor: $5.20 to $12.40 per week (from $2.60 to $6.20 per 1,000).
- Blackfalcon: about $1.80/week plus platform usage (UNK).

## 3. Meta route (c): written permission

What is known (FACT, read 2026-10-12, https://www.facebook.com/legal/automated_data_collection_terms, effective 2024-10-07):
- Permission is express and written, obtained "separately through Meta's formal authorization process". No form, address, or criteria on the page.
- Allowed uses named: search-engine results, previews of Meta URLs, or other purposes Meta approves in writing. Selling, licensing, or sublicensing the data is prohibited.
- Duties: privacy and security program with technical safeguards such as rate limiting; obey robots.txt; collect only publicly available personal data; Meta may audit on short notice; keep records at least one year after the terms end; Meta may revoke at any time; indemnity; terms survive as long as you use the data.
- INFER: DealSniffer's use (finding items for the owner's own resale) is not one of the named purposes, so the letter asks for approval under "other purposes Meta approves in writing". Approval is unlikely for a single self-hosted individual. Plan around a denial or silence.

Candidate programs:
1. Meta Content Library and API (https://developers.facebook.com/docs/content-library-and-api/). FACT: "controlled-access environment"; the API's Facebook data includes "Marketplace listings"; download access needs application approval by ICPSR or CASD and acceptance of Meta Research Tools terms (Information Sharing Agreement). Eligibility criteria not listed on the page. INFER: aimed at qualified researchers and institutions; a personal reseller is almost certainly not eligible. UNK.
2. Meta's formal authorization process for the Automated Data Collection Terms: UNK where. The owner should look at the "Get Access" and contact links under Meta for Developers and the Meta Content Library page; or send the letter through the legal contact in Meta's Terms of Service. Ask Meta directly in the letter which channel is correct.
3. Meta Business Support / Marketplace partner programs: UNK. I found no public Marketplace listings partner or feed program during this research (search 2026-10-12). Ask in the letter.

Owner steps: review the draft; edit placeholders; send from your own email or the contact route Meta's pages point to; record the date and any reference number in a receipt; do not scrape under the draft's assumptions until a reply arrives.

## 4. DRAFT request letter (owner to review and send; NOT sent)

```
Subject: Request for written permission under Meta's Automated Data Collection Terms: single-user, read-only, non-commercial-data use

To: Meta Platforms, Inc. (the department that grants written permission under the Automated Data Collection Terms; if this is the wrong channel, please forward it or tell me where to apply)

Date: [DATE]

Dear Meta team,

I am Michael [LAST NAME], an individual in [CITY], Arkansas (ZIP 72032 area). I am writing to ask for express written permission under Meta's Automated Data Collection Terms (effective October 7, 2024), or to be told which program applies to my use.

What I run. DealSniffer is a small software tool I host myself on one computer that I own. I am its only user. It helps me find used items that people are selling near me so I can buy them in person and resell them locally.

What I would collect. Public Facebook Marketplace listings only: title, price, general location, photos, listing URL, and posted time, for listings within about [50] miles of Conway, Arkansas. Keywords are items I know how to repair or resell. I do not log in with any account to collect, I do not collect from private groups or non-public content, and I do not collect private messages or profile data.

How it is limited.
- Read-only: the tool never posts, messages sellers, or interacts with Facebook. Any contact with a seller is done by me, personally, through Facebook's own Marketplace features.
- Volume: about 2,000 listings per week at most, collected in small scheduled batches, with rate limiting and back-off, and obeying robots.txt and similar signals.
- No resale or sharing of data: the data is stored on my computer, used only to evaluate listings for my own purchases, and is not sold, licensed, sublicensed, published, or given to anyone. Seller names and profile fields are not stored; listings are deleted after [30] days.
- Security: stored on an encrypted disk with a single-user login; no cloud sharing.
- Attribution: where I display a listing, I show that it is from Facebook Marketplace and link to the original listing.
- Audit and revocation: I will keep records for at least one year as your terms require, will cooperate with any audit, and will stop immediately if you restrict or revoke permission.

Request. Please tell me (1) whether you will grant written permission for this use or which Meta program or API (for example the Meta Content Library and API, or any Marketplace data program) I should apply to, (2) what eligibility and agreement terms would apply, and (3) any technical limits you require.

I understand that I may not collect Meta data by automated means until permission is granted, and I will not do so in the meantime through my own tools. [OWNER: delete this sentence if you are using a paid provider in the meantime, and say so honestly instead: "I currently use a third-party data provider, [NAME], and will stop if you instruct me to."]

Thank you for your time.

Michael [LAST NAME]
[EMAIL] [PHONE] [ADDRESS]
```

Review notes for the owner:
- The bracketed sentence matters. If you use a provider before permission, do not claim you do not collect; say so honestly or wait. INFER: waiting is the cleanest legal posture, but you already chose to accept the risk in (b).
- Do not name any other people or Meta employees; do not attach secrets.
- Keep a copy; log the send date.

## 5. Sources (all read 2026-10-12)
- Meta Automated Data Collection Terms, effective 2024-10-07: https://www.facebook.com/legal/automated_data_collection_terms
- Meta Content Library and API: https://developers.facebook.com/docs/content-library-and-api/
- Apify actor: https://apify.com/apify/facebook-marketplace-scraper and changelog https://apify.com/apify/facebook-marketplace-scraper/changelog.md (latest entries 2026-09-10; no radius option mentioned)
- Apify DPA (updated 2026-07-08): https://docs.apify.com/legal/data-processing-addendum
- Apify Black Falcon actor (search summary only): https://apify.com/blackfalcondata/facebook-marketplace-scraper
- Bright Data dataset: https://brightdata.com/products/datasets/facebook/marketplace
- Bright Data scraper: https://brightdata.com/products/web-scraper/facebook/marketplace
- Bright Data API doc: https://docs.brightdata.com/api-reference/scrapers/social-media-apis/facebook-marketplace-collect-by-url
- Not verified here: any provider's own acceptable-use and data-retention terms (UNK, owner or next task should read them before signing up).
