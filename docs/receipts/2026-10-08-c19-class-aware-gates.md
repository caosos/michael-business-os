# Receipt: C-19, class-aware gates and capital-velocity ranking (ADR-0012)

Agent 03, 2026-10-08. Package `mbos_economics` 0.12.0, scoring config 2026.10.2 (2026.10.1 archived in `config/history/`). Dry-run only. Tags: FACT / INFERENCE / RECOMMENDATION / UNKNOWN.

## What changed (FACT)
- **Removed** `capital_and_risk.min_profit_flip` (150), `min_profit_service` (100), gate `min_profit_ok`, YES condition `ev_min_profit_ok`, and `alert_thresholds.ev_multiple_of_min_profit`. Neither engine code nor default config holds a constant profit floor. `tests/test_class_aware.py` asserts it.
- **Added (data in config, hashed for replay):** `deal_classes` (boundaries mirrored from `operator_profile.v1.json`; a test fails on drift), `class_gates` (per-class `min_net_profit`, `min_ev_profit`, `min_cash_multiple`), `ranking`.
  - Replacements: gate `class_profit_ok` (deterministic net vs the class's `min_net_profit`); YES condition `class_ev_ok` (EV vs the class's EV and cash multiple).
  - CAPITAL_INTENSIVE_FLIP keeps a meaningful absolute requirement ($150 gate, $250 EV). MICRO_FLIP and QUICK_TURN have none. SERVICE has none (the $/h floor and target govern).
  - Alert re-based: `ev_multiple_ok` = EV cash multiple >= 1.5 (flips) or EV $/h >= 1.25 x service target (services).
- **New scorecard outputs** (`derived` and `ranking`): `deal_class` (basis RECOMMENDATION), `class_requirements`, `cash_at_risk`, `days_to_cash`, `cash_multiple`, `ev_cash_multiple`, `capital_velocity`, `catastrophic_downside_probability`, `parts_out_floor`, `liquidity`, `personal_use_value`, `current_cash_context` ({value, known}), `seasonality_factor`.
  - `ranking{}` shows every component: `risk_adjusted_profit`, `confidence`, `capital_velocity`, `seasonality_factor_applied`, `cash_pressure_factor`, `rank_score`, `formula`.
- **New optional input** `economics.context {personal_use_value, current_cash, seasonality_factor}`. Absent or null is UNKNOWN: never assumed, factor 1, reported null.

## Goldens (Michael's three examples; `examples/class_aware/`, `tests/class_cases.py`)
| Case | Class | Net (plan) | Cash multiple | Velocity /day | Decision | Rank |
|---|---|---|---|---|---|---|
| 65" TV, ~$30 | MICRO_FLIP | $56 (< old $150 floor) | 2.1x | 1.0 (capped) | MAYBE (not PASS; no gate fails) | 32.99 |
| Older mower, late season, cash tight | CAPITAL_INTENSIVE_FLIP | $532 | 1.4x | 0.0033 | PASS (composite) | 0.14 |
| Recon 250 non-running | STANDARD_FLIP | $483 | 1.39x | 0.018 | PASS (composite, $/h) | 1.79 |

FACT: the TV outranks the mower with a bigger spread on the mower side. Mower velocity is tiny and its cash share of Michael's stated cash is 0.72 (an illustrative input, not Michael's actual number).

## Re-baseline of the 14 existing goldens
FACT: no decision changed (all 14 verdicts and composites identical). Only ids, `engine_version`, `scoring_config_version`, `inputs_hash`/`config_hash` and the added fields changed. Value-add parts ceiling for the zero-turn case moved $509 -> $505 because the YES test now uses the STANDARD_FLIP EV requirement ($100) and cash multiple instead of the old flat $150 on EV; verified by the bisect test. Lane-D export fixture regenerated through Agent 04's real StateStore (19 items, receipt chain ok). The sensitivity tables are unchanged; its header was updated.

## Caveats
- UNKNOWN: Michael has not confirmed class thresholds (MICHAEL_DECISIONS #9); every class threshold and `class_gates` value is a provisional RECOMMENDATION.
- INFERENCE: services rank with tiny cash at risk, so their `capital_velocity` hits the cap; compare `rank_score` within a lane (C-20 will group by lane or use $/h for services).
- The estimator does not yet fill `economics.context.seasonality_factor` from `seasonality.json` (follow-up); until then it is UNKNOWN unless supplied.
- 337 tests pass with the Agent 01 contracts and Agent 04 state envs; 316 without.
