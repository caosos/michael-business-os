# Receipt: D-33 (auction watchlist, price/closing alerts, approved bid ceiling storage)

- Timestamp: 2026-10-09
- Agent: 04 (bounded worker, Sonnet)
- Inputs (read-only): queue rows D-33, B-23 (DONE), C-32 (DONE); migrations 0024-0027 for the owner-channel pattern.
- Mode: DRY-RUN. Throwaway pgserver PG16 clusters only. Nothing was sent, bid, spent or published.

## Built
- `state/migrations/0028_auction_watch.sql`: append-only `auction_watches` and `auction_watch_events`; view `v_auction_watch_current` (latest bid and count, effective close, ceiling, alerts fired); functions `watch_auction`, `set_bid_ceiling`, `stop_watch` (owner_channel + human actor + human provenance) and `record_watch_observation` (owner_channel or agent_write; needs provenance for source/freshness).
- Alert-once: `UNIQUE (watch_id, dedupe_key)` with ON CONFLICT DO NOTHING; the function returns only the alerts fired by that call. Kinds: `price`, `closing` (last N hours, before close only), `ceiling_reached`. Alerts are stored records; nothing is delivered.
- Soft-close: an observation may carry a new `closes_at`; it moves the closing window.
- Every write has an ITEM_STATE_CHANGED receipt (entity_type auction_watch), idempotent on key.
- No bid path: the ceiling is a stored number that authorizes nothing; no action request, budget or capital row is created.

## Acceptance
- FACT: `state/tests/test_auction_watch.py` (6 tests): alerts fire once per event incl. idempotent replay and post-close; ceiling-reached once, latest ceiling wins; soft close; stop; agent cannot watch/set ceiling/stop or insert directly; negative test: no bid-named function, zero action requests, budget receipts or capital rows, chain verifies.
- FACT: health `cd state && .venv/bin/python -m pytest`: 330 passed, 1 skipped, 0 failed.
- UNKNOWN: who calls `record_watch_observation` on a schedule (lane 02 adapter / dispatcher); not in this task. Live bid integration and authorization remain unverified, so stay dry-run.
