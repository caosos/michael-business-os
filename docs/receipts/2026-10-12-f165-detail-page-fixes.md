# F-165 receipt: listing detail page fixes (DRY-RUN, no live reload)

Provenance: queue row F-165 (owner program, GSA parity 2b; Agent 01 inspected F-160 `f6a399c` on real caches). Cached data only; nothing fetched, sent or bid. Base `e5104de`.

## What changed (`operator_ui/market_detail.py`)
- Root cause of 'distance unknown' on the detail page and in Similar: the pool was loaded with `origin=None`. The page now resolves the owner's current search exactly as `/market` does (`market_prefs.recall(FILTER_KEYS)` -> `with_home` -> `parse_query`) and loads the pool with `ms._origin(q['base'])`, so the same gazetteer/Census path computes the distance as for the card. The status box gets a 'Location' row: `City, ST ZIP · N mi` (`distance unknown` only when it truly is). The decision-helper text 'distance unknown (location not found)' disappears for the same reason.
- Similar listings: same category, excludes the item, events and pure land (Land default-off), restricted to the owner's current scope (By Distance: known distance within the radius; By State: a known matching state, plus the radius when ticked), sorted by known distance then closing date, cap 8.
- No photo: a one-line 'No photo (open the original listing)' and the facts box takes the full width; no gallery block. Phone (<=700 px) compacts the header/nav to one scrolling line so the facts box starts higher.

## Tests (tests/test_market_f165.py, 3)
Similar within radius / sorted by distance then close / capped at 8 / no land / no self / no Texas; detail distance equals the card's distance for the same lot and origin; real Chrome no-photo layout at 1440 and 390 (no `.dt-photos` block, facts box top < 600 and < 400). Layout test importorskips playwright.

## Results
Reference backend 616 passed / 1 failed (known `test_resale_f39`); lane D + E 105 passed / 2 failed (known F-32 pair).

## UNKNOWN
The owner's scope is the last remembered search (or home); a detail link carries no query string of its own.
