# Receipt — Round-One Marketing Research

- **Timestamp:** 2026-10-06
- **Agent:** 07 (Marketing)
- **Related output:** `docs/research/agent-07-marketing.md`, ADR-0001, ADR-0002

## Method / provenance
Three parallel web-research sweeps were run (read-only; WebSearch/WebFetch). Each separated FACT (vendor developer/support docs, Google policy pages, one peer-reviewed study) from INFERENCE/RECOMMENDATION/UNKNOWN. No accounts created, nothing published, no spend.

## Sweep 1 — OSS automation / CRM / email / analytics platforms
- **Checked:** repos, licenses, activity for n8n, Activepieces, Windmill, Huginn, Mautic, Twenty, Munin + alternates (Node-RED, EspoCRM, SuiteCRM, Odoo, Listmonk, Postal/Mailu, Chatwoot, Cal.com, Umami, Plausible, Matomo, Baserow, NocoDB).
- **Observed:** n8n = Sustainable Use License (~207k★, v2.43.x); Activepieces MIT; Windmill AGPL; Huginn MIT; Mautic GPL-3 v6.0.6; Twenty AGPL; **Munin = server monitoring, irrelevant**; Cal.com relicensed MIT "Cal.diy" Apr 2026; NocoDB moved to Sustainable Use Jan 2026. **No mature OSS for local-SEO/review/listing management.**
- **Confidence:** High on licenses/purpose (primary repos). Star counts/versions point-in-time. Chatwoot/Mailu/Postal exact edition licenses = UNKNOWN (verify before deploy).
- **Sources:** github repos listed above; license/activity corroborated via vendor sites + comparison articles (see §Appendix of research file).

## Sweep 2 — Listing-platform APIs (automate vs manual)
- **Checked:** Google Business Profile, Apple Business Connect, Bing Places, Meta Graph, Yelp, Nextdoor, listing-sync/aggregators.
- **Observed:** GBP = API suite behind allowlist + `business.manage`, quota 0 until approved, Q&A API discontinued Nov 3 2025, cannot create/verify listing; Apple = partner-only API, SMB manual web only; Bing = no confirmed self-serve REST API (portal/Excel); Meta = strong publishing API after ~2–4wk App Review; Yelp Fusion read-only + R2R partner-gated; Nextdoor organic manual.
- **Confidence:** High (vendor developer/support docs) EXCEPT: GBP Local Posts v4.9 status (official says Active, blogs dispute) = UNKNOWN; Bing self-serve API = UNKNOWN; Apple "Apple Business" Apr-2026 rebrand scope = INFERENCE.
- **Sources:** developers.google.com/my-business/content/{sunset-dates,prereqs,limits}; support.apple.com guide apple-business-partner-api-access; learn.microsoft.com/answers (Bing); docs.developer.yelp.com; developer.nextdoor.com.

## Sweep 3 — AEO/GEO, local SEO, schema, reviews, attribution
- **Checked:** AI-engine sourcing behavior, local ranking factors, schema.org types + Google rich-result support, Google review policy, attribution methods.
- **Observed:** AI Overviews pull from Google organic; ChatGPT ~85% from Bing top-10; Perplexity uses Reddit + Yelp Fusion. GEO study (arXiv 2311.09735, KDD 2024): stats +41%, quotes +28%, citations +115% in generated-answer visibility (benchmark, not live). llms.txt: no evidence of use. Whitespark 2025: GBP ~32%, Reviews ~20%. Schema: HomeAndConstructionBusiness JSON-LD; first-party review stars not rendered (2019 change); FAQ rich results deprecated May 7 2026 (keep FAQPage); BreadcrumbList rewarded. Google review policy: no gating, no incentives; 2026 clarification agency-interpreted.
- **Confidence:** High on the peer-reviewed GEO study, Google policy pages, schema.org hierarchy, and the 2019/2026 schema changes. MEDIUM on engine-sourcing percentages (vendor-measured, directional). UNKNOWN on causal schema→AI-visibility effect and exact 2026 review-policy enforcement scope.
- **Sources:** arxiv.org/pdf/2311.09735v1; support.google.com/contributionpolicy/answer/7400114; seroundtable.com (llms.txt); whitespark.ca; quattr.com/blog/faq-schema-in-2026; localo.com/blog/whitespark-localo-data.

## Uncertainty summary
Items requiring a live re-check before any build: GBP Local Posts v4.9 status + exact create/delete limits; Bing self-serve API existence; Apple rebrand flow; exact 2026 Google review-policy wording; contractor referral-fee legality by jurisdiction; Chatwoot/Mailu/NocoDB license specifics.
