# Receipt: F-17, the ADR-0012 capital fields on the card

- **Date:** 2026-10-07 · **Actor:** Agent 06 · **Task:** READY_QUEUE `F-17` (P1; claimed in `f63f5e2`)
- **Intent:** show how well a deal uses Michael's cash: a small fast flip can beat a big slow one. There is no universal profit floor (ADR-0012).
- **Effect:** this branch only. Read-only rendering of `mbos.card` output.

## Provenance
spine `mbos` @ `e20d6af` (installed without `build/`); `card.schema.json` re-vendored byte-identical (additive optional economics fields); ADR-0012 and `docs/messages/acks/ARIA-20261007-1840-deal-scoring-training.md`.

## What was built
- `card_view.render_capital`, placed between "Estimated numbers" and the value-add plan:
  - the headline row shows **class, cash multiple and capital velocity**, with **the downside (chance the repair fails outright) beside them**;
  - a second block holds parts-out floor, repair uncertainty, liquidity, skill fit and personal-use value;
  - **UNKNOWN stays visible** per field. `current_cash_context` has its own banner: "Cash situation: UNKNOWN. You have not told the system how much cash you have free right now..." until Michael sets it in the operator profile;
  - fields absent from an older card render as UNKNOWN ("the card does not carry this field"), never a guess;
  - `expected_gross_profit` already shows low to high in the numbers table, and the card's "why a small fast flip..." line is in WHY.
- **No sorting or filtering by profit anywhere in the UI.** A static test scans `operator_ui/` for any sort, order-by or threshold on profit, EV, revenue or $/h.

## Verification (FACT)
- `tests/test_capital_f17.py` (9 tests) built from Michael's three training examples with real `build_card`: the $30 TV is a Micro flip at 2.5x with a 20% downside and a $15 parts-out floor and a $30 to $70 gross range; the late-season mower is Capital-intensive with trapped cash; the non-running Recon is a Standard flip with high repair uncertainty.
- Cash context UNKNOWN is said, and when set in the profile it is shown as the stated fact. Missing numbers render UNKNOWN with no invented multiple. Hostile text in these fields is escaped. The live page shows the section.
- Mutation check: changing the cash-situation banner text fails its test.
- Reference 133 passed; lane D/E 27 passed.
