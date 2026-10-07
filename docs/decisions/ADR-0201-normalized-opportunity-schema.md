# Decision

**ADR:** 0201 (agent-02-namespaced; coordinator to reconcile into a global sequence)
**Title:** Normalized Opportunity Schema (single record for buy-items and service-leads)
**Author:** Agent 02 (Opportunity Discovery)
**Date:** 2026-10-06

Status:
PROPOSED

Context:
The engine ingests heterogeneous sources — P2P listings, auction lots, free-goods posts, service-lead feeds, and
government contracts — across APIs, internal endpoints, email alerts, and (last resort) browser scraping. Downstream
agents need one stable shape to score (Economics/03), store and track as CRM state (State/04), and act/notify on
(Communications/06). Without a shared schema these teams will diverge and integration will break.

Options considered:
1. **Per-source raw records + per-consumer adapters.** Flexible but pushes normalization cost onto every consumer;
   dedup and scoring become source-specific. Rejected — guarantees divergence.
2. **Two separate schemas (buy vs. service).** Cleaner per-domain but duplicates location/dedup/scoring/notify
   plumbing and complicates a unified ranking/notification pipeline. Rejected.
3. **One source-agnostic opportunity record** with an `opportunity_type` discriminator and a shared price/location/
   comps/valuation/dedup envelope. Recommended.

Recommendation:
Adopt option 3 — the normalized schema in `docs/research/agent-02-opportunity.md` §6. Salient points:
- `opportunity_type` ∈ {buy_item, auction_lot, free_item, service_lead, gov_contract}; `category` enum spans both
  equipment classes and service classes.
- `price.{amount,type,buyer_premium_pct}` unifies fixed-price and auction math on one path (buyer premium folded
  into true cost).
- `comps.basis` records the valuation source (ebay_sold | hibid_realized | gsa_sale | self_history | none).
- `valuation.{est_resale,est_cost_total,est_net_profit,profit_per_mile,confidence}` and `geo_tier` are the hooks
  Economics(03) and the long-distance logic (research §9) plug into — exact fields are **Agent 03's call to finalize**.
- `dedup_key` + `content_hash` support cross-source identity and change detection (research §7).
- `seller.contact_*` is captured but **never auto-actioned in Round One**.

Evidence:
- Field set derived from what each researched source actually exposes (eBay Browse, GovDeals, HiBid, EstateSales.NET
  alerts, Trash Nothing, SAM.gov) — see `docs/research/agent-02-opportunity.md` §1, §6 and the provenance receipt.
- Prior-art architecture: jgdigitaljedi/gs-scraper couples multi-source listings with an eBay comp lookup — the same
  listing+comps envelope this schema generalizes.

Risks:
- Over-fitting to today's sources; new sources may need schema additions (mitigate with an open `source`-specific
  `extra` map if needed).
- Valuation/scoring fields may be reshaped by Agent 03 — treat §6's `valuation`/`comps` block as provisional until
  reconciled.

Reversibility:
Medium. Easy to extend (additive fields) before any collector writes real data; harder once multiple collectors and
a populated store exist. Deciding now, pre-implementation, is low-cost.

Coordinator review required:
YES — reconcile with Agent 03 (scoring fields), Agent 04 (CRM/state persistence), Agent 06 (notification payload).
Do NOT mark ACCEPTED without that cross-agent review.
