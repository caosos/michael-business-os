"""F-49: locate a US ZIP or city from a LOCAL file. No network, no paid geocoder. Truthfully None when the place is not in the file.

Default file: operator_ui/data/gazetteer_us.csv (small, hand-entered approximate town centroids: INFER, good to a few miles).
Set MBOS_GAZETTEER_FILE to a bigger CSV with the header zip,city,state,lat,lng (e.g. built from the Census ZCTA gazetteer) to widen it.
"""

from __future__ import annotations

import csv
import os
import re
from functools import lru_cache
from pathlib import Path

DEFAULT = Path(__file__).parent / "data" / "gazetteer_us.csv"
_ZIP = re.compile(r"^\d{5}(?:-\d{4})?$")


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[dict, dict]:
    zips, cities = {}, {}
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    c = (float(r["lat"]), float(r["lng"]))
                except (KeyError, TypeError, ValueError):
                    continue
                z, city, st = (r.get("zip") or "").strip(), (r.get("city") or "").strip().lower(), (r.get("state") or "").strip().lower()
                if z:
                    zips.setdefault(z, c)
                if city:
                    cities.setdefault((city, st), c)
                    cities.setdefault((city, ""), c)
    except OSError:
        pass
    return zips, cities


def locate(text: str | None):
    """-> (lat, lng) or None. Accepts '72032', '72032-1234', 'Conway', 'Conway, AR', 'Conway Arkansas'."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    zips, cities = _load(os.environ.get("MBOS_GAZETTEER_FILE") or str(DEFAULT))
    if _ZIP.match(t):
        return zips.get(t[:5])
    m = re.match(r"^(.*?)[, ]+([A-Za-z]{2}|arkansas)$", t, flags=re.I)
    if m:
        st = "ar" if m.group(2).lower() == "arkansas" else m.group(2).lower()
        hit = cities.get((m.group(1).strip(" ,").lower(), st))
        if hit:
            return hit
    return cities.get((t.lower(), ""))
