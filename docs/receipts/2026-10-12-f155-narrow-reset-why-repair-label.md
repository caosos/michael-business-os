# F-155 third step (narrow): reset keeps resale targets, outside rows say why, repair label

Provenance: Agent 01 review of c2813dd/423903c (2026-10-12T07:29:06Z). Dry-run, display only; no network, no spend.

1. `market_prefs`: `resale_targets` added to EMPTY, dict-type guard in `load()`, kept by action `reset`.
2. `market_suggest.suggest`: every row in "Scored but outside your rules" now carries the engine verdict, its reason text, net and days to cash, plus the cap and the repair rule next to the engine's repair allowance.
3. `render_ranked`: repair allowance tagged "estimate (repair scope unknown)" when `repair_scope_known` is false; says plainly when it exceeds the "little or no repair" rule.

Tests: tests/test_market_f155.py 12 passed. Reference 559 passed / 1 failed (known flaky resale_f39); lane D+E 105 passed / 2 failed (known F-32).
Not verified: the real-cache 'Trailer, Utility' (3-1-QSC-I-27-006-005) case was not re-run against the live cache; covered by a synthetic lot.
