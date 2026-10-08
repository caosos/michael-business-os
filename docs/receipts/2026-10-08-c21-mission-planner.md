# Receipt: C-21, Weekly Money Mission planner

Agent 03, 2026-10-08. `mbos_economics` 0.13.0. Dry-run, pure function, no clock, no random, no LLM arithmetic. Tags: FACT / INFERENCE / UNKNOWN.

## What it does (FACT)
`mbos_economics.mission.plan_week(mission, ledger, scorecards)` returns a `mission_plan` (A-23, `mission.schema.json`). `scorecards` are scored Items. The output passes `mbos.mission.plan_errors` in every golden when Agent 01's validator is present.
- Candidates: non-PASS scorecards with positive expected net, top 10 by `rank_score` (`config/mission-planner.json`, data).
- Search: every subset of the candidates that fits `available_to_deploy` and `hours_available` (null hours = unconstrained, listed in `unknowns`).
- Objective: exact probability that the week's total reaches the target, by convolving each leg's scorecard branches (independent legs). A plan within `probability_resolution` (0.05) of the best counts as equal, then the plan that risks less cash wins. If the target is unreachable or null, the objective is expected net, then less cash.
- Class velocity: a leg whose cash returns after the period counts as locked cash, not this week's income.
- Recommendation: `DEPLOY` (legs commit cash), `DO_NOT_SPEND` (legs commit zero cash), `HOLD` (nothing viable), `UNKNOWN` (null target; `remaining_gap` null).
- No absolute-profit floor anywhere (ADR-0012). Every leg carries its scorecard id and a `why` naming class, cash at risk ("no capital at risk" for zero-cash services), days to cash, hours, P(plan goes right) and rank components.

## Goldens (tests/test_mission.py, 12 tests)
- $500 week: smart-home service alone (DEPLOY; "services only" stated; TV and flips add no meaningful probability); mower and Recon (PASS) never become legs.
- $1,500 week: service + 65" TV; plan states it does not close the gap.
- Cash-tight week ($100): service + TV. $40: TV only. 1 h: TV only.
- Zero-cash service: DO_NOT_SPEND. Null target: UNKNOWN, null gap. All PASS: HOLD.

## Also in this change (agent 01 request)
`deal_class` for services is now `SERVICE_JOB` (matching the card); `cash_multiple` and `ev_cash_multiple` are null for services; the digest says "no capital at risk" for zero-cash rows. Engine 0.13.0; scoring config unchanged (2026.10.2).

## Caveats
- INFERENCE: a service with materials cash is DEPLOY, not DO_NOT_SPEND, because the A-23 validator forbids cash on a DO_NOT_SPEND plan. The explanation says "Services only".
- Legs are assumed independent. Planner parameters are RECOMMENDATION, not Michael-confirmed.
