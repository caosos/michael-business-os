"""Deduplication (research §7, three layers; layer 3 re-alert suppression is the alerting
consumer's job and keys off `dedup_key` + `content_hash`).

1. Intra-source identity: (source, source_listing_id) → exactly one Item, forever.
   Re-discovery updates last_seen / content; it never creates a second Item.
2. Cross-source identity: same type + category, price within 15%, same place, and
   title token similarity ≥ 0.85 → merge as another `sources[]` sighting.
   Service leads instead match on a hashed contact fingerprint + category within 14 days
   (the same customer submitting twice, or a referral and a form for the same job).
"""

from __future__ import annotations

import re
from datetime import timedelta
from difflib import SequenceMatcher

from .ids import canonical_json, sha256_ref

TITLE_SIMILARITY = 0.85
PRICE_TOLERANCE = 0.15
NEAR_MILES = 10.0
SERVICE_WINDOW = timedelta(days=14)
RELIST_WINDOW = timedelta(days=14)
RELIST_TITLE_SIMILARITY = 0.90

_PRICE_BANDS = [0, 1, 100, 250, 500, 1000, 1500, 2500, 5000, 10000]
_STOP = frozenset("a an and the for with of in on to or w/ w obo firm sale used good great nice".split())
_TOKEN = re.compile(r"[a-z0-9]+")

# Fields that define "the listing changed" — flags are derived, so excluded.
_CONTENT_FIELDS = ("title", "description", "condition", "price", "ends_at", "bid_count",
                   "location", "listing_status")


def price_band(price: dict | None) -> str:
    if not price or price.get("amount") is None:
        return (price or {}).get("type") or "noprice"
    amt = price["amount"]
    if amt == 0:
        return "0"
    for lo, hi in zip(_PRICE_BANDS, _PRICE_BANDS[1:]):
        if lo <= amt < hi:
            return f"{lo}-{hi}"
    return f"{_PRICE_BANDS[-1]}+"


def geo_cell(location: dict | None) -> str:
    loc = location or {}
    if loc.get("lat") is not None and loc.get("lng") is not None:
        return f"cell-{loc['lat']:.1f}{loc['lng']:+.1f}"
    if loc.get("zip"):
        return f"zip-{str(loc['zip'])[:3]}"
    if loc.get("city"):
        return f"city-{loc['city'].lower().replace(' ', '_')}-{(loc.get('state') or '').lower()}"
    return "nogeo"


def dedup_key(item_type: str, category: str, normalized: dict, contact_fp: str | None = None) -> str:
    """Blocking key (never an identity — ruling R8) in the contract example's format, e.g.
    `trailer|1000-1500|cell-35.1-92.4`. Service leads with a contact block on a 64-bit prefix of the
    contact fingerprint (`drywall_repair|lead|fp-<16 hex>`) so the same customer's leads meet in one
    bucket; without one they fall back to the geo cell."""
    if item_type == "service":
        return f"{category}|lead|" + (f"fp-{contact_fp[:16]}" if contact_fp else geo_cell(normalized.get("location")))
    return f"{category}|{price_band(normalized.get('price'))}|{geo_cell(normalized.get('location'))}"


def content_hash(normalized: dict) -> str:
    return sha256_ref(canonical_json({k: normalized.get(k) for k in _CONTENT_FIELDS}))


def title_tokens(title: str) -> list[str]:
    return sorted({t for t in _TOKEN.findall((title or "").lower()) if t not in _STOP})


def title_similarity(a: str, b: str) -> float:
    ta, tb = title_tokens(a), title_tokens(b)
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, " ".join(ta), " ".join(tb)).ratio()


def _prices_close(a: dict | None, b: dict | None) -> bool:
    a_amt, b_amt = (a or {}).get("amount"), (b or {}).get("amount")
    if a_amt is None or b_amt is None:
        return False
    if a_amt == b_amt:
        return True
    hi = max(a_amt, b_amt)
    return hi > 0 and abs(a_amt - b_amt) / hi <= PRICE_TOLERANCE


def _same_place(a: dict | None, b: dict | None) -> bool:
    from .normalize import haversine_miles
    a, b = a or {}, b or {}
    if None not in (a.get("lat"), a.get("lng"), b.get("lat"), b.get("lng")):
        return haversine_miles((a["lat"], a["lng"]), (b["lat"], b["lng"])) <= NEAR_MILES
    if a.get("zip") and b.get("zip"):
        return str(a["zip"])[:3] == str(b["zip"])[:3] and (
            "*" in str(a["zip"]) + str(b["zip"]) or a["zip"] == b["zip"])
    if a.get("city") and b.get("city"):
        return (a["city"].lower(), (a.get("state") or "").lower()) == \
               (b["city"].lower(), (b.get("state") or "").lower())
    return False


def is_relist(cand: dict, cand_sighting: dict, item_type: str, category: str, normalized: dict) -> bool:
    """Same-source relist: the earlier listing ENDED (caller checks it is absent from the current fetch) and the
    same seller re-posts the same unit under a new id. Requires an identical non-empty seller name, same
    category, title similarity ≥ 0.90 and price within 15%. Two units listed at the same time (dealer twins)
    are never relists, because both are present in the same fetch."""
    seller_a = ((cand.get("normalized") or {}).get("counterparty") or {}).get("name")
    seller_b = (normalized.get("counterparty") or {}).get("name")
    return (cand["type"] == item_type and cand["category"] == category and bool(seller_a) and seller_a == seller_b
            and _prices_close((cand["normalized"]).get("price"), normalized.get("price"))
            and title_similarity(cand["normalized"].get("title", ""), normalized.get("title", "")) >= RELIST_TITLE_SIMILARITY)


def is_cross_source_duplicate(cand: dict, item_type: str, category: str, normalized: dict) -> bool:
    """`cand` is an existing Item. Flip/asset matching only; service uses fingerprints."""
    if cand["type"] != item_type or cand["category"] != category:
        return False
    cn = cand["normalized"]
    return (_prices_close(cn.get("price"), normalized.get("price"))
            and _same_place(cn.get("location"), normalized.get("location"))
            and title_similarity(cn.get("title", ""), normalized.get("title", "")) >= TITLE_SIMILARITY)
