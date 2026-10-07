"""GSA Auctions API adapter — flip lane, ADR-02-0202 tier 1 (official federal API, read-only). READY_QUEUE B-03.

Endpoint (gsa.github.io/auctions_api/openapi.yaml, read 2026-10-07):
    GET https://api.gsa.gov/assets/gsaauctions/v2/auctions?format=JSON   header X-API-KEY: <api.data.gov key>
Response: {"results": [ {SaleNo, LotNo, ItemName, AucStartDt, AucEndDt, AuctionStatus, PropertyCity,
PropertyState, PropertyZip, BiddersCount, HighBidAmount, Reserve, AucIncrement, ItemDescURL, ImageURL,
LotInfo:[{LotSequence, LotDescript}], AgencyName, ContractOfficer, COEmail, COPhone, ...} ]}

* The API has no geographic filter, so lots are kept client-side by `states` (default: AR and its neighbours).
  Distance stays economic: a neighbouring-state lot is kept and flagged by RESEARCH, not dropped here.
* **No live call without explicit enablement:** `live=True` must be passed (CLI: `live = true` in the profile).
  The key comes from `GSA_API_KEY` and travels in a header, never in a URL, so it cannot reach provenance.
* Fixture mode runs the same parse/normalize code on hand-built responses (shaped from the documented
  schema; not recorded live — UNKNOWN until first live call: exact JSON types of LotNo/PropertyZip/amounts).
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..canonical import CanonicalError, raw_json_bytes
from ..http import (CallbackTransport, HttpResponse, ReadOnlyTransport, Transport, TransportError, UrllibTransport,
                    status_error)
from ..normalize import MAX_DESCRIPTION, base_flags, classify, clean_text, match_text, money

HOST = "api.gsa.gov"
URL = f"https://{HOST}/assets/gsaauctions/v2/auctions?format=JSON"
DEFAULT_STATES = frozenset({"AR", "MO", "TN", "MS", "LA", "TX", "OK"})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class GsaAuctionsAdapter(SourceAdapter):
    source = "gsa_auctions"
    ingestion_method = "api"
    tos_risk = "low"
    access_tier = 1
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, api_key: str | None, *, live: bool = False, transport: Transport | None = None,
                 states: frozenset[str] = DEFAULT_STATES, clock: Callable[[], datetime] = _utcnow) -> None:
        self.api_key, self.live, self.states, self.clock = api_key, live, frozenset(states), clock
        self.http = ReadOnlyTransport(transport or UrllibTransport(), frozenset({HOST}))

    @classmethod
    def from_env(cls, environ, *, live: bool = False, **kw) -> "GsaAuctionsAdapter":
        return cls(environ.get("GSA_API_KEY"), live=live, **kw)

    @classmethod
    def from_fixture(cls, fixture_dir: str | Path, clock: Callable[[], datetime] = _utcnow, **kw) -> "GsaAuctionsAdapter":
        body = (Path(fixture_dir) / "auctions.json").read_bytes()
        return cls("fixture-key", live=True, transport=CallbackTransport(lambda *a: HttpResponse(200, body)),
                   clock=clock, **kw)

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        if not self.live:
            res.error = SourceError("config", "live GSA calls not enabled for this profile (set live = true)")
            return res
        if not self.api_key:
            res.error = SourceError("config", "GSA_API_KEY not set (free key from api.data.gov)")
            return res
        try:
            r = self.http.request("GET", URL, {"X-API-KEY": self.api_key, "Accept": "application/json"})
        except TransportError as e:
            res.error = SourceError("network", str(e))
            return res
        res.requests_made = 1
        err = status_error(r, "GSA Auctions")
        if err:
            res.error = err
            return res
        try:
            data = json.loads(r.body)
            lots = data["results"] if isinstance(data, dict) else None
            if not isinstance(lots, list):
                raise ValueError("no results[] array")
        except (ValueError, KeyError) as e:
            res.error = SourceError("parse", f"GSA response malformed: {e}", r.status)
            return res
        fetched_at = self.clock()
        words = [k.lower() for k in profile.keywords]
        for lot in lots:
            if not isinstance(lot, dict):
                res.records.append(RawRecord(json.dumps(lot).encode(), None, fetched_at, URL))
                continue
            if str(lot.get("PropertyState") or "").strip().upper() not in self.states:
                continue
            if words and not any(w in str(lot.get("ItemName", "")).lower() for w in words):
                continue
            try:
                res.records.append(RawRecord(raw_json_bytes(lot), lot, fetched_at, URL))
            except CanonicalError:
                res.records.append(RawRecord(json.dumps(lot).encode(), None, fetched_at, URL))
        return res

    def normalize(self, lot: dict, fetched_at: datetime) -> Normalized:
        if not isinstance(lot, dict) or not lot.get("SaleNo") or lot.get("LotNo") in (None, "") or not lot.get("ItemName"):
            raise NormalizationError("GSA lot missing SaleNo/LotNo/ItemName")
        sale, lot_no = clean_text(lot["SaleNo"]), clean_text(lot["LotNo"])
        title = clean_text(lot["ItemName"], 300)
        desc = clean_text(" ".join(clean_text(li.get("LotDescript")) for li in sorted(
            (x for x in lot.get("LotInfo") or [] if isinstance(x, dict)),
            key=lambda x: int(x.get("LotSequence") or 0) if str(x.get("LotSequence") or "0").isdigit() else 0)),
            MAX_DESCRIPTION)
        category, matched = classify("flip", match_text(title), match_text(title, desc))

        high = money(lot.get("HighBidAmount"))
        bidders = lot.get("BiddersCount")
        bid_count = int(bidders) if str(bidders).strip().isdigit() else None
        price = ({"amount": high, "currency": "USD", "type": "auction_current", "buyer_premium_pct": 0}
                 if high else {"currency": "USD", "type": "starting_bid", "buyer_premium_pct": 0})
        # AucEndDt is a date only (ISO 8601, UTC). INFERENCE: end-of-day UTC is an upper bound; the real close
        # also depends on InactivityTime. RESEARCH must confirm before any bid decision.
        end = str(lot.get("AucEndDt") or "").strip()[:10]
        ends_at = f"{end}T23:59:59Z" if len(end) == 10 and end[4] == "-" else None

        zip_raw = "".join(ch for ch in str(lot.get("PropertyZip") or "") if ch.isdigit())
        location = {k: v for k, v in {
            "city": clean_text(lot.get("PropertyCity")).title() or None,
            "state": clean_text(lot.get("PropertyState")).upper() or None,
            "zip": zip_raw[:5].zfill(5) if zip_raw else None,
        }.items() if v}
        counterparty = {"role": "agency", "contact_method": "gov_poc"}
        if lot.get("AgencyName"):
            counterparty["name"] = clean_text(lot["AgencyName"], 100)

        normalized = {"title": title, "condition": "used", "price": price, "counterparty": counterparty,
                      "listing_status": "active", "images": []}
        if desc:
            normalized["description"] = desc
        if ends_at:
            normalized["ends_at"] = ends_at
        if bid_count is not None:
            normalized["bid_count"] = bid_count
        if location:
            normalized["location"] = location
        flags = base_flags(price=price, bid_count=bid_count, ends_at=ends_at, fetched_at=fetched_at,
                           matched=matched, tier=None, texts=(title, desc))
        if flags:
            normalized["flags"] = flags
        url = clean_text(lot.get("ItemDescURL")) or f"gsa-auctions://{sale}/{lot_no}"   # no guessed web URL
        return Normalized(source_listing_id=f"{sale}-{lot_no}", url=url, type="flip", category=category,
                          opportunity_kind="auction_lot", normalized=normalized)
