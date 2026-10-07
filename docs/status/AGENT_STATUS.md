# Agent Status

Agent: 03
Role: Economics / Scoring
Branch: research/agent-03-economics
Worktree: /home/michaelos/business-os-worktrees/agent-03-economics
State: COMPLETE
Current phase: Round One — research/design complete; awaiting coordinator review
Started: 2026-10-06
Last updated: 2026-10-07T04:03Z

## Current objective
Round-One deliverable complete: an auditable economic engine that decides whether an
opportunity (physical asset flip OR service job) is worth Michael's time and money, with
every score explainable and reconstructable. No production changes, no purchases, no CAOSCare.

## Completed
- Canonical opportunity schema (flip) + service-job schema, as prose and JSON Schema.
- Universal cost/revenue/hours ledger and all required formulas.
- Travel economics treating distance as a FOUR-channel economic cost (fuel, time,
  wasted-trip risk, revisit friction) — "distance is economic, not arbitrary."
- Profit/hour, ROI, cash-tied-up, expected-value (decision-tree) models.
- Separate risk model (outcome dispersion) and confidence model (evidence quality).
- Skill-fit, time-to-cash, and scarcity models.
- Combined weighted composite score (0-100) + gates-first YES/MAYBE/PASS decision logic.
- Immediate-alert thresholds, long-distance rules, minimum-evidence-before-YES checklist.
- Comparable-sales methodology (sold not asking, median, trim, condition-adjust, DOM).
- Learning loop from completed outcomes (Brier/MAPE calibration, versioned config).
- Five fully reconstructable worked examples: trailer, mower, generator, drywall, smart-home.
- 21 acceptance tests.
- Machine-readable scoring-config.json as single source of truth for all constants.
- ADR-001 proposing the engine architecture (PROPOSED; needs coordinator review).

## Findings
- FACT: Repo is green — all seven agent worktrees are empty stubs; no prior schemas/code
  to conform to. The economics schemas here are the first definition of these concepts.
- FACT: System law — "No action without a receipt. No receipt without provenance." A score
  is treated as a receipt of a judgment; every number carries provenance + config version.
- FACT: Michael's skills (from prompt): mechanical diagnosis, repair, welding, fabrication,
  maintenance, equipment repair, drywall, construction, troubleshooting, smart-home install.
- INFER: Michael's true scarce resource is HOURS, not dollars → profit/hour is the primary
  discipline metric; a high headline profit with poor $/hr or a ruinous downside is a PASS.
- INFER: The generator worked example shows a $1,030 "paper profit" correctly rejected by
  distance + unverifiable-fault + downside risk — proof the engine resists seductive gambles.
- REC: All thresholds/weights/caps are calibratable defaults centralized in scoring-config.json.

## Decisions made
- Gates-first, then weighted-composite ranking (hybrid). Hard gates encode "worth doing at
  all" (ruin, skill, evidence, floor wage); composite ranks survivors for limited attention.
- Net profit excludes Michael's own labor as a cash cost (standard contractor treatment);
  his time is disciplined via the profit/hour gate instead (avoids double counting).
- Risk (outcome dispersion) and confidence (evidence quality) are modeled separately.
- Expected value computed over an explicit decision tree (repair-success × sale/win).
- See docs/decisions/ADR-001-economics-scoring-engine.md.

## Unknowns
- UNK: Michael's real time-value floor/target ($/hr). Everything keys off this.
- UNK: Exact home base (assumed Conway, AR), vehicle mpg, realistic wear-per-mile, local fuel price.
- UNK: Per-deal and concurrent cash limits (coordinate with Agent 05 spend limits).
- UNK: License allow-list — which trades are legally gated/off-limits (Agent 05 owns).
- UNK: Current IRS standard mileage rate (used only as cross-check) at runtime.

## Blockers
None. Round-One design does not depend on other agents being finished; integration points noted.

## Needs Michael decision
- Confirm time-value $/hr floor and target (drives every profit/hour gate).
- Confirm per-deal cash risk cap and max concurrent cash tied up.
- Confirm home base + primary pickup vehicle (mpg) for travel-cost accuracy.
(These are recorded here before any ask, per protocol; defaults are in place for design.)

## Needs coordinator review
- ADR-001 (economics scoring engine) — PROPOSED; a whole-system-affecting recommendation.
- Schema alignment with Agent 02 (normalized opportunity; comps/DOM/active-listing feeds)
  and Agent 04 (canonical entity IDs, outcome/lesson store, receipt/provenance schema).
- Approval interface handoff to Agent 05 (YES/NO/MODIFY/HOLD consumes decision + reasons;
  distance/spend caps and license allow-list are governance-owned).

## Files produced
- docs/research/agent-03-economics.md  (canonical Round-One research/design)
- docs/research/schemas/opportunity.schema.json
- docs/research/schemas/service-job.schema.json
- docs/research/schemas/scorecard.schema.json
- docs/research/config/scoring-config.json
- docs/decisions/ADR-001-economics-scoring-engine.md
- docs/receipts/2026-10-06-methods-and-assumptions.md
- docs/status/AGENT_STATUS.md (this file)

## Next action
Hold for coordinator (Agent 01) review of ADR-001 and cross-agent schema alignment.
On request, refine thresholds once Michael supplies time-value and capital limits, and wire
field names to Agent 02 / Agent 04 final schemas.
