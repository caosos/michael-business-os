import sys, json, collections
sys.path.insert(0, 'src')  # run from the repo root: python -I tools/b44_live_smoke.py (ONE charged live call; prints counts only)
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters.brightdata_fb_marketplace import BrightDataFbMarketplaceAdapter as A, HARD_CAP
from mbos_discovery.normalize import HOME_BASE, haversine_miles
a=A(live=True)
r=a.fetch(SearchProfile("flip-fb","flip",("tools",),radius_miles=50,limit=20))
print("error:", (r.error.kind, r.error.status, r.error.message[:200]) if r.error else None)
print("requests:", r.requests_made, "records:", len(r.records), "cost:", a.last_cost)
fields=collections.Counter(); dist=collections.Counter(); ld=0; norm=0; coords=0
for rec in r.records:
    d=rec.payload
    fields.update(k for k,v in d.items() if v not in (None,"",[],{}))
    loc=d.get("location"); src=loc if isinstance(loc,dict) else d
    lat,lng=src.get("latitude",src.get("lat")),src.get("longitude",src.get("lng",src.get("lon")))
    if isinstance(lat,(int,float)) and isinstance(lng,(int,float)):
        coords+=1; mi=haversine_miles(HOME_BASE,(lat,lng)); dist["<=50" if mi<=50 else "50-100" if mi<=100 else ">100"]+=1
    else: dist["no_coords"]+=1
    if d.get("listing_date"): ld+=1
    try: a.normalize(d, a.clock()); norm+=1
    except Exception: pass
print("fields:", dict(fields)); print("distance buckets:", dict(dist)); print("listing_date:", ld, "normalized_ok:", norm)
