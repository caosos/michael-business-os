# Agent 07 — Marketing / Customer Acquisition / AI Discovery
## Round-One Research & Design Deliverable

**Date:** 2026-10-06
**Author:** Agent 07 (Marketing)
**Status:** Research/design only. Nothing in this document has been published, provisioned, purchased, or acted upon.
**Consumer:** Agent 01 (Coordinator) for integration; Agent 05 (Governance) for approval-model alignment.

**Operating assumptions (confirmed with Michael):**
- **Greenfield** — no website, no Google Business Profile, no listings exist yet. Design builds from zero.
- **Free / self-hosted first** — prefer OSI/fair-code open source, self-hosted. Pay only where unavoidable (domain, email deliverability relay, call tracking, listing sync).
- **Design for growth** — start solo (Michael), architect so it scales to a small team without re-platforming.
- Services: mobile repair, equipment repair, furniture assembly, drywall/small repair, smart-home install (cameras, thermostats, locks, doorbells, lighting, sensors, Wi-Fi/networking), appropriate accessibility mechanical work. This is a **Service-Area Business (SAB)**.

**Legend:** **[FACT]** = verified against a cited source · **[INF]** = inference/synthesis · **[REC]** = recommendation · **[UNK]** = unknown / unverified / needs live check.

> **Evidence caution [FACT]:** Most "2026 best-practice" marketing content online is vendor/agency material, not independent research. Ranking-factor percentages and "X× more likely" stats are expert-survey or vendor numbers — treat as prioritization heuristics, not physics. Primary sources (vendor developer docs, Google policy pages, the one peer-reviewed GEO study) are cited where they exist.

---

## 1. Executive Summary

The highest-leverage, lowest-risk growth engine for this business is **classic local SEO done exceptionally well**, because it simultaneously feeds the three things that matter in 2026:
1. The **Google local pack / Maps** (where local service demand converts),
2. **AI answer engines** — Google AI Overviews pull from Google organic, ChatGPT pulls from Bing's index, Perplexity reads Yelp + Reddit **[FACT]**, so winning organic + a review-rich profile *is* the AEO/GEO strategy, and
3. **Referral/word-of-mouth capture**, which a CRM + review loop compounds.

**Recommended spine:** a self-hosted automation hub (**n8n**) orchestrating a lean CRM (**Twenty** or **EspoCRM**), a booking tool (**Cal.diy**), email/marketing (**Listmonk** now, **Mautic** later), inbound chat (**Chatwoot**), and privacy analytics (**Umami/Plausible**) — all glued to the few platforms that expose APIs (Google Business Profile, Meta). Everything routes through Agent 05's **YES/NO/MODIFY/HOLD** approval gate before anything leaves the system.

**The hard constraints to design around:**
- **Apple Business Connect has no self-serve SMB API** — manual web only. **[FACT]**
- **Bing Places has no confirmed self-serve REST API** — portal / Excel bulk upload. **[UNK/FACT]**
- **GBP API cannot create a new listing or verify it** — initial setup is manual; API is for ongoing management and requires an **allowlist approval** (quota 0 until granted). **[FACT/INF]**
- **No mature open-source product exists for local-SEO / review / listing management** — this is the one category where we glue APIs ourselves or accept a paid SaaS. **[FACT]**
- Google **prohibits review gating and incentivized reviews**; a 2026 clarification also discourages on-premises asks and content-directed requests. **[FACT]**

**Anti-spam posture:** organic-first, consent-based, volume-capped, human-approved for anything outbound. The system is designed to *earn* demand (content, reviews, referrals) rather than *push* it.

---

## 2. Recommended Marketing Architecture

### 2.1 How marketing plugs into the Business OS core flow

The coordinator's canonical flow is `DISCOVER → NORMALIZE → RESEARCH → SCORE → RECOMMEND → MICHAEL APPROVES → ACT → RECEIPT → OUTCOME → LEARN`. Marketing is both a **producer of outbound actions** (posts, review requests, emails, replies) and a **source of inbound leads** (which become opportunities Agent 02 scores). Marketing actions are gated exactly like any other external action.

```
                         ┌─────────────────────────────────────────────┐
                         │          AGENT 07 MARKETING SUBSYSTEM         │
                         └─────────────────────────────────────────────┘

  SIGNAL / DISCOVERY            DRAFTING (autonomous)        APPROVAL GATE (Agent 05)
  ┌───────────────┐            ┌────────────────────┐       ┌──────────────────────┐
  │ GBP metrics   │            │ Content generator  │       │  Michael reviews:     │
  │ reviews feed  │──────────▶ │ (service pages,     │─────▶ │  YES / NO / MODIFY /  │
  │ web analytics │            │  posts, replies,    │       │  HOLD                 │
  │ form/call leads│           │  review requests,   │       │  (messages, publish,  │
  │ inbound chat  │            │  emails, referrals) │       │   email, scheduling)  │
  └───────┬───────┘            └─────────┬──────────┘       └───────────┬──────────┘
          │                              │                              │ approved
          ▼                              ▼                              ▼
  ┌───────────────┐            ┌────────────────────┐       ┌──────────────────────┐
  │   CRM (lead   │◀───────────│   n8n ORCHESTRATOR  │◀──────│  ACTION EXECUTOR      │
  │   + source)   │   leads    │  (workflows, queues │       │  (API calls / draft   │
  │  Twenty/Espo  │───────────▶│   cron, webhooks)   │──────▶│   for manual publish) │
  └───────┬───────┘            └─────────┬──────────┘       └───────────┬──────────┘
          │                              │                              │
          │                              ▼                              ▼
          │                    ┌────────────────────┐       ┌──────────────────────┐
          │                    │  RECEIPT / PROVENANCE│      │  CHANNELS             │
          └───────────────────▶│  log (every action,  │      │  API: GBP, Meta       │
             outcome/revenue   │  provenance, cost)   │      │  Manual: Apple, Bing, │
                               └──────────────────────┘      │   Nextdoor, Yelp      │
                                                             └──────────────────────┘
```

**Design principles [REC]:**
- **Draft-by-default, publish-by-approval.** The system may research and draft anything; it may *send/publish* nothing without an approval receipt. This matches Agent 05's autonomy split exactly (drafting autonomous; messages/publishing/scheduling/email require approval).
- **One canonical lead record.** Every inbound (call, form, chat, review, referral) becomes a CRM contact carrying its attribution source through to revenue (closed-loop).
- **No action without a receipt; no receipt without provenance** — marketing actions emit the same receipt object the rest of the OS uses (what, when, which channel, which approval, what it cost, source draft + prompt).
- **API-where-possible, human-browser-where-required** — the executor has two lanes: an *API lane* (GBP, Meta) and a *manual-assist lane* that produces a ready-to-paste draft + checklist for Michael to publish in a browser (Apple, Bing, Nextdoor organic).

### 2.2 Component stack (self-hosted first)

| Layer | Pick | Alternate | Why |
|---|---|---|---|
| Orchestration / workflows | **n8n** | Activepieces (if strict OSI license needed) | Richest connector + webhook + AI node library; the glue. **[INF]** |
| CRM | **Twenty** | EspoCRM (lighter) / Odoo CE (if you want invoicing+dispatch too) | Lead + source + pipeline; scales to a team. **[INF]** |
| Booking | **Cal.diy** | — | Self-hosted appointment capture → CRM. **[FACT: relicensed MIT Apr 2026]** |
| Email / campaigns | **Listmonk** (start) → **Mautic** (later) | — | Listmonk = simple reliable sends; Mautic when you need drip/scoring. **[INF]** |
| Inbound chat / shared inbox | **Chatwoot** | — | Captures website/social DMs as leads. **[INF]** |
| Web analytics / attribution | **Umami** or **Plausible** | Matomo (richest) | Privacy-first, own the data; UTM capture. **[FACT: licenses]** |
| Website / CMS | Static site (Astro/Eleventy) or lightweight CMS | WordPress (bigger ecosystem) | Fast, cheap, easy JSON-LD control. **[REC]** |
| Email delivery (SMTP) | Paid relay (SES/Postmark) | self-host Postal/Mailu | Deliverability is hard; a relay is the pragmatic paid line. **[INF]** |
| Local-SEO / listing sync | **(gap — glue via API) + optional paid SaaS** | BrightLocal / Moz Local / SE Ranking | No mature OSS exists. **[FACT]** |

---

## 3. Organic-First Plan

**Thesis [INF]:** For a local SAB, paid ads are optional; the compounding assets are (1) a fully-optimized Google Business Profile, (2) real reviews, and (3) service/FAQ pages that rank organically — which also feed AI answers. Build those before spending a dollar on ads.

**Priority order (highest real leverage first) [INF, grounded in Whitespark 2025 factor weights]:**
1. **Google Business Profile** — create, verify, fully populate (categories, services, service areas, photos, hours, description). GBP is ~32% of local-pack influence. **[FACT: Whitespark 2025 survey]**
2. **Reviews engine** — compliant post-job request to *every* customer. Reviews ~20% and rising. **[FACT]**
3. **Service pages that rank** — one strong page per service line with prices, inclusions, FAQs, real photos. On-page ~15%. **[FACT]**
4. **Behavioral signals** — make calling/booking/getting directions frictionless (calls, direction requests, clicks are weighted ~9%). **[FACT]**
5. **Citations / NAP consistency** — one canonical Name/Address/Phone everywhere (~6%; value is consistency not volume). **[FACT]**
6. **Off-site entity presence** — the domains AI engines over-cite (Reddit, YouTube, LinkedIn) + authoritative local directories. **[FACT/INF]**
7. **Referrals & contractor network** — structured word-of-mouth (see §11).

Paid acquisition (Google LSA/Ads, Meta ads) is explicitly **deferred to a later round** and out of scope for Round One (no spend).

---

## 4. Tools / Repos — URLs, Licenses, Activity

> All licenses/activity verified Oct 2026; star counts and versions drift — treat as point-in-time. **[FACT]** unless noted.

### 4.1 The seven platforms named in the brief

| Platform | URL | License | Activity (2026) | Role here |
|---|---|---|---|---|
| **n8n** | github.com/n8n-io/n8n | Sustainable Use License (fair-code, **not** OSI) | ~207k★, v2.43.x, very active | **Adopt** — orchestration hub |
| **Activepieces** | github.com/activepieces/activepieces | **MIT** | ~22–24k★, active | Alternate hub (cleanest license) |
| **Windmill** | github.com/windmill-labs/windmill | AGPL-3.0 (+ Ent.) | active | Skip unless code-first scripting needed |
| **Huginn** | github.com/huginn/huginn | **MIT** | ~49.6k★, releases 2026.09 | Optional — web monitoring/scraping agents |
| **Mautic** | github.com/mautic/mautic | GPL-3.0 | v6.0.6 (Sep 2025), active | **Adopt later** — full marketing automation |
| **Twenty** | github.com/twentyhq/twenty | AGPL-3.0 | ~52–58k★, active (YC S23) | **Adopt** — CRM |
| **Munin** | github.com/munin-monitoring/munin | GPL-2.0-only | maintained | **Irrelevant** — server monitoring, not marketing **[FACT]** |

> **n8n license note [FACT]:** Sustainable Use License (since Mar 2022). Free to self-host for your own business; you may **not** resell n8n as hosted SaaS. Fine for us.

### 4.2 Stronger / alternative candidates discovered

| Category | Tool | URL | License | Fit |
|---|---|---|---|---|
| Automation | Node-RED | nodered.org | Apache-2.0 | Only if wiring smart-home/IoT hardware **[FACT]** |
| Automation | Automatisch | automatisch.io | AGPL-3.0 | Simpler but ~80 connectors, slow cadence **[FACT]** |
| CRM | **EspoCRM** | espocrm.com | AGPL-3.0 | Lean PHP CRM, <400MB RAM **[FACT]** |
| CRM | SuiteCRM | suitecrm.com | AGPL-3.0 | Heavier Salesforce-style suite **[FACT]** |
| CRM/ERP | **Odoo CE** | odoo.com | LGPL-3.0 | CRM + invoicing + field-service dispatch in one **[FACT]** |
| Email | **Listmonk** | listmonk.app | AGPL-3.0 | Single Go binary; fast newsletters **[FACT]** |
| SMTP | Postal / Mailu | postalserver.io / mailu.io | MIT / UNK | Self-host sending (deliverability burden) **[FACT/UNK]** |
| Chat | **Chatwoot** | chatwoot.com | MIT (editions vary — verify) | Omnichannel inbound inbox **[FACT/UNK]** |
| Booking | **Cal.diy** | github.com/calcom | MIT (relicensed Apr 2026; enterprise features removed) | Self-host booking **[FACT]** |
| Analytics | **Umami** | umami.is | MIT | Lightest privacy analytics **[FACT]** |
| Analytics | **Plausible CE** | plausible.io | AGPL-3.0 | Clean privacy analytics **[FACT]** |
| Analytics | Matomo | matomo.org | GPL-3.0 | Richest (some paid plugins) **[FACT]** |
| DB / tables | Baserow / NocoDB | baserow.io / nocodb.com | MIT / Sustainable Use (changed Jan 2026) | Lightweight job/customer tables **[FACT]** |

### 4.3 Local-SEO / review / listing management — the gap

**[FACT]** There is **no mature self-hostable open-source platform** for GBP/review/listing management in 2026. Options:
- **Glue it ourselves:** n8n + GBP API to pull reviews, trigger alerts, draft replies, schedule posts.
- **Accept a paid SaaS** for citation/listing consistency (the manual-API platforms): **BrightLocal** (~$39/mo), **Moz Local** (90+ dirs incl. Apple/Bing/Data Axle/Neustar), **SE Ranking**, **Localo**. **[FACT: all proprietary]** — deferred (no spend this round); flagged as the most likely justified future expense.

---

## 5. API / Platform Limitations (the automate-vs-manual reality)

### 5.1 Listing/map platform matrix

| Platform | Official API? | Automatable (with approval) | Manual-only | Approval needed |
|---|---|---|---|---|
| **Google Business Profile** | **Yes** (suite of ~8 APIs) | Read/update location info; read reviews + **post replies**; create/manage **local posts**; performance metrics; media; place actions | **Create new listing + verify**; delete/hide reviews; **Q&A (API killed Nov 3 2025)** | Allowlist request form + OAuth `business.manage`; **quota 0 until approved** (~days–2wk) |
| **Apple Business Connect** | Partner-only API | (Partners only) brand/showcases/reviews at scale | **For a single SMB: everything manual web** (claim, verify, edit place card) | Apple-approved partner org only |
| **Bing Places** | **No confirmed self-serve REST API** | Bulk create/update via **Excel upload**; Google import | Single-location portal edits | Any true API appears partner-gated **[UNK]** |
| **Meta (FB/IG)** | **Yes** (Graph API — most mature) | Publish FB Page + IG posts/Reels/Stories/carousels; read/manage comments; insights | Posting to personal FB timeline | Meta app + **App Review (~2–4 wk)**; scopes `pages_manage_posts`, `instagram_business_content_publish`, etc. |
| **Yelp** | Yes (2 APIs) | Fusion: read public data (**cannot export own reviews**); R2R: post owner replies (≤20/day) | Posting reviews; private responses | Fusion key (easy); **R2R = partner agreement** |
| **Nextdoor** | Partner APIs | Ads API (campaigns/reporting) if partner | **Organic business posts = manual** | Partner application |
| **Listing-sync (Yext/Uberall/Moz/BrightLocal)** | Yes (they *are* the aggregation layer) | Push NAP across 90–200+ dirs incl. Apple/Bing/Yelp | — | Paid subscription |

**All of the above are [FACT]** from vendor developer/support docs, **except** the Apple "Apple Business" rebrand scope (April 2026, third-party-sourced **[INF]**) and the Bing self-serve API status **[UNK]**.

### 5.2 Three items to re-verify live before building (flagged by research)
1. **[UNK]** GBP **Local Posts API v4.9** — Google's official sunset page lists it **Active**, but several 2026 blogs claim deprecation. Pull the live v4.9 reference before building post automation.
2. **[UNK]** Exact GBP limits ("can't create listing / can't delete review") against the current v4.9 reference.
3. **[UNK]** Whether any self-serve Bing Places REST API truly exists vs partner-only.

**Implication [REC]:** Treat **Google + Meta as the only reliably automatable channels**. Everything else (Apple, Bing, Nextdoor organic, Yelp posting) uses the **manual-assist lane** — the system drafts; Michael publishes in a browser — or a future paid listing-sync tool.

---

## 6. Website / Local-SEO Structure

**You are a Service-Area Business [INF]:** hide street address in GBP, define service-area regions, pick the most specific primary category per core service and use secondary categories for the rest. Prioritize the highest-margin/highest-volume service as the GBP primary category.

### 6.1 Information architecture [REC]

```
/                                   home: brand, service menu, service-area map, proof, CTAs
/services/                          hub linking all service lines
  /services/mobile-repair/
  /services/equipment-repair/
  /services/furniture-assembly/
  /services/drywall-repair/
  /services/smart-home-installation/            (pillar page)
      /services/smart-home-installation/security-cameras/
      /services/smart-home-installation/smart-thermostats/
      /services/smart-home-installation/smart-locks/
      /services/smart-home-installation/video-doorbells/
      /services/smart-home-installation/smart-lighting/
      /services/smart-home-installation/sensors/
      /services/smart-home-installation/wifi-networking/
  /services/accessibility-modifications/
/areas/<city-or-region>/            ONLY real priority markets, unique content
  /areas/<city>/<top-service>/      service×location, only where you have real proof
/help/  (or /blog/)                 how-to + buyer-question content for AEO
/reviews/   /about/   /contact/
```

**Each service page [REC]:** plain-language definition, what's included, **typical price ranges**, how long it takes, service-area/constraints, embedded **question-first FAQ**, real job photos, licensing/insurance trust signals, single clear call/form/booking CTA.

**[FACT]** Service×city combination pages with genuinely unique local content outperform generic "service areas" pages; thin near-duplicate city pages are discouraged in 2026. **Build service pages first; add location pages only where you genuinely operate and can write unique content** — never programmatic doorway pages (ranking/penalty risk).

**Internal linking [REC]:** hub-and-spoke (pillar → sub-services → related FAQ/blog; location → relevant service) — serves crawlers and AI passage extraction.

---

## 7. Schema / Structured Data Strategy

**Implement as JSON-LD (Google's recommended format) [FACT]:**
- **`HomeAndConstructionBusiness`** (a `LocalBusiness` subtype) as the core entity — `name`, `address`/`areaServed`, `telephone`, `geo`, `openingHours`, `priceRange`, `url`, and **`sameAs`** → GBP, Yelp, Facebook, LinkedIn, YouTube (entity disambiguation). Use the most specific subtype available per context. **[FACT: schema.org hierarchy]**
- **`Service`** per service line — `serviceType`, `areaServed`, `provider`, optional **`Offer`** / price range.
- **`BreadcrumbList`** — still a supported, rewarded rich result. **[FACT]**
- **`FAQPage`** — **keep for AEO/extractability** even though FAQ rich results are gone (below). **[FACT]**
- **`AggregateRating`/`Review`** — include (feeds ranking/AI understanding) but **do not expect star snippets on your own site**.

**Critical schema facts to not get wrong [FACT]:**
- **First-party `LocalBusiness`/`Organization` review stars are NOT rendered by Google** — this is a **2019** change, not new 2026 news (many blogs misframe it). Google still *reads* AggregateRating; stars only render from third-party sites (Google, Yelp). So the star-visibility play is **reviews on GBP/Yelp**, not markup on your own site.
- **FAQ rich results are fully deprecated as of May 7, 2026** (all sites); Search Console FAQ reports being removed. `FAQPage` schema stays valid and crawled — keep it for AEO, expect no visual rich result.
- **`HowTo` rich results deprecated (desktop) Sept 2023.**

**[UNK]** Whether/how much schema causally affects AI-answer inclusion is unproven (correlational vendor claims only). Implement it for correctness and extractability, not on a promised AI-visibility ROI.

---

## 8. Google / Apple / Bing Plan

### 8.1 Google (the priority channel)
1. **[Manual]** Create & verify GBP (cannot be done via API). Set SAB mode, hide address, define service areas.
2. **[Manual]** Choose most-specific **primary category** (e.g. Handyman / Electrician / Furniture Assembly Service / Drywall Contractor) + secondary categories for other services. No keyword stuffing in business name (suspension risk). **[FACT]**
3. **[Manual]** Populate: services, description, hours, real photos, products/price ranges.
4. **[API, after allowlist]** Automate via GBP APIs: pull reviews → draft replies for approval; schedule/publish local posts (verify v4.9 status first); pull performance metrics into attribution; monitor Q&A manually (API gone).
5. Tag the GBP website link with a **UTM** so GBP-driven traffic is distinguishable.

### 8.2 Apple (manual, but claim it — Siri/Maps/Spotlight depend on it)
- **[Manual only]** Claim & manage the Apple Maps place card via **Apple Business Connect** website with an Apple ID. **No SMB API.** **[FACT]**
- Siri/Apple Maps/Spotlight/Wallet surfaces pull from this listing — claiming matters even without automation.
- **[INF]** Watch the April 2026 "Apple Business" rebrand (Business Connect data migrates automatically); re-verify the self-service flow at claim time.

### 8.3 Bing (manual / bulk)
- **[Manual]** Create via the relaunched **bing.com/forbusiness** portal (supports Google import). **[FACT]**
- For multiple locations later: **Excel bulk-upload** tool.
- **[UNK]** No confirmed self-serve REST API — do not plan API automation; revisit if a listing-sync tool is adopted (they hold Bing publisher integration). Feeds Bing search + Windows/Copilot + (indirectly) ChatGPT.

---

## 9. AEO / GEO / AI-Search Visibility Strategy

**Core realization [FACT]:** You influence AI answers mostly by winning the indexes they read, not by special AI tricks:
- **Google AI Overviews** lean on pages already ranking in Google organic (and appear on a large share of local queries).
- **ChatGPT search** draws largely from **Bing's index** (~85% citation overlap with Bing top-10 in studies).
- **Perplexity** uses its own freshness-weighted index, cites **Reddit** heavily, and **integrates Yelp's Fusion API for local-business data/reviews**.
- A small set of domains (Reddit, Wikipedia, YouTube, LinkedIn) accounts for a majority of citations across engines.

**Therefore [REC]:**
1. **Win classic local SEO + organic rankings** (covered in §3/§6) — this is 80% of AEO for a local business.
2. **Make pages extractable:** direct question→answer phrasing, concrete specifics (price ranges, response times, service boundaries), **named statistics**, and **citations to authoritative sources**. This is the one tactic with controlled-study support: the Princeton/GA-Tech **GEO study (arXiv 2311.09735, KDD 2024)** found adding statistics (+41%), quotations (+~28%), and authoritative citations (up to +115% for lower-ranked pages) improved visibility in generated answers. **[FACT — but a benchmark/simulation, not measured on live ChatGPT/Gemini.]**
3. **Review-rich GBP + Yelp** — because Perplexity reads Yelp directly and reviews drive local ranking.
4. **Off-site entity presence** on over-cited domains: a genuine (non-spammy) **Reddit** footprint answering local questions, **YouTube** how-to clips (thermostat/doorbell installs), a **LinkedIn** company page, authoritative local directories — all with consistent NAP + `sameAs`.

**Explicitly do NOT prioritize [FACT]:**
- **llms.txt** — strong evidence it does nothing (Google's Mueller: "no AI system currently uses llms.txt"; ~97% of llms.txt files get zero requests). Harmless to add; expect no gains.
- Unverified vendor stats like "FAQ schema → 2.8× more likely in AI answers" — no traceable source. **[UNK]**

**[UNK]** AI-answer-engine referrals are **hard to attribute** — they arrive as "direct" / no referrer with no standardized UTM. Expect a measurement gap; the "how did you hear about us?" field is the only reliable capture (see §13).

---

## 10. Community / Social Strategy

**Principle [REC]:** be genuinely useful in local community channels; never spam. Automation *drafts and schedules*; a human publishes anything that touches a community space, and organic community posts are mostly **manual-lane** anyway (no APIs).

| Channel | API? | Approach |
|---|---|---|
| **Facebook Page / Instagram** | **Yes** (Graph API, ~2–4wk App Review) | Automate drafting + (approved) publishing of job photos, before/afters, tips, seasonal reminders. Strongest automatable social channel. **[FACT]** |
| **Nextdoor** | Organic = **manual** | High-value for neighborhood home-services demand. Manual-assist drafts; Michael posts. Consider Nextdoor's "Neighborhood Faves." **[FACT]** |
| **Reddit** (local city subs, r/HomeImprovement, smart-home subs) | — | **Earn** presence by answering real questions helpfully (matters for AEO). Strict no-spam; disclose affiliation. Manual, human-paced. **[INF]** |
| **YouTube** | — | How-to clips (install a video doorbell, mount a camera) → embed on service pages; cited by AI. **[INF]** |
| **Local FB groups / community boards** | — | Manual, value-first participation; follow each group's self-promo rules. **[INF]** |
| **Classified / service posts** (Craigslist, etc.) | — | Manual-lane, capped, templated-but-varied, no duplicate spam. **[INF]** |

**Cadence guardrail [REC]:** a modest, consistent schedule (e.g. 2–3 posts/week drafted, human-approved) beats bursts. Per-channel daily caps enforced in n8n (see §16).

---

## 11. Contractor / Referral Strategy

**Why [INF]:** contractors (GCs, electricians, realtors, property managers, interior designers, moving companies) generate steady overflow and complementary work (e.g. a GC who doesn't do smart-home installs; a mover who doesn't assemble furniture). This is the highest-trust, lowest-cost acquisition channel.

**Design [REC]:**
- **Partner CRM segment** in Twenty/EspoCRM: track referral partners distinctly from customers, with a relationship owner and referral history.
- **Two-way referral agreement** (give to get): formalize who refers what; optionally a flat **referral fee or reciprocal arrangement** (money/commitments = **approval-gated**; must comply with any licensing/kickback rules for the trade/jurisdiction — **[UNK]**, needs Michael/legal check).
- **Outreach is approval-gated and personalized** — the system drafts a tailored intro per partner; Michael approves each send. **No cold-blast outreach** (anti-spam). Strict caps (e.g. ≤N new-partner contacts/day).
- **Referral tracking:** every referred lead tagged with the partner source → closed-loop ROI per partner → reinforces the best relationships.
- **Customer referrals:** a compliant "know someone who needs…?" ask in post-job follow-up (not tied to reviews; referral incentives to *customers* are fine — unlike review incentives — but still approval-gated and disclosed).

---

## 12. Review System

**Compliance first [FACT — Google Maps UGC policy]:**
- **No review gating** (can't route by expected sentiment / only ask happy customers).
- **No incentivized reviews** (no cash, discount, gift, contest, donation in exchange).
- 2026 clarification (agency-interpreted, **verify live [UNK]**): also avoid **on-premises asks** (counter/kiosk), **directing customers to mention specific staff/services**, and **staff review quotas**.
- **Allowed:** ask **all** customers equally, **after the job**, via email/SMS/QR/link, in **neutral open-ended language** ("We'd appreciate your honest feedback on Google"), and respond to all reviews.

**System design [REC]:**
1. On job completion in CRM → n8n triggers a **post-job review request** (SMS and/or email) to **every** customer, with a **direct Google review short-link**, neutrally worded. First draft auto-generated; **send is approval-gated** (or pre-approved as a policy-bounded template — see §15).
2. Lighter secondary nudge toward profiles AI engines read (Yelp — but follow Yelp's own anti-solicitation TOS). **[FACT]**
3. **No** scripted "mention [tech]" or "mention smart-home." **No** discounts for reviews.
4. **Review monitoring:** GBP Reviews API pulls new reviews → system **drafts a reply** → Michael approves → posted via API. Respond within ~1–2 days (trust + behavioral signal). **[FACT/INF]**
5. **Volume & frequency caps** and dedupe so no customer is asked twice.

---

## 13. Attribution Model

**Goal [REC]:** every lead carries its true source from first touch to closed revenue (closed-loop), despite the AI-referral measurement gap.

**Layers:**
- **Web analytics:** self-hosted **Umami/Plausible** (or Matomo) alongside/instead of GA4. **[FACT: privacy-first, own data]**
- **UTM discipline:** tag every link you control (GBP website link, GBP posts, social, email) with consistent UTMs.
- **First-party form capture [FACT best-practice]:** hidden fields for `utm_source/medium/campaign`, `gclid`, `referrer`, `landing_page`, populated by a small first-party JS snippet reading the URL + a first-touch cookie/localStorage. Pipe into the CRM so the source survives to the closed deal.
- **"How did you hear about us?"** — **required dropdown on every form + verbal question on every call.** Cheapest backstop; the *only* reliable capture for word-of-mouth and **AI-engine referrals** (which otherwise show as "direct"). **[FACT/INF]**
- **Call attribution:** best is **Dynamic Number Insertion (DNI)** call tracking (CallRail ~std, KeyMetric ~$35/mo) — a **paid** line, deferred. Budget-free fallback: **distinct phone numbers per major channel** (one on GBP, one on website, one on flyers) + log source per call. Use **GBP's free "calls" metric** for profile-originated calls. **[FACT]**
- **GBP performance metrics** (calls, direction requests, website clicks, search queries) pulled via API into the attribution store — the closest thing to free local-pack attribution. **[FACT]**

**Attribution object [REC]:** `{lead_id, first_touch_source, first_touch_detail(utm/gclid), self_reported_source, channel, created_at, became_customer, revenue, job_type}` stored on the CRM contact, feeding the ROI model.

---

## 14. ROI Model

**[REC]** Measure per channel and per campaign, closed-loop:

- **Core metric: CAC per channel** = channel cost (tooling share + ad spend + time) ÷ customers acquired via that channel.
- **LTV** = avg job value × repeat rate × referral multiplier (home services has strong repeat + referral potential).
- **Channel ROI** = (attributed revenue − channel cost) ÷ channel cost.
- **Leading indicators** (before revenue accrues): GBP calls/direction-requests/clicks, review count & avg rating, organic rankings for target service×city terms, form fills, booking rate.

**Round-One cost picture (design-time estimate, nothing spent) [INF]:**
| Item | Self-hosted-first cost |
|---|---|
| Domain | ~$10–20/yr (unavoidable) |
| Server/VPS for the stack (or Michael's existing box) | $0–20/mo |
| Email deliverability relay (SES/Postmark) | $0–15/mo (SES ~$0.10/1k) |
| All OSS software (n8n, Twenty, Cal.diy, Listmonk, Chatwoot, Umami) | $0 (self-hosted) |
| **Optional later:** call tracking (DNI) | ~$35–50/mo |
| **Optional later:** listing-sync SaaS (Moz Local/BrightLocal) | ~$39–100/mo |

**ROI framing [INF]:** the organic engine's dominant cost is **Michael's time**, not cash. The model should price time explicitly so "free" channels aren't mistaken for zero-cost. First paid dollars are best justified for **call tracking** (closes the attribution gap) and **listing sync** (closes the Apple/Bing automation gap) — only once organic lead flow proves the funnel.

---

## 15. Approval Workflow

Aligns with Agent 05's model (drafting autonomous; messages/offers/money/publishing/scheduling/email/SMS/calls/external commitments require approval) and the **YES / NO / MODIFY / HOLD** interface.

**Approval object (marketing extension of the OS receipt) [REC]:**
```json
{
  "approval_id": "...",
  "action_type": "gbp_post | review_request | review_reply | social_post |
                  email_campaign | partner_outreach | classified_post",
  "channel": "google | meta | nextdoor | email | sms | ...",
  "draft": { "subject": "...", "body": "...", "media": ["..."], "link_utm": "..." },
  "recipients_or_target": "...",
  "provenance": { "source_trigger": "...", "generator_prompt": "...", "model": "..." },
  "policy_checks": { "anti_spam": "pass", "consent": "verified", "caps_ok": true,
                     "review_policy": "compliant" },
  "estimated_cost": 0.0,
  "requested_at": "...", "decision": "YES|NO|MODIFY|HOLD", "decided_at": "...",
  "receipt_id": "..."
}
```

**Flow [REC]:**
1. Trigger (job completed, new review, scheduled post slot, inbound lead) → autonomous **draft** + **policy pre-checks**.
2. Item enters Michael's approval queue (YES/NO/MODIFY/HOLD). **MODIFY** edits the draft; **HOLD** parks it.
3. On **YES** → executor acts (API lane) or emits a ready-to-publish packet (manual lane) → **receipt** written with provenance + cost.
4. **Outcome** (did it post? engagement? lead?) recorded → feeds LEARN.

**Pre-approved policy templates [REC/INF]:** to avoid approval fatigue at scale, allow Michael to *pre-approve* narrow, policy-bounded templates (e.g. the neutral post-job review request) within hard caps — every send still logs a receipt and remains auditable/revocable. This is a governance decision to confirm with Agent 05.

---

## 16. Anti-Spam Safeguards

**Design-level [REC]:**
- **Consent & permission basis** — email/SMS only to customers/partners with a lawful basis; honor unsubscribe/STOP immediately; segment opted-in only.
- **Organic-first, earn-don't-push** — the system is built to create content/reviews/referrals, not to blast.
- **Hard volume caps per channel per day** enforced in n8n (e.g. ≤X review requests, ≤Y partner intros, ≤Z community posts). Global daily outbound ceiling.
- **Dedupe & frequency caps** — never contact the same person twice for the same purpose; cool-down windows.
- **Human approval for all outbound** (per §15) — no un-approved message ever leaves.
- **Content variation, no duplicate-spam** — classified/community posts templated but varied; no identical cross-posting that trips spam filters.
- **Channel-policy compliance built in** — review policy (no gating/incentive/content-direction), platform TOS (Yelp anti-solicitation, Nextdoor/Reddit self-promo rules), CAN-SPAM/CASL-style email rules, SMS consent rules. **[FACT where cited; jurisdiction specifics UNK]**
- **Kill switch & rate-limit** (inherit Agent 05's) — one switch halts all outbound.
- **Prompt-injection defense** — inbound content (reviews, chat messages, listings) is untrusted; the drafting agent treats it as data, never instructions (coordinate with Agent 05's defenses).
- **Provenance on everything** — every outbound action traceable to a trigger, a draft, an approver.

---

## 17. Automate vs Approval-Only Matrix

| Capability | Autonomous (no approval) | Approval-gated (YES/NO/MODIFY/HOLD) | Manual-only (human in browser) |
|---|---|---|---|
| Market/keyword/competitor research | ✅ | | |
| Draft content (pages, posts, replies, emails) | ✅ | | |
| Pull GBP metrics / reviews / analytics | ✅ (read) | | |
| Rank/score leads, compute attribution & ROI | ✅ | | |
| **Publish GBP post** | | ✅ (API lane) | |
| **Reply to a review** | | ✅ (API lane) | |
| **Send review request (SMS/email)** | | ✅ *(or pre-approved template w/ caps)* | |
| **Publish FB/Instagram post** | | ✅ (API, after App Review) | |
| **Send email campaign** | | ✅ | |
| **Partner / contractor outreach** | | ✅ | |
| **Referral fees / money / commitments** | | ✅ (+ legal check) | |
| **Scheduling appointments** | | ✅ | |
| **Create/verify GBP listing** | | | 🖐️ (no API) |
| **Claim/manage Apple Business Connect** | | | 🖐️ (no SMB API) |
| **Create/manage Bing Places** | | | 🖐️ (no confirmed API) |
| **Nextdoor organic post** | | ✅ draft | 🖐️ publish |
| **Reddit / community participation** | | ✅ draft | 🖐️ publish (human-paced) |
| **Classified/service posts** | | ✅ draft | 🖐️ publish (capped) |

This matrix is the concrete contract for Agent 01/05 to wire into the OS permission model.

---

## 18. 48-Hour Operational Path (Round One — design/prep only, no publishing/spend)

> Everything below is **local/draft/dry-run**; nothing goes live, no accounts created, no money spent, CAOSCare untouched. "Prepare" = ready-to-execute once Michael approves in a later round.

**Hours 0–8 — Foundations & decisions**
- Finalize stack picks (n8n + Twenty + Cal.diy + Listmonk + Chatwoot + Umami) and confirm the 3 open decisions in §19 with Michael/Agent 01.
- Stand up the stack **locally** (Docker Compose, no public exposure) for evaluation only.
- Draft the **canonical NAP**, business name (policy-compliant), service list, and primary/secondary GBP categories.

**Hours 8–20 — Content & site scaffold**
- Generate the **website IA** (§6) and draft copy for home + 5 service pages + smart-home sub-pages (prices, inclusions, FAQs, trust signals) — as drafts.
- Author **JSON-LD templates** (§7): HomeAndConstructionBusiness, Service, BreadcrumbList, FAQPage, sameAs.
- Draft the **help/blog** seed list (10 buyer-question articles optimized for extraction).

**Hours 20–32 — CRM, attribution, workflows (dry-run)**
- Define CRM schema: lead/contact, **attribution object** (§13), partner segment (§11).
- Build (but don't arm) n8n workflows: inbound-lead→CRM, post-job→review-request draft, new-review→reply draft, social-post scheduler — all stopping at the **approval queue**.
- Build the first-party **UTM/gclid hidden-field** capture snippet and the "how did you hear about us?" field.

**Hours 32–44 — Channel prep & approval wiring**
- Prepare **GBP setup checklist** + API **allowlist request packet** (to submit later).
- Prepare **Apple Business Connect** and **Bing Places** manual setup checklists.
- Prepare **Meta app / App Review** requirements doc (scopes, assets).
- Draft the **approval object** + policy-check rules (§15/§16) for Agent 05 to review; propose pre-approved review-request template + caps.

**Hours 44–48 — Package for coordinator**
- Assemble: stack decision, site+schema drafts, CRM+attribution schema, workflow inventory (disarmed), channel checklists, approval/anti-spam spec, ROI model + cost sheet, and the **open questions** in §19.
- Hand off to Agent 01; nothing published.

---

## 19. Open Questions / Needs From Other Agents / UNKNOWNs

**Needs from Michael / Agent 01:**
- Business legal name, service-area geography, target primary GBP category, phone/email of record.
- Confirm **pre-approved template** policy (review requests within caps) — yes/no (Agent 05 call).
- Budget posture for the two most-justified future paid items: **DNI call tracking** and **listing-sync SaaS**.

**Needs from Agent 05 (Governance):** final approval-object schema, kill-switch/rate-limit interfaces, prompt-injection handling for untrusted inbound (reviews/chat), secrets handling for API tokens (GBP OAuth, Meta app, SMTP).

**Needs from Agent 04 (CRM/state):** reconcile CRM choice (Twenty vs EspoCRM vs Odoo) so marketing and CRM don't diverge; shared contact/lead schema.

**Needs from Agent 06 (Communications):** who owns email/SMS sending infrastructure and deliverability (avoid two agents running SMTP).

**Needs from Agent 03 (Economics):** job-value / margin data to populate LTV and per-channel CAC in the ROI model.

**UNKNOWNs to resolve before building (not assumptions to bake in):**
- **[UNK]** GBP Local Posts API v4.9 live status; exact create/delete limits.
- **[UNK]** Any self-serve Bing Places REST API.
- **[UNK]** Apple "Apple Business" (April 2026) rebrand effect on the claim/manage flow.
- **[UNK]** Exact enforced scope of the 2026 Google review-policy clarifications (verify at Google's support URL).
- **[UNK]** Jurisdiction rules on referral fees/kickbacks for the relevant trades.
- **[UNK]** Chatwoot / Mailu exact current edition licenses; NocoDB Sustainable-Use implications — verify before deploy.

---

## Appendix — Primary Sources (selected)

- Google Business Profile APIs — sunset dates / prereqs / limits: developers.google.com/my-business/content/{sunset-dates,prereqs,limits}
- Google Maps UGC (review) policy: support.google.com/contributionpolicy/answer/7400114
- Apple Business Partner API access: support.apple.com/guide/business/apple-business-partner-api-access-abcb4226f877/web
- Bing Places (Microsoft Q&A on API): learn.microsoft.com/en-us/answers/questions/5708229
- Yelp Respond-to-Reviews / Fusion: docs.developer.yelp.com/docs/respond-to-reviews-api-v2 ; business.yelp.com/data/products/fusion
- Nextdoor developer/advertising: developer.nextdoor.com
- GEO study (stats/quotes/citations effect): arxiv.org/pdf/2311.09735v1 (KDD 2024)
- llms.txt (no evidence): seroundtable.com/google-ai-llms-txt-39607.html
- Whitespark Local Search Ranking Factors 2025: via localo.com/blog/whitespark-localo-data
- First-party review stars removed (2019): whitespark.ca/blog/local-businesses-say-goodbye-to-review-snippets-in-google
- FAQ rich results deprecation (May 2026): quattr.com/blog/faq-schema-in-2026
- Tool repos/licenses: github.com/{n8n-io/n8n, activepieces/activepieces, windmill-labs/windmill, huginn/huginn, mautic/mautic, twentyhq/twenty, munin-monitoring/munin, knadh/listmonk}; espocrm.com; umami.is; plausible.io

*End of Round-One deliverable.*
