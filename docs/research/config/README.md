# Scoring config: moved

There is now one source of truth for the scoring config (C13): **`economics/config/scoring-config.json`**. The current version is 2026.10.1.

The round-one file (2026.10.0) is preserved byte-for-byte at `economics/config/history/scoring-config-2026.10.0.json`. It is kept for the record only, because it stored formulas as prose and the engine cannot execute it. See ADR-03-002 §3 for every formula change.
