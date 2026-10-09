# Receipt: B-23 Arkansas auction discovery (fixture-first)

- Task: B-23 (lane 02). DRY-RUN; no network, no bid/contact path exists.
- Added: `src/mbos_discovery/auctions.py` (source inventory `HOUSES`, per-house terms record, `AuctionFixtureAdapter`, per-field `Field` with source/observed_at/basis/age, distance filter + exceptional statewide hook), `tests/fixtures/auctions/govdeals.json`, `tests/test_b23_auctions.py`.
- Provenance: field list from the B-23 queue row; access tiers from ADR-02-0202 / `policy.py` (govdeals, publicsurplus, hibid, allsurplus, municibid = PENDING_MICHAEL tier 3, so no live path; GSA tier 1). Distances: haversine from Conway, town centroids are INFERENCE.
- UNKNOWN (not invented): every house's registration, dealer/licence rule, deposit, buyer premium, card surcharge, payment, inspection/pickup windows, public online bidding. They stay `UNKNOWN`, `terms_verified=False`, until the B-12 owner step reads each terms page. Real response shapes are UNKNOWN; the fixture is hand-built.
- Vehicles: category `vehicle` maps to Item `project_vehicle` / subcategory `vehicle` (Item enum is frozen).
- Gap: sales tax is captured only when the lot states it; otherwise UNKNOWN.
