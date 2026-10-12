# F-146: real Wooley auction events on /market (B-26 next boundary)

Provenance: queue row F-146 (owner P0 Wooley source); lane 02 `5c1aaa5` (`WooleySiteAdapter`, B-26 receipt `docs/receipts/2026-10-11-b26-wooley-site.md` there), pinned the local way: `git archive 5c1aaa5` into `.tools/disc-5c1aaa5`, `uv pip install --no-deps` into the lane 06 venv, no network. Archived Wooley pages copied unchanged from lane 02 `tests/fixtures/wooley/` into `tests/fixtures/wooley/`. DRY-RUN: no bid, contact, spend or publish; no hibid.com request anywhere.

## Change
- `tools/refresh_wooley_cache.py` (new): the ONLY fetcher. Without `--live` it refuses (exit 2, no request). With `--live` it runs `WooleySiteAdapter(live=True)` (wooleyauctioneers.com only, 10 s crawl delay, identifying UA, hibid.com refused by lane 02) and writes `var/cache/wooley-events.json` (or `MBOS_WOOLEY_CACHE`) atomically: `{as_of, requests, error, detail_errors, records}`. A failed refresh never replaces a good cache with an empty one. The UI never fetches on page load.
- `operator_ui/market_sources.py`: `wooley` source reading that cache (env `MBOS_WOOLEY_CACHE`), same card shape as GSA plus `event: True`. Card: auctioneer, title, closes_at, town, distance from the user's origin (gazetteer, then lane 02 `place_coords`), buyer premium when stated, category tags, Wooley auction page as the original link, HiBid catalog as a separate "View and bid on HiBid" link (a plain `<a>` for the human; never requested, embedded or scripted), kind `auction event`. Lot number, current bid and bid count: UNKNOWN. Freshness from `as_of` with the existing 6 h STALE rule. Missing/unreadable/time-less cache, or a failed refresh with no events = `offline` with an honest message. Real source: "connected (cached file)", never FIXTURE.
- Selector gains "Wooley Auctioneers". "All sources" merges GSA + Wooley (+ FIXTURE alerts only on the staging flag, unchanged). Craigslist / eBay / Facebook stay NOT CONNECTED.
- `market_source_view.py` / `market_view.py`: event list + gallery cards, offline/connected rows ("N auction events (not lots)"). `deal_ui.LISTING_HOSTS` gained `wooleyauctioneers.com` so the Wooley page renders as a link.
- **Price rule (decision):** an auction event has no price, so any min/max price filter EXCLUDES events (counted under "hidden by price", and the scope line says "A price range excludes events"). They are not moved to the unchecked section, because a price range is a hard owner limit and an event cannot be shown to satisfy it. Distance, category, keyword, state, closing-by and Search Now apply as for GSA.

## Tests
- `tests/test_market_f146.py`: 15 passed (card shape parity with GSA, UNKNOWN lot fields, links, connected label, selector and All merge, flag-only fixtures, distance/category/keyword/price rule, stale, offline x4 + failed refresh, refresh refuses without `--live`, atomic write and keep-good-cache, no hibid request/no external socket).
- Reference suite 499 passed / 1 failed (known `test_resale_f39` timeout); lane D+E 104 passed / 3 failed (2 known F-32 + `test_wanted_f25` order flake, 9/9 passed alone). `f143_live_check` not re-run by me (needs a staging server; Agent 01 runs the check tools).

## Not done / open
- No `--live` run by me (Agent 01 runs ONE on isolated staging and verifies in Claude in Chrome, desktop + mobile). No :8766 reload. The real cards (T.J. Bruck, Perryville) are verified there, not here.
- Lot-level data stays UNKNOWN: NEED written HiBid permission or a Wooley feed.
