# Receipt: C-20, morning digest re-ranked by the C-19 objective

Agent 03, 2026-10-08. `mbos_economics` 0.12.1. Dry-run, read-only over scored Items. Tags: FACT / INFERENCE / UNKNOWN.

## Change (FACT)
- `digest.build_digest` ordering inside a bucket (after the 72 h deadline window) is now `rank_score` = risk-adjusted profit x confidence x capital velocity (x seasonality x cash pressure), highest first, then time-to-cash, then item_id. The old key (EV $/h x confidence) is kept as `value_per_hour` for display only.
- Every row's `reason` names the components: class, cash at risk, days to cash, cash multiple, rank score and its factors (season and cash pressure shown only when known), plus EV $/h.
- New row fields: `rank_score`, `deal_class`, `capital_velocity`, `cash_multiple`, `ranking` (full component object).
- A card scored before C-19 has no `ranking`: it sorts after ranked rows in its bucket and its reason says "re-score". Nothing is invented.

## Golden (tests/test_digest.py::TestC20CapitalVelocityRanking, `examples/class_aware/`)
FACT: the 65" TV (MICRO_FLIP, ~$36 EV, rank 32.99) ranks above the late-season mower (CAPITAL_INTENSIVE_FLIP, ~$344 EV, rank 0.14, cash pressure visible in its reason). The older digest tests were re-baselined: in the `act` bucket the drywall job (rank 434.6) now precedes the project vehicle (25.1, cash tied up).

## Caveats
- INFERENCE: services and flips share one scale. A service's cash at risk is small, so its velocity sits at the 1.0/day cap and its rank is driven by risk-adjusted profit x confidence. Services therefore tend to rank above flips in a mixed list. If Michael wants lanes interleaved differently, that is a config/ranking decision, not an engine bug.
- Class thresholds remain provisional (MICHAEL_DECISIONS #9).
