# Agent Status

Agent: 02
Role: Opportunity Discovery Engine
Branch: research/agent-02-opportunity
Worktree: /home/michaelos/business-os-worktrees/agent-02-opportunity
State: COMPLETE
Current phase: Round One — research & design (complete); reporting via GitHub per coordination addendum
Started: 2026-10-06
Last updated: 2026-10-07T04:02Z

## Current objective
Round-One research deliverable is complete and committed. Standing by for coordinator (Agent 01)
review and for Round-Two implementation go-ahead. No code, no scraping, no seller contact.

## Completed
- Full source-landscape research across 5 clusters (P2P marketplaces; auctions/gov surplus;
  estate sales/liquidations; service leads; automation tech & legal) via parallel research agents.
- Master source inventory, top-20 ranking, GitHub project survey, access-model matrix,
  do-not-automate list, normalized schema, dedup strategy, polling strategy, long-distance logic,
  first-3 collectors, 24h capability, and major-unknowns list.
- Primary deliverable: `docs/research/agent-02-opportunity.md`.
- Two decision records (schema; access-tiering/legal posture) — both PROPOSED, coordinator review required.
- Provenance receipt for the key verified facts.

## Findings
Key verified facts (FACT unless tagged):
- **eBay Browse API** — free (OAuth client-credentials), ~5k calls/day, geo + used + local-pickup filters.
  The only free, legal, reliable listings API in scope. Sold-comps (Marketplace Insights) are gated/restricted.
- **GSA Auctions API** — public REST (api.gsa.gov, 5k/day, 5 per 5s), JSON/XML, 0% buyer premium, includes a
  separate **sold-price dataset** on data.gov. Only sanctioned auction API in scope.
- **SAM.gov Opportunities API v2** — free official federal-contract API (key + registered IP).
- **Trash Nothing REST API** — official, free key, JSON/OpenAPI; covers Freecycle/Buy-Nothing incl. Little Rock.
- **Craigslist** — native `?format=rss` is effectively dead; now Cloudflare-gated. Workarounds: OpenRSS prepend,
  self-generated RSS (craigsfeed/GitHub Actions), or pycraigslist + FlareSolverr. Highest-volume free local source.
- **GovDeals** = primary Arkansas government-surplus channel (AR state store + cities + ARDOT); only official API is
  **seller-side**, so buyer access is internal-JSON/scrape (ToS-adverse). AR State Surplus & UCA/state entities
  liquidate here.
- **HiBid** — public GraphQL `LotSearch`, native **ZIP + 100mi radius**, ~301M closed-lot sold-price archive
  (strongest comps source). AllSurplus exposes `maestro.lqdt1.com/search/list` with true lat/lng radius.
- **0% buyer-premium** platforms (cheapest math): GSA Auctions, PublicSurplus, Municibid.
- Best GitHub repos: **BoPeng/ai-marketplace-monitor** (AGPL-3.0, active — FB monitor + AI scoring + ntfy);
  **scumola/govdeals** (MIT, 2026 — GovDeals hunter/scorer/sniper); jgdigitaljedi/gs-scraper (stale but mirrors our
  architecture + eBay-comp pattern); pycraigslist (MIT); pretorin-ai/govbizops (SAM.gov).
- **Licenses/costs:** APIs above are free. BoPeng monitor is **AGPL-3.0 (copyleft — integration caution)**. No free
  FOSS aggregator spans the domain; paid **Apify actors** are the "works-today" fallback (pay-per-run).
- **Legal (INFERENCE from case law):** logged-out public scraping at light rate, no block-evasion, no republishing is
  materially defensible (hiQ v. LinkedIn; Meta v. Bright Data 2024). Worst realistic case for a solo operator is an
  account/IP ban, not litigation — unless PII, resale, or block-evasion is involved.
- **Risks:** FB Marketplace = highest local volume but brittle + ban/ToS risk (HIGH). Internal gov-surplus endpoints
  = ToS-adverse (MED–HIGH). No free sold-comps source except HiBid archive + GSA dataset → must self-accumulate comps.

## Decisions made
- ADR-0201 (PROPOSED): a single source-agnostic **normalized opportunity schema** for both buy-items and
  service-leads. Affects Economics(03), State/CRM(04), Communications(06).
- ADR-0202 (PROPOSED): **source-access tiering** (API > sanctioned email/IMAP > internal endpoint > headless
  browser > manual) and a **do-not-automate / legal posture**. Affects Governance(05) and all collectors.
- Neither is marked ACCEPTED — both require Agent 01 cross-agent review.

## Unknowns
- Craigslist 2026 block thresholds; whether OpenRSS / pycraigslist+FlareSolverr reliably return current results.
- Whether GovDeals/HiBid/AllSurplus/GovPlanet internal endpoints still answer anonymously, and their rate/ban limits.
- eBay sold-comps gating — self-accumulate vs third-party service.
- FB Marketplace ban rate logged-out vs logged-in; proxy necessity; BoPeng monitor current working status.
- Solo-operator approval odds for Thumbtack Partner / Angi webhook / Google LSA verification.
- SAM.gov exact rate limits; Trash Nothing field/volume coverage; MaxSold/CTbids endpoint stability & ToS.
- Email-alert parsing: real formats/deliverability and whether alerts carry enough structured data.
- Image pHash dedup effectiveness across platforms.
(Full list in the research file, §12.)

## Blockers
None.

## Needs Michael decision
- Risk tolerance for **internal-endpoint access on ToS-adverse gov-surplus sites** (public data, but against ToS).
  This sets how aggressive Tier-3 collectors may be. Business-owner call, not a technical one. (See ADR-0202.)
- Whether to budget for paid fallbacks (Apify actors; a third-party eBay sold-comps service) if free paths prove
  unreliable in live testing.

## Needs coordinator review
- ADR-0201 (schema) must be reconciled with Agent 03 (economics/scoring fields) and Agent 04 (CRM/state model).
- ADR-0202 (access tiering + legal posture) must be reconciled with Agent 05 (governance/security).
- Notification backbone (ntfy + Apprise) overlaps Agent 06 (communications) — coordinate to avoid duplication.
- ADR numbering is agent-namespaced (02xx) pending coordinator reconciliation of a global sequence.

## Files produced
- docs/research/agent-02-opportunity.md — primary Round-One deliverable.
- docs/status/AGENT_STATUS.md — this file.
- docs/decisions/ADR-0201-normalized-opportunity-schema.md
- docs/decisions/ADR-0202-source-access-tiering-and-legal-posture.md
- docs/receipts/2026-10-06-source-research-provenance.md

## Next action
Await Agent 01 review of ADR-0201/0202 and Round-Two implementation go-ahead. On go: scaffold the repo
(schema + SQLite + SourceAdapter + dedup + scheduler + ntfy/Apprise) and build the first 3 collectors
(eBay Browse API, Craigslist, IMAP email-alert ingestor) per research §10–11.
