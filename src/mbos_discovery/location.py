"""Offline ZIP lookup and location-scoped source selection (ADR-0015 section 4, B-39).

No geocoding service is called; no user location leaves the box. Selection is
by coverage only: it never connects, enables or fetches anything. A source
that is active for a user can still be `blocked` or `not_connected`; that
status is reported, not hidden.
"""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from typing import Optional

DEFAULT_METRO_RADIUS_MI = 100.0
_EARTH_MI = 3958.7613


@dataclass(frozen=True)
class User:
    home_zip: Optional[str] = None
    home_state: Optional[str] = None
    home_lat: Optional[float] = None
    home_lng: Optional[float] = None
    default_radius_mi: Optional[float] = None


# The owner row as seeded by ADR-0015: Conway AR 72032, 150 mi.
OWNER = User(home_zip="72032", home_state="AR", default_radius_mi=150.0)


@dataclass(frozen=True)
class SourceChoice:
    source_id: str
    active: bool
    reason: str
    status: str
    radius_mi: float


@lru_cache(maxsize=1)
def _zcta() -> dict:
    text = resources.files("mbos_discovery").joinpath("data/zcta_centroids.csv").read_text()
    return {r["zip"]: (float(r["lat"]), float(r["lng"])) for r in csv.DictReader(text.splitlines())}


def zip_centroid(zip_code: str) -> Optional[tuple]:
    """(lat, lng) for a 5-digit ZIP/ZCTA, or None. Accepts ZIP+4 and whitespace."""
    z = (zip_code or "").strip()[:5]
    return _zcta().get(z) if len(z) == 5 and z.isdigit() else None


def load_registry() -> list:
    raw = resources.files("mbos_discovery").joinpath("data/sources.v1.json").read_text()
    return json.loads(raw)["sources"]


def distance_mi(a: tuple, b: tuple) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * _EARTH_MI * math.asin(math.sqrt(h))


def user_point(user: User) -> Optional[tuple]:
    if user.home_lat is not None and user.home_lng is not None:
        return (user.home_lat, user.home_lng)
    return zip_centroid(user.home_zip) if user.home_zip else None


def default_radius(user: User, source: dict) -> float:
    """Profile default if set, else 100 mi for metro/point sources.

    For national sources the same number is the pickup-distance filter; with no
    profile value it falls back to 100 mi. A per-search override wins over this.
    """
    if user.default_radius_mi is not None:
        return float(user.default_radius_mi)
    return float(source.get("coverage", {}).get("radius_mi") or DEFAULT_METRO_RADIUS_MI)


def sources_for(user: User, registry: Optional[list] = None) -> list:
    """Every registry source with an active flag and a reason, active ones first."""
    pt = user_point(user)
    state = (user.home_state or "").upper() or None
    out = []
    for s in registry if registry is not None else load_registry():
        cov = s["coverage"]
        scope = cov["scope"]
        radius = default_radius(user, s)
        if scope == "national":
            active, why = True, "national coverage"
        elif state and state in [x.upper() for x in cov.get("states", [])] and scope == "states":
            active, why = True, "home state %s in coverage" % state
        elif scope in ("metro", "point") and pt and cov.get("center"):
            c = cov["center"]
            d = distance_mi(pt, (c["lat"], c["lng"]))
            reach = float(cov.get("radius_mi") or DEFAULT_METRO_RADIUS_MI) + radius
            active = d <= reach
            why = "%.0f mi from center, reach %.0f mi" % (d, reach)
        else:
            active, why = False, "location unknown or outside coverage"
        out.append(SourceChoice(s["source_id"], active, why, s["status"], radius))
    out.sort(key=lambda c: not c.active)
    return out
