# F-156: Sources panel on /market

Provenance: queue row F-156 (B-34 sub-step), depends on F-155. Dry-run, display only; no network, no mailbox read, no spend.

1. `market_sources.REGISTRY` (code, the only source list): 13 `SourceInfo` rows with class, geography, retrieval path, granularity, bid capability, constraints, next step. `probe()` does a light cache read (GSA as-of, auction-event cache as-of, fixture-dir presence, owner finds count); `source_state()` returns exactly one of LIVE CONNECTED / IMPORTED / MANUAL / NOT CONNECTED / BLOCKED. Only a real cache read yields LIVE CONNECTED; fixtures, missing caches and other probe states never do.
2. `market_source_panel.py` renders a collapsed `<details id='sources-panel'>` table; wired after the Suggestions panel in `market_routes.page_body`.
3. GSA golden fixture regenerated (intended page change); `market_source_panel.py` added to the UI module allowlist.

Tests: tests/test_market_f156.py 8 passed (every state label; fixtures never LIVE; stale flag; page render). Reference 567 passed / 1 failed (known resale_f39); lane D+E 105 passed / 2 failed (known F-32).
Not verified: Agent 01 browser check is pending. IMPORTED has no source in use yet (label tested via `source_state` only). HiBid e-mail has no adapter, shown NOT CONNECTED.
