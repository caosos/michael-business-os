"""Shared, pure normalization helpers used by every adapter.

Category rules are keyword based and ordered: the first matching rule wins, so the
result never depends on dict ordering or locale. Unmatched text falls to
`other_asset` / `other_service` with a `needs_review` flag rather than guessing.
"""

from __future__ import annotations

import math
import re
import unicodedata
from datetime import datetime, timedelta

from .ids import iso

HOME_BASE = (35.0887, -92.4421)          # Conway, AR 72034
MAX_DESCRIPTION = 4000
ENDING_SOON = timedelta(hours=24)

# (category, subcategory-or-None, patterns). Order matters: specific before general.
FLIP_RULES: list[tuple[str, list[str]]] = [
    ("trailer", [r"\btrailers?\b", r"\bflatbed\b", r"\bcar hauler\b", r"\bdump trailer\b"]),
    ("mower", [r"\bmowers?\b", r"\bzero[- ]?turn\b", r"\blawn tractor\b", r"\briding mower\b"]),
    ("generator", [r"\bgenerators?\b", r"\bgenset\b", r"\binverter generator\b"]),
    ("welder", [r"\bwelders?\b", r"\bwelding\b", r"\bplasma cutter\b", r"\bmig\b", r"\btig\b"]),
    ("compressor", [r"\bcompressors?\b"]),
    ("commercial_equipment", [r"\bforklift\b", r"\bpallet jack\b", r"\bcommercial\b", r"\brestaurant\b",
                              r"\bindustrial\b", r"\bwalk[- ]in cooler\b"]),
    ("mechanical_equipment", [r"\bpressure washer\b", r"\blog splitter\b", r"\btiller\b", r"\bengine\b",
                              r"\bwater pump\b", r"\btransfer pump\b", r"\bsmall engine\b"]),
    ("tool", [r"\btools?\b", r"\bdrill\b", r"\bimpact driver\b", r"\bimpact wrench\b", r"\bsaw\b",
              r"\btool ?box\b", r"\bchainsaw\b", r"\bwrench(es)?\b", r"\bsocket set\b"]),
    ("project_vehicle", [r"\bproject (car|truck)\b", r"\bpickup truck\b", r"\bjeep\b", r"\batv\b",
                         r"\butv\b", r"\bmotorcycle\b", r"\bgo[- ]?kart\b", r"\bdirt bike\b"]),
]

SERVICE_RULES: list[tuple[str, list[str]]] = [
    ("drywall_repair", [r"\bdrywall\b", r"\bsheetrock\b", r"\bhole in (the |my )?wall\b", r"\btexture match\b"]),
    ("mobile_repair", [r"\b(phone|iphone|android|tablet|ipad) (screen|repair|battery)\b",
                       r"\bcracked screen\b", r"\bscreen replacement\b"]),
    ("smart_home_install", [r"\bsmart (home|lock|thermostat|switch)\b", r"\bthermostat\b",
                            r"\bvideo doorbell\b", r"\bdoorbell\b", r"\bsecurity cameras?\b",
                            r"\btv (wall )?mount(ing)?\b", r"\bmount (a |my )?tv\b"]),
    ("assembly", [r"\bassembl(e|y|ing)\b", r"\bikea\b", r"\bflat[- ]?pack\b"]),
    ("equipment_repair", [r"\b(mower|generator|compressor|welder|small engine|pressure washer)\b.*\b(repair|fix|won'?t start|not starting)\b",
                          r"\b(repair|fix)\b.*\b(mower|generator|compressor|welder|small engine|pressure washer)\b"]),
    ("mechanical_service", [r"\bbrakes?\b", r"\boil change\b", r"\bmechanic\b", r"\balternator\b",
                            r"\bstarter\b", r"\bcar (repair|won'?t start)\b"]),
    ("technical_service", [r"\bwi-?fi\b", r"\bnetwork(ing)?\b", r"\brouter\b", r"\bcomputer\b",
                           r"\blaptop\b", r"\bprinter\b"]),
    ("handyman", [r"\bhandyman\b", r"\bfaucet\b", r"\bdoor\b", r"\bshel(f|ves)\b", r"\bfix\b",
                  r"\brepair\b", r"\binstall\b", r"\bcaulk\b", r"\bgutter\b"]),
]

_COMPILED = {
    "flip": [(c, [re.compile(p) for p in ps]) for c, ps in FLIP_RULES],
    "service": [(c, [re.compile(p) for p in ps]) for c, ps in SERVICE_RULES],
}

_INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) instructions|disregard (the )?(system|previous)"
    r"|system prompt|you are (now )?an? (ai|assistant|language model)|<\s*/?\s*(system|assistant)\s*>"
    r"|approve this (purchase|offer)|send (me )?(the )?(money|payment) (now|immediately)",
    re.IGNORECASE,
)

_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS = re.compile(r"\s+")


def clean_text(value, limit: int | None = None) -> str:
    if value is None:
        return ""
    s = unicodedata.normalize("NFKC", str(value))
    s = _CTRL.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    if limit and len(s) > limit:
        s = s[:limit].rstrip() + "…"
    return s


def match_text(*parts) -> str:
    return clean_text(" ".join(p for p in parts if p)).lower()


def classify(lane: str, *texts: str) -> tuple[str, bool]:
    """Return (category, matched). `texts` are tried in priority order (e.g. title before
    description), so incidental words in a description never override the headline.
    Unmatched → other_* (caller adds needs_review)."""
    for text in texts:
        for category, patterns in _COMPILED[lane]:
            if any(p.search(text) for p in patterns):
                return category, True
    return ("other_asset" if lane == "flip" else "other_service"), False


def injection_suspected(*texts: str) -> bool:
    return any(_INJECTION.search(t or "") for t in texts)


def haversine_miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def geo_tier(miles: float) -> int:
    """Research §9 rings from Conway. INFERENCE: straight-line/pickup distance, not road
    miles — `road_miles_one_way` is left for the RESEARCH stage (Agent 03 owns distance cost)."""
    if miles < 35:
        return 0
    if miles < 100:
        return 1
    if miles < 160:
        return 2
    return 3


def money(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        amt = float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None
    if math.isnan(amt) or amt < 0:
        return None
    return round(amt, 2)


def norm_ts(value) -> str | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    return iso(dt)


def base_flags(*, price: dict | None, bid_count: int | None, ends_at: str | None,
               fetched_at: datetime, matched: bool, tier: int | None, texts: tuple[str, ...]) -> list[str]:
    flags: set[str] = set()
    if price and price.get("type") == "free":
        flags.add("free")
    if price and price.get("type") in ("auction_current", "starting_bid") and bid_count == 0:
        flags.add("zero_bid")
    if ends_at:
        end = datetime.fromisoformat(ends_at.replace("Z", "+00:00"))
        if timedelta(0) <= end - fetched_at <= ENDING_SOON:
            flags.add("ending_soon")
    if not matched:
        flags.add("needs_review")
    if tier is not None and tier >= 2:
        flags.add("long_distance")
    if injection_suspected(*texts):
        flags.update({"injection_suspected", "needs_review"})
    return sorted(flags)
