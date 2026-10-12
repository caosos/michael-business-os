# Census 2023 Gazetteer, filtered to Arkansas + neighbouring states (for F-150 distance lookups)
- Source (US Census Bureau, public domain): https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2023_Gazetteer/2023_Gaz_zcta_national.zip (sha256 75191ab2d3df4b668fb511d2726d97c521d6d1ff555725704a5d9bb3bc2077ce) and .../2023_Gaz_place_national.zip (sha256 3c8b23c0dcdb15c0ebd16fee7373e032466e6b585650aa219bc1bee5ac8bd58f); downloaded by Agent 01 2026-10-12T02:25:32Z.
- Filter: `census_filter.py` (in this folder): ZCTA rows whose ZIP3 prefix falls in the USPS ranges for AR, MO, OK, TX, LA, MS, TN (the ZCTA file has no state column; state is INFERRED from the prefix); place rows with USPS in those states, with the Census suffix (city/town/CDP/village) moved to `kind`.
- `zcta_ar_region.csv`: zip,state,lat,lng (5,906 rows; internal point of the ZIP Code Tabulation Area, an approximation of a USPS ZIP).
- `places_ar_region.csv`: city,state,lat,lng,kind (5,836 rows; internal point of the Census place).
- Distances from these points are approximate (centroid to centroid); the UI already labels distances approximate.
