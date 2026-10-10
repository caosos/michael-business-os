"""B-23: Arkansas auction discovery — source inventory, per-house terms, fixture-first read-only adapters.

Scope: lots within ~100 miles of Conway (statewide only when `exceptional` says the margin is exceptional).
**No live path exists here.** `fetch()` reads fixture files only; a live fetch is the existing B-12 owner step
(docs/runbooks/first-live-run-checklist.md) and per ADR-02-0202 govdeals / publicsurplus / hibid / allsurplus /
municibid are PENDING_MICHAEL (tier 3), so they stay disabled; their alert emails (tier 2) and GSA (tier 1) are allowed.

Every captured lot field carries its own source and freshness (`Field`). The Item v1 `normalized` object is
`additionalProperties: false`, so the rich record is `AuctionLot`; `to_normalized()` yields the Item subset.
Fixtures are hand-built from the fields auction sites commonly show — real response shapes are UNKNOWN until B-12.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from .canonical import raw_json_bytes
from .ids import iso
from .normalize import HOME_BASE, base_flags, classify, clean_text, geo_tier, haversine_miles, match_text, money, norm_ts
from .policy import policy_for

UNKNOWN = "UNKNOWN"
STALE_AFTER_S = 6 * 3600     # INFERENCE: current bid / bid count older than 6h is stale for a closing-soon decision

# lat/lng of Arkansas towns (approximate centroids, INFERENCE) so a lot with only a city can be distance-filtered.
AR_PLACES: dict[str, tuple[float, float]] = {
    "conway": (35.0887, -92.4421), "little rock": (34.7465, -92.2896), "north little rock": (34.7695, -92.2671),
    "benton": (34.5645, -92.5868), "searcy": (35.2506, -91.7362), "russellville": (35.2784, -93.1338),
    "morrilton": (35.1509, -92.7435), "heber springs": (35.4917, -92.0332), "hot springs": (34.5037, -93.0552),
    "pine bluff": (34.2284, -92.0032), "jonesboro": (35.8423, -90.7043), "fort smith": (35.3859, -94.3985),
    "fayetteville": (36.0626, -94.1574), "texarkana": (33.4418, -94.0377), "el dorado": (33.2076, -92.6663),
    "marianna": (34.7737, -90.7576), "greenbrier": (35.2326, -92.3912),
}


@dataclass(frozen=True)
class Field:
    """One captured value with its provenance: where it came from, when seen, and how sure we are."""
    value: Any
    source: str                      # URL or fixture file the value was read from
    observed_at: str                 # ISO-8601 UTC
    basis: str = "FACT"              # FACT (shown by source) | INFERENCE | UNKNOWN
    age_seconds: int = 0

    @property
    def stale(self) -> bool:
        return self.age_seconds > STALE_AFTER_S


@dataclass
class AuctionLot:
    source: str
    lot_id: str
    fields: dict[str, Field]
    distance_miles: float | None = None

    def get(self, name: str):
        f = self.fields.get(name)
        return f.value if f else None


LOT_FIELDS = ("title", "current_bid", "bid_count", "closes_at", "buyer_premium_pct", "sales_tax_pct",
              "pickup", "rules_url", "location", "category")


@dataclass(frozen=True)
class AuctionHouse:
    """Per-house terms (B-23). Every value is UNKNOWN until read from the house's own terms page (B-12 owner step)."""
    source: str
    name: str
    kind: str                       # government | municipal | auctioneer_platform | estate_equipment | vehicle | federal
    policy_tier: int
    terms_url: str
    registration: str = UNKNOWN
    dealer_or_licence_required: str = UNKNOWN
    deposit: str = UNKNOWN
    buyer_premium: str = UNKNOWN
    card_surcharge: str = UNKNOWN
    payment: str = UNKNOWN
    inspection_window: str = UNKNOWN
    pickup_window: str = UNKNOWN
    online_bidding_public: str = UNKNOWN
    categories: tuple[str, ...] = ()
    terms_verified: bool = False

    def unknown_terms(self) -> list[str]:
        return [k for k in ("registration", "dealer_or_licence_required", "deposit", "buyer_premium", "card_surcharge",
                            "payment", "inspection_window", "pickup_window", "online_bidding_public")
                if getattr(self, k) == UNKNOWN]


# Source inventory. Terms are deliberately UNKNOWN: nothing here has been read live. Names are the platforms
# named in ADR-02-0202 / the B-23 row; Arkansas-local auctioneers are added from alert emails / owner input.
HOUSES: dict[str, AuctionHouse] = {h.source: h for h in [
    AuctionHouse("gsa_auctions", "GSA Auctions", "federal", 1, "https://gsaauctions.gov", categories=("vehicle", "equipment")),
    AuctionHouse("govdeals", "GovDeals", "government", 3, "https://www.govdeals.com", categories=("vehicle", "equipment", "tools")),
    AuctionHouse("publicsurplus", "PublicSurplus", "government", 3, "https://www.publicsurplus.com", categories=("vehicle", "equipment")),
    AuctionHouse("allsurplus", "AllSurplus", "auctioneer_platform", 3, "https://www.allsurplus.com", categories=("vehicle", "equipment")),
    AuctionHouse("municibid", "Municibid", "municipal", 3, "https://municibid.com", categories=("vehicle", "equipment")),
    AuctionHouse("hibid", "HiBid (Arkansas auctioneers)", "estate_equipment", 3, "https://hibid.com", categories=("estate", "equipment", "vehicle")),
    AuctionHouse("ar_state_surplus", "Arkansas state surplus", "government", 1, "https://www.transform.ar.gov", categories=("vehicle", "equipment")),
    AuctionHouse("vehicle_salvage_platforms", "Copart / IAA-type vehicle auctions", "vehicle", 5, "https://www.copart.com", categories=("vehicle",)),
]}


def house_terms_gap(source: str) -> list[str]:
    h = HOUSES.get(source)
    return h.unknown_terms() if h else ["house not in inventory"]


def place_coords(location: dict) -> tuple[float, float] | None:
    if isinstance(location.get("lat"), (int, float)) and isinstance(location.get("lng"), (int, float)):
        return float(location["lat"]), float(location["lng"])
    return AR_PLACES.get(clean_text(location.get("city")).lower())


def in_scope(distance: float | None, state: str | None, radius: float, exceptional: bool = False) -> bool:
    """Within `radius` of Conway; statewide (AR) only when the margin is flagged exceptional. Unknown distance: out."""
    if distance is None:
        return False
    if distance <= radius:
        return True
    return exceptional and (state or "").upper() == "AR"


class AuctionFixtureAdapter(SourceAdapter):
    """Reads `<fixture_dir>/<source>.json` ({"lots":[...]}) — never the network. Live fetch is refused."""
    ingestion_method = "fixture"
    tos_risk = "low"
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, source: str, fixture_dir: str | Path, clock: Callable[[], datetime] | None = None,
                 exceptional: Callable[[dict], bool] | None = None, observed_at: datetime | None = None) -> None:
        self.source = source                                    # type: ignore[misc]
        self.access_tier = policy_for(source).tier              # type: ignore[misc]
        self.path = Path(fixture_dir) / f"{source}.json"
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.exceptional = exceptional

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        try:
            body = json.loads(self.path.read_bytes())
            lots = body["lots"]
        except (OSError, ValueError, KeyError) as e:
            res.error = SourceError("parse", f"auction fixture unreadable: {e}")
            return res
        fetched_at = self.clock()
        for lot in lots:
            if not isinstance(lot, dict):
                continue
            loc = lot.get("location") or {}
            c = place_coords(loc)
            d = haversine_miles(HOME_BASE, c) if c else None
            if not in_scope(d, loc.get("state"), profile.radius_miles, bool(self.exceptional and self.exceptional(lot))):
                continue
            res.records.append(RawRecord(raw_json_bytes(lot), lot, fetched_at, f"fixture://{self.path.name}"))
        return res

    def lot(self, payload: dict, fetched_at: datetime) -> AuctionLot:
        if not isinstance(payload, dict) or not payload.get("lot_id") or not payload.get("title"):
            raise NormalizationError("auction lot missing lot_id/title")
        src = f"fixture://{self.path.name}"
        seen = norm_ts(payload.get("observed_at")) or iso(fetched_at)
        age = max(0, int((fetched_at - datetime.fromisoformat(seen.replace("Z", "+00:00"))).total_seconds()))

        def fld(name, value, basis="FACT"):
            return Field(value if value is not None else UNKNOWN, src, seen, basis if value is not None else "UNKNOWN", age)

        loc = payload.get("location") or {}
        c = place_coords(loc)
        dist = round(haversine_miles(HOME_BASE, c), 1) if c else None
        title = clean_text(payload["title"], 300)
        kind = clean_text(payload.get("kind")).lower()
        category, _ = classify("flip", match_text(title))
        if kind == "vehicle":
            category = "project_vehicle"
        f = {
            "title": fld("title", title),
            "current_bid": fld("current_bid", money(payload.get("current_bid"))),
            "bid_count": fld("bid_count", payload["bid_count"] if isinstance(payload.get("bid_count"), int) else None),
            "closes_at": fld("closes_at", norm_ts(payload.get("closes_at"))),
            "buyer_premium_pct": fld("buyer_premium_pct", money(payload.get("buyer_premium_pct"))),
            "sales_tax_pct": fld("sales_tax_pct", money(payload.get("sales_tax_pct"))),     # UNKNOWN unless the lot states it
            "pickup": fld("pickup", clean_text(payload.get("pickup"), 500) or None),
            "rules_url": fld("rules_url", clean_text(payload.get("rules_url")) or None),
            "location": fld("location", {k: v for k, v in loc.items() if k in ("city", "state", "zip", "lat", "lng")} or None),
            "category": fld("category", "vehicle" if kind == "vehicle" else category, "INFERENCE"),
        }
        return AuctionLot(self.source, clean_text(payload["lot_id"]), f, dist)

    def normalize(self, payload: Any, fetched_at: datetime) -> Normalized:
        lot = self.lot(payload, fetched_at)
        bid, count, ends = lot.get("current_bid"), lot.get("bid_count"), lot.get("closes_at")
        bid = bid if isinstance(bid, float) else None
        count = count if isinstance(count, int) else None
        ends = ends if ends != UNKNOWN else None
        bp = lot.get("buyer_premium_pct")
        price = {"currency": "USD", "type": "auction_current" if bid else "starting_bid",
                 "buyer_premium_pct": bp if isinstance(bp, float) else 0}
        if bid:
            price["amount"] = bid
        category = "project_vehicle" if lot.get("category") == "vehicle" else lot.get("category")
        loc = lot.get("location") if isinstance(lot.get("location"), dict) else {}
        n: dict = {"title": lot.get("title"), "condition": "used", "price": price,
                   "counterparty": {"role": "auction_house", "name": HOUSES[self.source].name} if self.source in HOUSES
                   else {"role": "auction_house"},
                   "listing_status": "active", "images": []}
        if ends:
            n["ends_at"] = ends
        if count is not None:
            n["bid_count"] = count
        if loc:
            n["location"] = {**{k: v for k, v in loc.items() if k in ("city", "state", "zip", "lat", "lng")},
                             **({"geo_tier": geo_tier(lot.distance_miles)} if lot.distance_miles is not None else {})}
        flags = base_flags(price=price, bid_count=count, ends_at=ends, fetched_at=fetched_at,
                           matched=category != "other_asset", tier=None, texts=(lot.get("title"),))
        if any(f.stale for f in lot.fields.values() if f.value != UNKNOWN):
            flags = sorted(set(flags) | {"needs_review"})
        if flags:
            n["flags"] = flags
        return Normalized(source_listing_id=lot.lot_id, url=lot.get("rules_url") if lot.get("rules_url") != UNKNOWN
                          else f"{self.source}://{lot.lot_id}", type="flip", category=category,
                          opportunity_kind="auction_lot", normalized=n,
                          subcategory="vehicle" if lot.get("category") == "vehicle" else None)
