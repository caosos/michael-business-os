"""Filter Census 2023 Gazetteer (public domain) to Arkansas + neighbouring states. usage: python -I census_filter.py ZCTA_TXT PLACE_TXT OUTDIR"""
import csv, sys
from pathlib import Path
zt, pt, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]); out.mkdir(parents=True, exist_ok=True)
STATES = {"AR", "MO", "OK", "TX", "LA", "MS", "TN"}
# USPS ZIP3 prefixes by state (public USPS ranges) for the ZCTA file, which has no state column
RANGES = {"AR": (716, 729), "MO": (630, 658), "OK": (730, 749), "TX": (750, 799), "LA": (700, 714), "MS": (386, 397), "TN": (370, 385)}
def state_of(z):
    p = int(z[:3])
    for s, (a, b) in RANGES.items():
        if a <= p <= b and not (s == "TX" and p in (733,)) :
            return s
    return None
def rows(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        r = csv.reader(f, delimiter="\t")
        head = [h.strip() for h in next(r)]
        for line in r:
            yield dict(zip(head, [c.strip() for c in line]))
zn = 0
with open(out / "zcta_ar_region.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["zip", "state", "lat", "lng"])
    for d in rows(zt):
        z = d["GEOID"]; s = state_of(z)
        if s:
            w.writerow([z, s, round(float(d["INTPTLAT"]), 5), round(float(d["INTPTLONG"]), 5)]); zn += 1
pn = 0
with open(out / "places_ar_region.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["city", "state", "lat", "lng", "kind"])
    for d in rows(pt):
        if d["USPS"] in STATES:
            name = d["NAME"]
            for suf, kind in ((" city", "city"), (" town", "town"), (" CDP", "cdp"), (" village", "village")):
                if name.endswith(suf):
                    name, k = name[: -len(suf)], kind; break
            else:
                k = "other"
            w.writerow([name, d["USPS"], round(float(d["INTPTLAT"]), 5), round(float(d["INTPTLONG"]), 5), k]); pn += 1
print({"zcta_rows": zn, "place_rows": pn})
