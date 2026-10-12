# F-158 receipt: commercial real-estate auctions no longer leak through the Land/Real Estate filter

- FACT: on `498fcb3` the three Wilson titles (category guess `commercial_equipment`) matched Equipment through the system guess and were kept as "mixed".
- Change (lane 06 only, `operator_ui/market_search.py`): when the TITLE matches Land/Real Estate, other categories come from the title only (`card_cats`, `in_cat(title_only=True)`); `commercial building` and `building` + `auction` titles count as land/real estate.
- Unchanged from F-157: All, multi-select, defaults, per-owner prefs, test isolation. Mixed titles (campers/vehicles/trailers/tractor) are still kept.
- Tests: `tests/test_market_f157.py` 13 passed (5 new). Full run: reference 580 passed / 1 failed (known resale_f39); lane D+E 105 passed / 2 failed (known F-32). No live reload; dry-run.
