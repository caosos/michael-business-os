# Decision

**ADR:** 0202 (agent-02-namespaced; coordinator to reconcile into a global sequence)
**Title:** Source-Access Tiering and Do-Not-Automate / Legal Posture
**Author:** Agent 02 (Opportunity Discovery)
**Date:** 2026-10-06

Status:
PROPOSED

Context:
Few in-scope sources offer an official API. The rest range from sanctioned email alerts to undocumented internal
endpoints to anti-bot-defended login-walled sites. How aggressively the engine ingests each source is a
whole-system legal/risk posture — it affects Governance(05), every collector's design, and Michael's liability.
A single reckless scraper (PII harvest, block-evasion, account-bound ToS breach) could get accounts banned or create
legal exposure. This ADR fixes the ingestion priority order and the never-automate list.

Options considered:
1. **Scrape everything that renders.** Max coverage, max risk (bans, ToS breach, CFAA exposure on block-evasion,
   PII liability). Rejected.
2. **API-only.** Safest, but abandons the highest-volume local sources (Craigslist, FB, GovDeals, estate sales) that
   are the actual hunt. Rejected — leaves most money on the table.
3. **Tiered access by risk, with a hard do-not-automate list and a mandatory kill-switch.** Recommended.

Recommendation:
Adopt the tiering in `docs/research/agent-02-opportunity.md` §4–§5, preference order safest-first:
1. **Official API** — eBay Browse, GSA Auctions, SAM.gov, Trash Nothing, Google LSA (read), Thumbtack Pro (if approved).
2. **Sanctioned email-alert / IMAP** — EstateSales.NET, GovDeals/PublicSurplus/MaxSold/CTbids saved-search alerts,
   AR Bid/ARBuy. (We read only our own inbox — no server touched beyond a legitimate account feature.)
3. **Internal JSON/GraphQL endpoints** — GovDeals, HiBid, AllSurplus, PublicSurplus, Municibid, GovPlanet,
   MaxSold, Proxibid, PropertyRoom. Public data but ToS-adverse → throttle, cache, rotate identity, **kill-switch on blocks**.
4. **Headless browser + stealth (last resort)** — FB Marketplace, OfferUp. Logged-out where possible (safer per
   Meta v. Bright Data 2024); if logged-in, disposable account + static residential ISP proxy, low frequency.
5. **Manual / human network (never automate)** — see do-not-automate list.

**Do NOT automate:** FB/Buy-Nothing groups; Nextdoor for-sale & recommendations; Thumbtack/Angi/HomeAdvisor consumer
sites (PII + ToS — use their official lead API instead); EstateSales.NET site scraping (use their email alerts);
EstateSales.ORG entirely ($0.25/page, 1k/day cap); any logged-in account where the data is others' PII; and **never
evade an IP block or CAPTCHA after being blocked** (the clearest CFAA trigger — Craigslist v. 3Taps).

**Mandatory controls:** a per-source kill-switch that disables a source on repeated 403/429 and alerts the operator;
conservative, jittered request rates; no republishing/resale of scraped data in Round One+.

Evidence:
- Case law (INFERENCE applied to our facts): hiQ v. LinkedIn (public scraping ≠ CFAA "unauthorized access", but ToS
  breach if logged in); Meta v. Bright Data 2024 (ToS bind only while logged in); Craigslist v. 3Taps (block-evasion
  = CFAA). Citations in `docs/receipts/2026-10-06-source-research-provenance.md`.
- Per-source API/ToS status: `docs/research/agent-02-opportunity.md` §1, §4, §5.

Risks:
- Internal-endpoint tier is still ToS-adverse even for public data; a site could issue a C&D or ban.
- Over-conservatism could under-cover the market; the tiering is meant to be tuned after live testing, not a freeze.

Reversibility:
High for tuning rates/cadence; the do-not-automate list and kill-switch should be treated as durable guardrails, not
knobs.

Coordinator review required:
YES — reconcile with Agent 05 (governance/security) as the authority on legal posture and guardrails. The internal-
endpoint aggressiveness also needs Michael's risk-tolerance call (flagged in AGENT_STATUS → Needs Michael decision).
Do NOT mark ACCEPTED without that review.
