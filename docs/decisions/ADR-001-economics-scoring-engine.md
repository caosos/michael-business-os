# Decision

**ADR-001 — Economics & Scoring Engine architecture**

Status: PROPOSED

## Context
Michael needs an auditable engine that decides whether an opportunity — a physical asset
flip or a service job — is worth his time and money, and how urgently. The engine must
evaluate ~24 required factors (acquisition, materials, parts, fuel, mileage, travel time,
labor, fees, storage, disposal, revenue, repair/sale probability, cash tied up, net profit,
profit/hour, ROI, expected value, time-to-cash, risk, confidence, skill fit, scarcity,
salvage/downside) and produce a YES/MAYBE/PASS decision where **every score is explainable
and reconstructable**. "Distance is economic, not arbitrary."

## Options considered
1. **Single weighted-score ranking.** Normalize every factor to 0-100, weight, sum, threshold.
   - Simple and explainable, but a high weighted score can mask a ruinous downside or a deal
     outside Michael's skill/legal scope. No hard protection against loss.
2. **Pure expected-value maximization.** Rank purely by EV (or EV/hour).
   - Theoretically clean, but ignores evidence quality (low-confidence estimates treated as
     truth), ignores attention/urgency, and tolerates high-variance gambles.
3. **Gates-first hybrid (RECOMMENDED).** Hard gates first (ruin, skill/legal, floor wage,
   minimum evidence, long-distance ratio), then a transparent weighted composite ranks the
   survivors, with expected value computed over an explicit decision tree and a confidence
   haircut applied before ranking.

## Recommendation
Adopt Option 3. Specifically:
- Reduce every opportunity to a provenance-tagged ledger (cash out, cash in, Michael-hours).
- Compute expected value over a 3-branch decision tree (repair-success × sale/win), plus
  deterministic net profit, profit/hour, ROI, cash-tied-up, time-to-cash, and max-loss.
- Model **risk** (outcome dispersion) and **confidence** (evidence quality) separately.
- Treat distance as a four-channel economic cost (fuel, time, wasted-trip EV, revisit friction).
- Apply hard PASS gates, then a weighted composite (weights differ flip vs service), then
  YES/MAYBE/PASS with named reasons, and an immediate-alert flag for strong+perishable deals.
- Centralize all constants in a versioned `scoring-config.json`; store a `scorecard` per
  opportunity so any score can be replayed by hand under the config that produced it.
- Feed every completed outcome back (Brier/MAPE) to recalibrate priors without mutating history.

Full design: `docs/research/agent-03-economics.md`. Schemas/config under `docs/research/`.

## Evidence
- Methods are established, not invented: expected value / decision trees, EVPI, Kelly-style
  risk-of-ruin, inventory turnover & GMROI, days-on-market, comparable-sales appraisal,
  loaded labor rate / markup-vs-margin, cost-per-mile (IRS rate as cross-check), Brier/MAPE.
- Five fully reconstructable worked examples (trailer YES+alert, mower PASS→MAYBE with
  evidence, generator PASS on distance, drywall YES, smart-home YES) demonstrate the logic.
- 21 acceptance tests (reconstructability, monotonicity, gate enforcement, learning loop).

## Risks
- Default thresholds/weights are RECOMMENDATIONS; mis-calibration mis-ranks deals until the
  learning loop and Michael's time-value input tune them. Mitigation: versioned config,
  outcome calibration, conservative floor wage.
- Field names are provisional pending Agent 02 (opportunity) and Agent 04 (entities/receipts)
  final schemas. Mitigation: designed to nest inside theirs; alignment flagged for coordinator.
- Probability estimates (p_repair, p_sale) are only as good as evidence; the confidence gate
  and comps-minimum guard against over-trusting thin data.

## Reversibility
High. Pure decision logic over data, no persistence or external side effects committed.
Thresholds/weights are config, not code. Reversible by editing `scoring-config.json`
(with a version bump). Schema changes are additive-friendly.

## Coordinator review required: YES
(Not to be marked ACCEPTED by Agent 03; requires Agent 01 cross-agent reconciliation with
Agents 02, 04, and 05.)
