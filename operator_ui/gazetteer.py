"""F-49: locate a US ZIP or city from a LOCAL file. No network, no paid geocoder. Truthfully None when the place is not in the file.

Default file: operator_ui/data/gazetteer_us.csv (small, hand-entered approximate town centroids: INFER, good to a few miles).
Set MBOS_GAZETTEER_FILE to a bigger CSV with the header zip,city,state,lat,lng to replace it. By default the Census 2023 ZIP and place files (AR + neighbours, public domain) are read after it; distances are centroid to centroid, approximate.
"""

from __future__ import annotations

import csv
import os
import re
from functools import lru_cache
from pathlib import Path

DEFAULT = Path(__file__).parent / "data" / "gazetteer_us.csv"
_ZIP = re.compile(r"^\d{5}(?:-\d{4})?$")


CENSUS = (Path(__file__).parent / "data" / "zcta_ar_region.csv", Path(__file__).parent / "data" / "places_ar_region.csv")  # Census 2023, public domain


def _norm(city: str) -> str:
    """Lower-case, 'St.'/'St' -> 'saint', punctuation dropped, so 'St. Francis' and 'Saint Francis' meet."""
    c = re.sub(r"\bst\b\.?", "saint", city.lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", c).split())


def _read(path, zips: dict, cities: dict, bare: dict) -> None:
    try:
        with open(path, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    c = (float(r["lat"]), float(r["lng"]))
                except (KeyError, TypeError, ValueError):
                    continue
                z, city, st = (r.get("zip") or "").strip(), _norm((r.get("city") or "").strip()), (r.get("state") or "").strip().lower()
                if z:
                    zips.setdefault(z, c)
                if city:
                    cities.setdefault((city, st), c)
                    bare.setdefault(city, {}).setdefault(st, c)
    except OSError:
        pass


@lru_cache(maxsize=4)
def _load(path: str) -> tuple[dict, dict]:
    """With MBOS_GAZETTEER_FILE only that file is read; the default is the small file, then the Census ZIP and place files."""
    zips, cities, bare = {}, {}, {}
    for p in ([path] if path != str(DEFAULT) else [path, *CENSUS]):
        _read(p, zips, cities, bare)
    for city, by_state in bare.items():  # a bare name prefers Arkansas, else the first state seen
        cities[(city, "")] = by_state.get("ar") or next(iter(by_state.values()))
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
        hit = cities.get((_norm(m.group(1).strip(" ,")), st))
        if hit:
            return hit
    return cities.get((_norm(t), ""))


def city_label(text: str | None) -> str:
    """Return ``City, ST`` for a known ZIP; leave an entered city unchanged."""
    value = " ".join(str(text or "").split())
    if not _ZIP.match(value):
        return value
    configured = os.environ.get("MBOS_GAZETTEER_FILE")
    paths = [Path(configured)] if configured else [DEFAULT, *CENSUS]
    for path in paths:
        try:
            with open(path, newline="", encoding="utf-8") as fh:
                for row in csv.DictReader(fh):
                    if (row.get("zip") or "").strip() == value[:5] and (row.get("city") or "").strip():
                        city = (row.get("city") or "").strip()
                        state = (row.get("state") or "").strip().upper()
                        return f"{city}, {state}" if state else city
        except OSError:
            continue
    return value
