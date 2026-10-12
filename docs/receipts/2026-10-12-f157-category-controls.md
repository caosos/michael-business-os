# F-157: category controls control the feed

Provenance: queue row F-157 (P0 owner UX correction), depends on F-156. Dry-run; local filter + existing prefs file only; no network, no spend.

1. `market_search`: nine owner categories (Tools, Equipment, Trailers, Vehicles, Lawn & Garden, Machinery, Pallets/Wholesale, Land/Real Estate, Other/Unknown) plus `all`. `parse_query` gives `cats`, `cat_all`, `cat_default`; with nothing ticked the default is every category except Land/Real Estate. `partition` keeps a lot when any category it matches is selected (`card_cats`/`cat_ok`): pure land/home lots are hidden while Land is off, mixed lots (land + tools/equipment) stay, lots matching nothing sit under Other/Unknown. All = no category filter. The old `any` keyword focus only applies when the owner edits it away from the default, so it no longer overrides the ticks.
2. `market_view`: 44 px tap-target category chips with an All box, in the existing filter sidebar; `static/market_radius.js` syncs All with the boxes (without script the server treats All as everything). Save-search stores `cat:` only when not the default.
3. Persistence: the existing `market_prefs` `last` choice (`cat`), file `MBOS_MARKET_PREFS_FILE`; no new store. Tests set that env var to a temp file; `test_isolation_owner_prefs_untouched` pins that another file is never written.
4. GSA golden regenerated (intended page change).

Tests: tests/test_market_f157.py 8 passed. Full health results in AGENT_STATUS.
Not verified: Agent 01 Claude Chrome desktop/mobile check on the loaded revision is pending (no live reload by this worker). Word-list classification is a heuristic on title + category guess, not seller-verified; the long description is ignored.
