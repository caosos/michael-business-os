# Agent Status

Agent: 07
Role: Marketing / Customer Acquisition / AI Discovery
Branch: research/agent-07-marketing
Worktree: /home/michaelos/business-os-worktrees/agent-07-marketing
State: COMPLETE
Current phase: Round One — research & design complete; coordination layer established
Started: 2026-10-06
Last updated: 2026-10-06

## Current objective
Round-One research/design deliverable is complete. Now reporting through GitHub per the coordination addendum: status file, research file at mandated path, decision records, and receipts pushed to this branch for Agent 01 to ingest. No publishing, no spend, no external action.

## Completed
- Full marketing architecture research & design deliverable (all 15 required RETURN items), with FACT/INFERENCE/RECOMMENDATION/UNKNOWN tagging → `docs/research/agent-07-marketing.md`.
- Three parallel research sweeps: (1) OSS automation/CRM/email/analytics platforms + licenses/activity; (2) listing-platform APIs (Google/Apple/Bing/Meta/Yelp/Nextdoor) automate-vs-manual; (3) AEO/GEO + local SEO + schema + reviews policy + attribution.
- Architecture that plugs into the OS flow (DISCOVER→…→APPROVE→ACT→RECEIPT→LEARN) and the YES/NO/MODIFY/HOLD gate.
- Automate-vs-approval-only matrix; anti-spam safeguards; ROI/cost model; 48-hour prep path.
- Two decision records for system-affecting recommendations (automation hub, CRM) → `docs/decisions/`.
- Research provenance receipt → `docs/receipts/`.

## Findings
**Verified facts (FACT):**
- **Only Google Business Profile and Meta (FB/IG) are reliably automatable via official API.** GBP requires an allowlist access request + OAuth `business.manage`; quota is 0 until approved (~days–2wk). GBP cannot create/verify a new listing (manual) and its Q&A API was discontinued Nov 3 2025.
- **Apple Business Connect has no self-serve SMB API** — manual web only (claim/verify/edit Apple Maps place card). Siri/Maps/Spotlight pull from it, so it must still be claimed manually.
- **Bing Places has no confirmed self-serve REST API** — portal + Excel bulk upload only; relaunched Oct 2025.
- **Yelp:** Fusion API read-only (cannot export own reviews); Respond-to-Reviews is partner-gated. Nextdoor organic posts = manual.
- **No mature open-source product exists for local-SEO/review/listing management (2026).** This is the one category where we glue APIs ourselves or accept a paid SaaS.
- **n8n** = Sustainable Use License (fair-code, not OSI; free for own-business use, no reselling), ~207k★, v2.43.x. **Activepieces** MIT. **Twenty** AGPL-3.0. **EspoCRM** AGPL-3.0. **Odoo CE** LGPL-3.0. **Mautic** GPL-3.0 v6.0.6. **Listmonk** AGPL-3.0. **Umami** MIT / **Plausible** AGPL. **Cal.com relicensed to MIT ("Cal.diy") Apr 2026** with enterprise features removed. **Munin is server monitoring — irrelevant to marketing.**
- **Local ranking factors (Whitespark 2025 expert survey):** GBP ~32%, Reviews ~20% (rising), On-page ~15%, Behavioral ~9%, Links ~8%, Citations ~6%.
- **Google prohibits review gating and incentivized reviews**; 2026 clarification also discourages on-premises asks, content-directed requests, and staff quotas.
- **AI engines source answers from the classic indexes:** AI Overviews from Google organic; ChatGPT from Bing (~85% overlap with Bing top-10); Perplexity from its own index + Reddit + Yelp Fusion. → Winning local SEO *is* the AEO strategy.
- **Schema:** `HomeAndConstructionBusiness` (LocalBusiness subtype) in JSON-LD; first-party review stars not rendered by Google (a 2019 change, not 2026); FAQ rich results deprecated May 7 2026 (keep `FAQPage` for AEO); `BreadcrumbList` still rewarded.
- **llms.txt has no evidence of working** — de-prioritized.

## Decisions made
- **Architecture: organic-first.** Build GBP + reviews + ranking service/FAQ pages before any paid acquisition; paid ads deferred to a later round.
- **Draft-by-default, publish-by-approval**, aligned with Agent 05's autonomy split. Two executor lanes: API lane (GBP, Meta) and manual-assist lane (Apple, Bing, Nextdoor, Reddit, classifieds).
- **Recommended stack (PROPOSED):** n8n (orchestration) · Twenty or EspoCRM (CRM) · Cal.diy (booking) · Listmonk→Mautic (email) · Chatwoot (inbound) · Umami/Plausible (analytics) · static site (Astro/Eleventy). See ADRs.

## Unknowns
- GBP Local Posts API v4.9 live status (official docs say Active; some 2026 blogs claim deprecated) — verify before building post automation.
- Exact GBP create/delete limits against current v4.9 reference.
- Whether any self-serve Bing Places REST API truly exists.
- Apple "Apple Business" (April 2026) rebrand effect on the claim/manage flow.
- Exact enforced scope of 2026 Google review-policy clarifications (agency-interpreted).
- Jurisdiction rules on contractor referral fees/kickbacks.
- Chatwoot / Mailu exact current edition licenses; NocoDB Sustainable-Use implications.

## Blockers
None currently. Round-One scope is complete and self-contained.

## Needs Michael decision
- **Pre-approved review-request templates?** Allow the compliant post-job review request to auto-send within hard caps (every send still logged as a receipt), or require individual approval for each? (Governance-adjacent; affects approval-fatigue at scale.)
- **Budget posture for the two most-justified future paid items:** DNI call tracking (~$35–50/mo, closes attribution gap) and listing-sync SaaS (~$39–100/mo, closes Apple/Bing automation gap). Not needed this round.

## Needs coordinator review
- **CRM selection conflict risk with Agent 04 (CRM/State):** marketing recommends Twenty (or EspoCRM/Odoo). Must converge on one CRM + shared contact/lead schema. See ADR-0002.
- **Automation hub shared infra:** n8n proposed as the marketing orchestrator; may overlap with coordinator/comms orchestration choices. See ADR-0001.
- **Email/SMS sending ownership vs Agent 06 (Communications):** avoid two agents running SMTP/deliverability.
- **Need from Agent 03 (Economics):** job-value/margin data to populate LTV and per-channel CAC in the ROI model.
- **Need from Agent 05 (Governance):** final approval-object schema, kill-switch/rate-limit interfaces, prompt-injection handling for untrusted inbound (reviews/chat), secrets handling for API tokens.

## Files produced
- `docs/research/agent-07-marketing.md` — full Round-One marketing architecture deliverable.
- `docs/status/AGENT_STATUS.md` — this file.
- `docs/decisions/ADR-0001-automation-orchestration-hub.md` — n8n as automation hub (PROPOSED).
- `docs/decisions/ADR-0002-crm-selection.md` — CRM selection, needs Agent 04 reconciliation (PROPOSED).
- `docs/receipts/2026-10-06-marketing-research.md` — research provenance receipt.

## Next action
Hold for Agent 01 coordinator review. On request, proceed to draft website copy + JSON-LD schema templates (Hours 8–20 of the 48-hour prep path) — all as drafts, nothing published.
