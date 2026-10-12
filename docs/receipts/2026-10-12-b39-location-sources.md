# Receipt: B-39 offline ZIP table and sources_for(user) (DRY-RUN)

- **Task:** B-39 (P1 owner program, ADR-0015 P-74-4, dependency D-37 DONE `c729a2c`).
- **Change:** `src/mbos_discovery/location.py` (`zip_centroid`, `sources_for(user, registry=None)`, `default_radius`, `OWNER` = Conway AR 72032, 150 mi); data in `src/mbos_discovery/data/` (`zcta_centroids.csv` 33,791 rows; `sources.v1.json` copy of lane 04 `c729a2c`; `PINNED.md`).
- **Rules (ADR-0015 section 4):** national always active; `states` scope active on home_state match; metro/point active when distance <= coverage radius + user radius; no known location gives national only. Status (blocked / not_connected) is reported, never hidden; selection connects nothing.
- **Provenance:** Census 2023 Gazetteer ZCTA internal points, public domain, zip sha256 75191ab2...077ce (also used by Agent 01's F-150 file). Centroid distances are approximate. No network call; no location leaves the box.
- **Tests:** 432 passed, 0 failed (8 new, tests/test_location.py): Ohio user sees no Arkansas Craigslist or AR houses; owner gets every registry source at 150 mi; distance match without state; MO border user reaches NW Arkansas only; unknown location is national only.
- **Not done / note:** the registry copy predates D-38 (three AR auction-house rows); re-vendor when D-38 lands. Wiring into the UI is F-162.
