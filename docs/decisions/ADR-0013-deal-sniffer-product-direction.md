# ADR-0013: Deal Sniffer product direction — mission engine now, marketplace seams later

- **Status:** ACCEPTED (scope + seams). Marketplace *features* are NOT accepted work; only the seams below are.
- **Source:** Aria message ARIA-20261007-1905-deal-sniffer-product-package; `docs/product/DEAL_SNIFFER_START_HERE.md` (owner direction, 2026-10-07).
- **Authority:** product/design direction only. No spend, contact, bid, payment, publishing or deployment is authorised.

## Decision
1. **Growth path.** Level 1 (private engine that makes Michael money) is the only level being built. Level 2 (transaction engine) and Level 3 (public marketplace) get *seams* so they can be added without refactoring the core. We do not build Craigslist + eBay + Thumbtack + Zillow + escrow.
2. **Weekly Money Mission** is a first-class planning object above single Items: capital ledger (`protected_principal`, `earned_working_capital`, `capital_deployed`, `realized_profit`, `available_to_deploy`), weekly target, hours, and a portfolio of opportunities that plausibly closes the gap. "Do not spend the bankroll" is a valid output. Michael's $500 protected principal is owner-set; the weekly target ($1,500 in the package) is an *example* and stays UNKNOWN until Michael states it (MICHAEL_DECISIONS #10).
3. **Opportunity classes** extend ADR-0012: MICRO_FLIP, QUICK_TURN, STANDARD_FLIP, CAPITAL_INTENSIVE_FLIP, **SERVICE_JOB, OTHER_OPPORTUNITY**. Classes are data in `config/operator_profile.v1.json`, never code constants. No universal profit floor (unchanged).
4. **One canonical inventory object, many truthful merchandising views.** A view may change headline, fact order, image order, emphasis and audience language. It MUST preserve condition truth, known defects, evidence basis (seller-stated / system-inferred / independently verified / UNKNOWN), price/bid terms and provenance. This is enforced by a lint, not by trust.
5. **Campaigns (wanted objects)** are a data model with four autonomy levels: WATCH_ONLY, RECOMMEND, ASSISTED_DEAL, BOUNDED_AUTOPILOT. Only WATCH_ONLY and RECOMMEND run in this release. ASSISTED_DEAL drafts only through the existing step-up approval path. BOUNDED_AUTOPILOT is denied by policy until a later explicit Michael decision.
6. **Conversational intake** is a seam: deterministic required-field specs per category (data) compute the *missing questions* and build a structured draft; an LLM front end may later sit on top but cannot mark anything verified.
7. **Valuation** is an interface returning ranges (list / likely / fast / as-is / after-repair, confidence, evidence) and a mandatory not-an-appraisal marker. Flip categories use existing comps; homes are interface-only (UNKNOWN) now.
8. **Reputation, credentials, payments, jurisdiction**: design seams only. Credential vocabulary is specific (identity_verified, payment_verified, insurance_verified, residential_license_verified, electrical_license_verified…); the bare word "verified" is invalid. Reputation events are receipted facts with evidence, graduated and appealable. Payments go through a provider boundary; Deal Sniffer is not the bank; `money.payment.*` stays granted to nobody. Jurisdiction rules are *packs* (rule, source, date verified, confidence, unresolved questions); we never hard-code "outside city limits means no licence".
9. **Contracts.** All new objects are *additive* schemas (mission, inventory, campaign, valuation, jurisdiction pack) outside the frozen v1.0.0 set; none alters Item/Receipt/Provenance/Approval/ActionRequest/Outcome. Anything that would need a frozen-contract change goes through ADR-0009.

## Consequences
- New READY work A-22..A-27, B-20/B-21, C-21/C-22, D-18, E-17..E-19, F-18..F-20, G-11 (READY_QUEUE, section "Deal Sniffer product package").
- Nothing here blocks the dry-run release candidate; C-19 (ADR-0012) stays P0.
- A later explicit Michael decision or accepted ADR overrides the package; amend with provenance.
