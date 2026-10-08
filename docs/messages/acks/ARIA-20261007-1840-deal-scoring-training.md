# ACK: ARIA-20261007-1840-deal-scoring-training

- **Message:** `origin/liaison/aria-to-agent-01:docs/messages/inbox/ARIA-20261007-1840-deal-scoring-training.md`
- **Classification:** TRAINING_SIGNAL + OWNER_INPUT
- **Disposition:** **TASKED** (card side INCORPORATED; scoring side tasked to lane C, because it needs engine changes I do not own)
- **Acked by:** Agent 01, 2026-10-08
- **Authority check:** the message authorises design/scoring work only. No spend, offer, contact, publishing or live action was taken or enabled.

## Reconciliation against current repo truth

**FACT, the main finding: the rule is violated today.** Lane C's scoring config has `capital_and_risk.min_profit_flip = 150` and `min_profit_service = 100`, applied as the hard gate `min_profit_ok` (`mbos_economics/engine.py`), plus `ev_min_profit_ok`. Michael's $30 TV that becomes $75–100 in an hour has an expected net profit below $150, so the engine would PASS it. This is exactly the "universal absolute-profit floor" the message forbids.

| # | Concept requested | Status before | Now |
|---|---|---|---|
| 1 | `cash_at_risk` | on card (`total_cash_at_risk`) | unchanged |
| 2 | `expected_days_to_cash` / range | on card (single value) | unchanged; range is task C-19 |
| 3 | `capital_velocity` | missing | **card: done** (`economics.capital_velocity`); **score input: C-19** |
| 4 | `gross_profit_range` | single value | **card: done** (low/high from conservative/optimistic resale) |
| 5 | profit per hour | on card | unchanged |
| 6 | `cash_multiple` / ROI | engine has `ev_roi`; not on card | **card: done** (`economics.cash_multiple`) |
| 7 | `seasonality_score` | `demand_now`/`hold_likely`/`peak_months` | task C-19: numeric seasonality input into the score |
| 8 | `liquidity_score` | `sale_prob`, `expected_dom_days` in item economics; not on card | **card: done** (`economics.liquidity`) |
| 9 | `repair_uncertainty` | `repair_scope_known`, `repair_success_prob`; not on card | **card: done** (`economics.repair_uncertainty`) |
| 10 | `catastrophic_downside_probability` | implicit (1 − `repair_success_prob`) | **card: done** |
| 11 | `parts_out_floor` | `downside.salvage_if_repair_fails`; not on card | **card: done** |
| 12 | `transport_handling_cost` | on card (`transport_cost`, logistics) | unchanged |
| 13 | `skill_fit` | in scorecard; not on card | **card: done** |
| 14 | `personal_use_value` | missing | **card: slot** (UNKNOWN unless a lane supplies it); input is C-19 |
| 15 | `current_cash_context` | missing | **data slot** in `config/operator_profile.v1.json` (`current_cash_context`, null = UNKNOWN; **Michael sets it**); card says UNKNOWN until then; MICHAEL_DECISIONS #9 |
| 16 | MICRO_FLIP / QUICK_TURN / STANDARD_FLIP / CAPITAL_INTENSIVE_FLIP | missing | **card: done** from thresholds in `operator_profile.v1.json` `deal_classes` (data; **PROVISIONAL**, proposed by Agent 01 from the examples, Michael confirms: MICHAEL_DECISIONS #9); **gates: C-19** |

## What I did (commit: the one adding this file)
- **Project truth:** ADR-0012 "No universal absolute-profit floor; capital-velocity scoring" (the standing rule, verbatim intent).
- **Card (my lane):** the ten capital-velocity fields as separate, honestly-labelled fields; a plain-English "why a small fast flip can outrank a big slow one" line; text-view CAPITAL section. Each derived from numbers already on the Item, with a basis; UNKNOWN when absent. No single unexplained score.
- **Tests from Michael's three examples** (`tests/unit/test_card.py`): the $30 TV is a MICRO_FLIP at 2.5x with a 20% catastrophic-downside probability and a parts-out floor; the late-season mower is CAPITAL_INTENSIVE with trapped cash and a negligible velocity; the non-running Recon is a different class with high repair uncertainty; a $30 profit is never rejected by the card.
- **Contract:** `card.schema.json` gained OPTIONAL economics fields (additive). Frozen governance contracts untouched.

## Tasks created
- **C-19 (03, P0):** replace the universal `min_profit_*` gate with class-aware gates; add capital velocity, cash multiple, catastrophic-downside, liquidity, parts-out floor, personal-use value and current cash context as engine inputs/outputs; ranking objective ≈ risk-adjusted profit × confidence × capital velocity with every component separately visible; goldens for the TV, the mower and the Recon.
- **C-20 (03):** digest ranking (C-08) uses the same objective.
- **F-17 (06):** show class, multiple, velocity and the "why it outranks" line in the Operator UI; pick up the card's new fields.
- **G-10 (07):** acceptance for the new fields and for "no universal floor".
- **MICHAEL_DECISIONS #9:** confirm the class thresholds and state the cash context (non-blocking; provisional defaults in use, flagged RECOMMENDATION on the card).

## Remaining blocker
None for the dry-run scope. Until C-19 lands, the engine still applies the $150 gate, so such deals are still PASSed by the scorer even though the card now explains them correctly.
