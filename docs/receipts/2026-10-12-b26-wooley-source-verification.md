# Receipt — B-26 Wooley Auctioneers auction-event source: review, fixes, live smoke (Agent 01)

Recorded 2026-10-12T00:02:33Z. Provenance: FACT = observed this session by command.

## Artifact
- Lane 02 `5c1aaa5` (status) / `2f81a7e` (review fixes) on top of `90672f2` (adapter `src/mbos_discovery/adapters/wooley_site.py`, 284 lines) — two bounded lane 02 workers, launched after pushed claims; no retry/escalation. Cost UNKNOWN.

## Review (read by me)
- hibid.com is refused before a request is built (`HibidRefused`); the transport is a `ReadOnlyTransport` allow-listed to `wooleyauctioneers.com`, redirects off; crawl delay floor 10 s (robots.txt); live OFF by default; stable source id = auction page slug; lot_number/current_bid/bid_count/lot_image are UNKNOWN by construction.
- Found and fixed (worker 2, `2f81a7e`, exactly as specified): (1) the User-Agent contained the user's personal e-mail -> now `DealSnifferBot/1.0 (read-only; auction events only)` with a no-'@' test; (2) unknown buyer premium defaulted to 0 -> now omitted unless stated; (3) `condition` asserted `used` -> `unknown`; (4) `price.type=starting_bid` without an amount -> omitted.

## Tests (clean checkout of 5c1aaa5, lane 02 interpreter)
- `tests/test_b26_wooley_site.py`: **18 passed, 0 failed**. Full lane 02 suite: **355 passed, 0 failed**.

## Live smoke (ONE bounded run, `WooleySiteAdapter(live=True).fetch()` from the clean checkout)
- Started 2026-10-12T00:01:29Z, finished 00:01:50Z; **3 requests** (current-auctions page + 2 auction pages, >= 10 s apart), no error, **0 hibid.com requests**, 2 events, no duplicate ids. Evidence: `docs/receipts/b26-live-smoke/live-smoke.json`.
- T.J. Bruck Estate Heavy Equipment & Machinery Auction: closes 2026-10-13T18:00-05:00 (FACT), Perryville AR 72126, 21.2 mi from Conway, buyer premium 10% (FACT), HiBid catalog link kept as a human link only; lot number / current bid UNKNOWN.
- S&H Systems Phase II (Jonesboro AR): closes 2026-10-21T14:00 Central (INFERENCE: page says "CT"), 110.8 mi, buyer premium UNKNOWN (not stated on its page).
- Earlier archive capture: `docs/receipts/b26-wooley-archive/` (2026-10-11T23:52Z, scrubbed, original sha256 kept).

## Verdict
- **B-26 source DONE at auction-EVENT level** (real, read-only, live-verified). Lot-level acceptance (Lot 34, bids) remains NEED: Wooley's own feed or HiBid written permission. Not yet in /market: next boundary F-146.
