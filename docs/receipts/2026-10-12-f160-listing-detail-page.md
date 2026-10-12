# F-160 receipt: listing detail page /market/item/<source>/<id> (DRY-RUN, no live reload)

Provenance: queue row F-160 (owner 2026-10-12 ~14:30 CDT, GSA parity 2/2; Agent 01 inspected gsaauctions.gov). Built from the cached record only (the GSA cache file and the other source caches already on this computer); no new fetch, no new store. Base `cb682ff`.

## What changed
- `operator_ui/market_detail.py` (new): `href(card)`, the page, the event page. Status box (GSA `auctionStatus`, else derived from the close), current bid, bidders, bid increment, ESTIMATED next minimum (cached bid + increment, live minimum unverified), reserve, countdown (server-rendered days/hrs/min/sec; `static/market_detail.js` ticks it, display only), photo area (GSA images are behind a GSA login, so the existing honest tile; real image hosts get thumbnail + full-screen link), 'Bid on the original site' (link only; never a bid here), Description from `lotInfo` through a small allow-list sanitizer (no attributes, links, scripts), Condition and Inspection/removal sections from `lotInfo` headings, Pay by / Remove by parsed from `instruction`, property address + OpenStreetMap search link (no embedded map), custodian and contacts exactly as published (REDACTED stays REDACTED), Similar listings (same category, nearest first, excludes the item, Land/Real Estate default-off), decision helpers (Suggestions reason from `market_suggest`, resale price form, My bids add).
- Auction EVENTS: dates, address, auctioneer, auctioneer/platform links, 'Lots not available: see the auctioneer'.
- Every card now links to its detail page: the card's single `View` (now internal), `View details` on list/legacy gallery/event cards and owner finds. The original listing link moved onto the detail page (and stays on list cards).
- `server.py`: GET `/market/item/<slug>/<id>` (404 page when no cached listing matches), `/static/market_detail.js`; CSP allows same-origin script on `/market/item/*` only.
- `tests/test_market_f163.py` skips cleanly when playwright is missing (module-level `pytest.importorskip`).

## Tests (tests/test_market_f160.py, 7)
Every card (gallery + list + events) links to a 200 detail page; GSA fields from the fixture lot; UNKNOWN labelled and 404 for an unknown id; event page; similar listings (excludes self, nearest first, Land off, no category); sanitizer; real Chrome 390 px (no horizontal overflow, countdown ticks). Offline: `socket.create_connection` raises for any non-loopback host in every test.
Adjusted: f145 golden regenerated (View is now internal), f159 card-shape assert, `test_operator_ui` module allow-list gets `market_detail.py`.

## Results
Reference backend 612 passed / 1 failed (the known `test_resale_f39`). Lane D + E 105 passed / 2 failed (the known F-32 pair; `test_wanted_f25` failed once under concurrent load and passes alone, 9/9). No live reload, no deploy, nothing sent.

## UNKNOWN / not done
Photo gallery shows one image (the cache has one `imageURL`); GSA images cannot load without a GSA login. Non-GSA sources have no raw record, so condition/inspection/contacts show UNKNOWN there. Bidder history and bid rules are not in the cache.
