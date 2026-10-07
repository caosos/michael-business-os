# Receipt — Economics engine: methods, assumptions, and provenance

- Timestamp: 2026-10-07T04:03Z (work performed 2026-10-06 → 2026-10-07)
- Agent: 03 (Economics / Scoring)
- Branch: research/agent-03-economics

## Sources checked
- `/home/michaelos/business-os-prompts/03-economics.md` — Agent 03 mission brief (authoritative
  task spec: required factors, deliverables, "distance is economic", explainability requirement).
- Sibling prompt files referenced for alignment: `02-opportunity.md` (geography Conway / Central
  AR, ~100 mi typical; normalized opportunity schema + comps/discovery sources), `04-state.md`
  (canonical entities, receipt + provenance schema, outcome/lesson store), `05-governance.md`
  (YES/NO/MODIFY/HOLD approval interface, spend limits, license concerns).
- Repository state: all seven agent worktrees are empty stubs (only a shared 3-line README);
  no prior economics schemas or code exist. Verified via directory inspection.

## What was observed (FACT)
- No existing data model, stack, or manifest committed anywhere in the project.
- System law repeated across agents: "No action without a receipt. No receipt without provenance."
- Decision interface is YES/NO/MODIFY/HOLD (governance, Agent 05).
- Core flow: DISCOVER → NORMALIZE → RESEARCH → SCORE → RECOMMEND → APPROVE → ACT → RECEIPT →
  OUTCOME → LEARN → REPEAT. Scoring (this agent) sits between RESEARCH and RECOMMEND.

## Methods used (established, not invented)
Expected value / decision trees; EVPI; Kelly-style risk-of-ruin; inventory turnover & GMROI;
days-on-market; comparable-sales appraisal (sold prices, median, outlier trim, condition
adjustment); loaded labor rate, markup vs margin; cost-per-mile = fuel + wear (IRS standard
mileage rate as an all-in cross-check only); Brier score & MAPE for calibration.

## Key assumptions (REC/UNK — calibratable, NOT verified facts)
- vehicle_cost_per_mile v = $0.46/mi (fuel $3.20/gal ÷ 18 mpg + $0.28/mi wear). [REC]
- avg_speed 45 mph; storage $1-3/day; w_min $40/hr, target $65 flip / $75 service. [REC]
- max_loss_cap $800; per-deal cash cap $1,500; min_profit $150 flip / $100 service. [REC]
- Home base Conway, AR; fuel price, mpg, wear, and Michael's true $/hr are UNKNOWN pending input.
- 2025 IRS mileage ~$0.70/mi (cross-check) NOT re-verified against current IRS publication. [UNK]

## Confidence
Medium-high in the *method and structure* (standard, defensible). Low in the *numeric
thresholds* until calibrated by Michael's inputs and the outcome-learning loop. All defaults
are centralized and versioned so they are reconstructable and safely replaceable.

## Related output
- docs/research/agent-03-economics.md (design), docs/research/schemas/*.json,
  docs/research/config/scoring-config.json, docs/decisions/ADR-001-economics-scoring-engine.md.

## Uncertainty / how to reconstruct
Any score produced by this engine is reconstructable from: the opportunity record's inputs +
the cited `comps[]` + `estimates_meta.assumptions[]` basis tags + the `scoring_config_version`
pinning the constants in `scoring-config.json`. Changing constants requires a version bump,
preserving the ability to replay historical scores.
