# B-43: Facebook Marketplace via Bright Data (adapter built; live smoke BLOCKED)

Agent 02, 2026-10-12. Provenance: docs/handoff/B42_FACEBOOK_MARKETPLACE_ROUTES.md (lane 07, `632947d`); Bright Data docs read 2026-10-12 (dataset `gd_lvt9iwuh6fbcwmx1a`, `POST /datasets/v3/scrape`, keyword discovery inputs keyword/city/radius, discovery returns URLs only, then by-URL for full records).

## Built (FACT: tests)
- `src/mbos_discovery/adapters/brightdata_fb_marketplace.py` on the SourceAdapter seam, `source = brightdata_fb`. Live OFF by default; token read from `~/.config/mbos/secrets/BRIGHTDATA_TOKEN` at call time (whitespace stripped), kept out of URL, headers log, `repr`, errors (scrubbed) and raw bytes. Only `api.brightdata.com`, POST only to the scrape URL.
- Seller/profile keys dropped before raw bytes are hashed; every raw record carries `source_compliance: UNKNOWN (no Meta permission; owner-accepted provider route)`; Items get `needs_review`, tos_risk high, ingestion_method api.
- Hard cap 20 records (`HARD_CAP`) on the discovery limit and on output.
- Fields: title, price (final else initial), location text (city/state) and coordinates when given, images (https only, via the pHash path), url, condition, `product_id` as source id (URL fallback). `listing_date` is kept in `match_hints` and the raw record: Item v1 has no field for it (not changed; frozen contract).
- Policy row `brightdata_fb` (ALLOWED, tier 4, note carries the compliance label). Registry: `fb_marketplace` access_mode `api`, status `fixture`; local edit ahead of lane 04's `b0cb55e`, recorded in `data/PINNED.md` with the new sha256 (lane 04 should take it). `test_location` updated for the status.
- Tests: `tests/test_b43_brightdata_fb.py` (11) with synthetic fixtures `tests/fixtures/brightdata_fb/`. Lane suite: 451 passed, 0 failed.

## Live smoke (FACT): BLOCKED, no data
One run, keyword `tools`, Conway AR, 50-mile radius, cap 20: 1 request, HTTP 400 `Customer is not active`. Records 0; fields, location/radius honouring and listing_date: UNKNOWN (not observed). Cost: none shown; nothing was charged as far as the response says. Not retried.
INFER: the Bright Data account is not activated yet (verification, billing or free-tier enrolment). Owner action: finish activation in the Bright Data control panel, then re-run the smoke (Agent 01 can queue it; the adapter needs no change). Open UNKs for that run: accepted `city` spelling ("Conway, AR"), `radius` honoured, sync `/scrape` vs async 202 (the adapter errors on 202), cost.
Registry status therefore stays `fixture`.
