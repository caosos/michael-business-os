# B-44: Bright Data async (202) support + live smoke (PARTIAL: counts lost to a script bug)

Agent 02, 2026-10-12. Provenance: B-43 receipt; Bright Data docs (async `/scrape` -> 202 `snapshot_id`; `GET /datasets/v3/progress/<id>`; `GET /datasets/v3/snapshot/<id>?format=json`).

## Built (FACT: tests)
- `brightdata_fb_marketplace.py`: a 202 now carries a snapshot id; the adapter polls progress with back-off 5/10/20/30/30 s, total wait cap 300 s, then reads the snapshot. Failed status -> 502, cap reached -> 504 (clean `SourceError`, token scrubbed). Same token handling, same 20-record cap; GETs only to `api.brightdata.com`.
- Tests: 2 new in `tests/test_b43_brightdata_fb.py` (202 + poll + back-off + cost carry-over; wait cap and failed status). Lane suite: 453 passed, 0 failed.

## Live smoke (FACT): ONE run executed, analysis lost
Keyword `tools`, Conway AR, 50 mi, cap 20. Result: no error, 9 requests (async path used), **20 records returned** (the cap). Cost header: not shown (`None`).
My analysis script read the wrong attribute (`rec.parsed`, should be `rec.payload`) and crashed after printing the above; the records were held only in memory and nothing was stored. So these are UNKNOWN: fields present, distance of each record from Conway (radius/city honoured), listing_date presence, normalization success. I did not re-run: a second charged call is outside the "ONE bounded smoke" authorization.
Fixed script (counts only, no listing data): `tools/b44_live_smoke.py`.
Registry row `fb_marketplace` stays `fixture` (not `connected`) until radius/field evidence exists.

## Next
Owner/Agent 01 authorizes one more bounded run (`python -I tools/b44_live_smoke.py`), then flip the registry row to `connected` with that receipt as policy_ref.
