"""B-25: GSA Auctions live adapter (tier 1, read-only, DEMO_KEY) feeding the B-23 `AuctionLot` shape.

Endpoint (smoke receipt docs/receipts/2026-10-09-gsa-api-smoke.md):
    GET https://api.gsa.gov/assets/gsaauctions/v2/auctions?api_key=DEMO_KEY&format=JSON  -> HTTP 303 -> signed S3 `active-auctions.json`
Response `{"Results":[{saleNo, lotNo, itemName, aucEndDt, highBidAmount, biddersCount, propertyCity/State (where the lot
is), locationCity/ST (the selling office, NOT the lot), itemDescURL, imageURL, lotInfo (HTML)}]}`. No buyer premium and no
sold prices exist in it: both stay UNKNOWN. `highBidAmount` is the CURRENT bid, never a sold price.

Rate/side-effect guard: at most ONE network fetch per `fetch()` (both hops count as one logical fetch: the API hop and its 303
target), the body is cached on disk and reused while fresh, a 429 is surfaced and not retried. No account, no paid key
(`DEMO_KEY` only unless the owner sets GSA_API_KEY), nothing is bid or sent. Live use needs `live=True`.
"""

from __future__ import annotations

import html
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

from .adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceError
from .auctions import HOUSES, UNKNOWN, AuctionFixtureAdapter, AuctionLot, Field, place_coords
from .canonical import raw_json_bytes
from .http import ReadOnlyTransport, Transport, TransportError, UrllibTransport, redact, status_error
from .ids import iso
from .normalize import HOME_BASE, base_flags, classify, clean_text, geo_tier, haversine_miles, match_text, money, norm_ts

API = "https://api.gsa.gov/assets/gsaauctions/v2/auctions"
HOSTS = frozenset({"api.gsa.gov"})
S3_SUFFIX = ".amazonaws.com"                       # the 303 target; any other host is refused
NEARBY_STATES = frozenset({"AR", "MO", "TN", "MS", "LA", "TX", "OK"})
CACHE_TTL = timedelta(hours=1)                      # respect api.data.gov's 10-per-window DEMO_KEY limit
_TAG = re.compile(r"<[^>]+>")


def _text(s) -> str:
    return clean_text(html.unescape(_TAG.sub(" ", str(s or ""))), 4000)


class GsaLiveAdapter(AuctionFixtureAdapter):
    source = "gsa_auctions"
    ingestion_method = "api"
    tos_risk = "low"
    access_tier = 1
    adapter_version = "2.0.0"

    def __init__(self, cache_path: str | Path, *, live: bool = False, transport: Transport | None = None,
                 api_key: str = "DEMO_KEY", states: frozenset[str] = NEARBY_STATES,
                 clock: Callable[[], datetime] | None = None) -> None:
        self.cache = Path(cache_path)
        self.asof_file = self.cache.with_suffix(".asof")
        self.live, self.api_key, self.states = live, api_key, frozenset(states)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.http = ReadOnlyTransport(transport or UrllibTransport(follow_redirects=False), HOSTS)
        self.exceptional = None
        self.summary: dict = {}

    def _asof(self) -> datetime | None:
        try:
            return datetime.fromisoformat(self.asof_file.read_text().strip())
        except (OSError, ValueError):
            return None

    def _download(self) -> tuple[bytes | None, SourceError | None]:
        """One logical fetch: API hop, then follow its 303 once to the S3 file."""
        try:
            r = self.http.request("GET", f"{API}?api_key={self.api_key}&format=JSON", {"Accept": "application/json"})
            if r.status in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location") or r.headers.get("location") or ""
                host = urlsplit(loc).hostname or ""
                if not host.endswith(S3_SUFFIX):
                    return None, SourceError("parse", f"redirect to unexpected host refused: {host or 'none'}", r.status)
                r = self.http._inner.request("GET", loc, {"Accept": "application/json"})   # signed URL; host checked above
        except TransportError as e:
            return None, SourceError("network", str(e))
        err = status_error(r, "GSA Auctions")
        return (None, err) if err else (r.body, None)

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        now = self.clock()
        asof, body = self._asof(), None
        if self.cache.exists() and asof and now - asof < CACHE_TTL:
            body = self.cache.read_bytes()
        elif not self.live:
            res.error = SourceError("config", "live GSA fetch not enabled (live=True) and no fresh cache")
            return res
        else:
            body, err = self._download()
            res.requests_made = 1
            if err:
                res.error = err
                return res
            self.cache.parent.mkdir(parents=True, exist_ok=True)
            self.cache.write_bytes(body)
            self.asof_file.write_text(iso(now))
            asof = now
        try:
            lots = json.loads(body)["Results"]
            if not isinstance(lots, list):
                raise ValueError("Results is not a list")
        except (ValueError, KeyError, TypeError) as e:
            res.error = SourceError("parse", f"GSA response malformed: {e}")
            return res
        self._observed = asof or now
        kept = 0
        for lot in lots:
            if not isinstance(lot, dict) or clean_text(lot.get("propertyState")).upper() not in self.states:
                continue
            kept += 1
            res.records.append(RawRecord(raw_json_bytes(lot), lot, self._observed, redact(API)))
        self.summary = {"as_of": iso(self._observed), "lots_in_file": len(lots), "lots_in_scope": kept,
                        "states": sorted(self.states), "from_cache": res.requests_made == 0}
        return res

    def lot(self, p: dict, fetched_at: datetime) -> AuctionLot:
        if not isinstance(p, dict) or not p.get("saleNo") or not p.get("lotNo") or not p.get("itemName"):
            raise NormalizationError("GSA lot missing saleNo/lotNo/itemName")
        seen = iso(getattr(self, "_observed", fetched_at))
        age = max(0, int((fetched_at - datetime.fromisoformat(seen.replace("Z", "+00:00"))).total_seconds()))
        src = redact(API)

        def fld(v, basis="FACT"):
            return Field(v if v not in (None, "") else UNKNOWN, src, seen, basis if v not in (None, "") else "UNKNOWN", age)

        city, state = clean_text(p.get("propertyCity")).title(), clean_text(p.get("propertyState")).upper()
        loc = {k: v for k, v in {"city": city, "state": state,
                                 "zip": "".join(c for c in str(p.get("propertyZip") or "") if c.isdigit())[:5]}.items() if v}
        c = place_coords(loc)
        dist = round(haversine_miles(HOME_BASE, c), 1) if c else None
        title = clean_text(p["itemName"], 300)
        end = clean_text(p.get("aucEndDt"))[:10]
        bidders = p.get("biddersCount")
        category, _ = classify("flip", match_text(title))
        f = {
            "title": fld(title), "current_bid": fld(money(p.get("highBidAmount"))),
            "bid_count": fld(bidders if isinstance(bidders, int) else None),
            # date only in the source: end-of-day UTC is an upper bound (INFERENCE)
            "closes_at": fld(norm_ts(f"{end}T23:59:59Z") if len(end) == 10 else None, "INFERENCE"),
            "buyer_premium_pct": fld(None), "sales_tax_pct": fld(None), "pickup": fld(None),
            "rules_url": fld(clean_text(p.get("itemDescURL"))), "location": fld(loc or None),
            "category": fld(category, "INFERENCE"), "image_url": fld(clean_text(p.get("imageURL"))),
            "lot_info": fld(p.get("lotInfo")),                      # verbatim (HTML as supplied)
            "agency": fld(clean_text(p.get("agencyName"), 100)),
            "sold_price": Field(UNKNOWN, src, seen, "UNKNOWN", age),   # a high bid is never a sold comp
        }
        return AuctionLot(self.source, f"{clean_text(p['saleNo'])}-{clean_text(p['lotNo'])}", f, dist)

    def normalize(self, payload, fetched_at: datetime) -> Normalized:
        lot = self.lot(payload, fetched_at)
        bid, count, ends = lot.get("current_bid"), lot.get("bid_count"), lot.get("closes_at")
        bid = bid if isinstance(bid, float) else None
        count = count if isinstance(count, int) else None
        ends = None if ends == UNKNOWN else ends
        price = {"currency": "USD", "type": "auction_current" if bid else "starting_bid"}   # no premium: UNKNOWN
        if bid:
            price["amount"] = bid
        loc = lot.get("location") if isinstance(lot.get("location"), dict) else {}
        n: dict = {"title": lot.get("title"), "condition": "used", "price": price,
                   "counterparty": {"role": "agency", "contact_method": "gov_poc",
                                    **({"name": lot.get("agency")} if lot.get("agency") != UNKNOWN else {})},
                   "listing_status": "active", "images": []}
        desc = _text(lot.get("lot_info")) if lot.get("lot_info") != UNKNOWN else ""
        if desc:
            n["description"] = desc
        if ends:
            n["ends_at"] = ends
        if count is not None:
            n["bid_count"] = count
        if loc:
            n["location"] = {**loc, **({"geo_tier": geo_tier(lot.distance_miles)} if lot.distance_miles is not None else {})}
        category = lot.get("category")
        flags = base_flags(price=price, bid_count=count, ends_at=ends, fetched_at=fetched_at,
                           matched=category != "other_asset", tier=None, texts=(lot.get("title"), desc))
        if any(x.stale for x in lot.fields.values() if x.value != UNKNOWN):
            flags = sorted(set(flags) | {"needs_review"})      # cached file older than 6h
        if flags:
            n["flags"] = flags
        img = lot.get("image_url")
        url = lot.get("rules_url")
        return Normalized(source_listing_id=lot.lot_id, url=url if url != UNKNOWN else f"gsa-auctions://{lot.lot_id}",
                          type="flip", category=category, opportunity_kind="auction_lot", normalized=n,
                          match_hints={"image_urls": [img]} if isinstance(img, str) and img.startswith("https://") else {})
