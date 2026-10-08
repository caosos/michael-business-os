# ADR-0012: No universal absolute-profit floor; capital-velocity scoring

- **Status:** ACCEPTED. Owner rule (Michael, via Aria message ARIA-20261007-1840, a training signal from live evaluation). Implementation: C-19.
- **Supersedes:** the `capital_and_risk.min_profit_flip` / `min_profit_service` hard gates in lane C's scoring config (`min_profit_ok`, `ev_min_profit_ok`).

## The rule
Never reject an opportunity solely because its expected profit is below an absolute amount. A $30 item that reliably becomes $75–$100 in an hour can outrank a $250 item that becomes $600 in four months.

## What decides instead
Separate, individually visible fields, never one unexplained number:
cash at risk · time to cash · capital velocity · cash multiple · profit per Michael-hour · gross-profit range · downside if the diagnosis is wrong (probability and parts-out floor) · seasonality and likely hold · liquidity · transport and handling burden · skill fit · personal-use value · the current cash situation.

Ranking objective ≈ **expected risk-adjusted profit × confidence × capital velocity**. Absolute profit, ROI, time-to-sale and downside exposure stay visible beside it.

## Deal classes
MICRO_FLIP / QUICK_TURN / STANDARD_FLIP / CAPITAL_INTENSIVE_FLIP. Thresholds are **data** (`config/operator_profile.v1.json` → `deal_classes`), provisional until Michael confirms (MICHAEL_DECISIONS #9). A capital-intensive flip must clear a meaningful absolute profit; a micro flip is judged on velocity, downside and profit per hour.

## "Good asset" is not "good buy for Michael right now"
Seasonality, hold time and the current cash situation can make a technically good flip the wrong purchase today (e.g. a mower late in the season with funds tight). Cash context is Michael-stated data; when absent the card says UNKNOWN rather than assuming.

## Consequences
- Lane C replaces the universal floor with class-aware gates (C-19) and updates its goldens. Until then the scorer still PASSes such deals while the card already explains them.
- Frozen governance contracts are untouched; the card contract gains optional fields only.
- A floor is allowed only as a class-specific, data-defined threshold, never as a global constant in code.
