"""CPSC Recalls Retrieval Web Services — sourced recall records for Agent 03's knowledge base. READY_QUEUE B-16.

FACT (CPSC "Recalls Retrieval Web Services Programmers Guide", v1.3, 2017-10-31, read in full 2026-10-07):
    GET https://www.saferproducts.gov/RestWebServices/Recall?format=json&<param>=<value>…
    Case-insensitive wildcard search on RecallID, RecallNumber, RecallDateStart/End, LastPublishDateStart/End,
    RecallURL, RecallTitle, ConsumerContact, RecallDescription, ProductName, ProductDescription, ProductModel,
    ProductType, InconjunctionURL, ImageURL, Injury, Manufacturer, Retailer, Importer, Distributor,
    ManufacturerCountry, UPC, Hazard, Remedy, RemedyOption. `format` XML|JSON (default XML).
    JSON: a list of recalls; single fields RecallID, RecallNumber, RecallDate ("YYYY-MM-DDT00:00:00"), Description,
    URL, Title, ConsumerContact, LastPublishDate; collections Products[{Name, Description, Model, Type, CategoryID,
    NumberOfUnits}], Manufacturers/Retailers/Importers/Distributors[{Name, CompanyID}], Hazards[{Name, HazardType,
    HazardTypeID}], Remedies[{Name}], RemedyOptions[{Option}], Injuries[{Name}], Images, Inconjunctions,
    ManufacturerCountries, ProductUPCs.
UNKNOWN: any rate limit and any API-key requirement (the guide states neither). So: one request per product-name
query, a small query cap, 429/403 → the shared block freeze. Model/Manufacturers are often EMPTY strings in real
records (the guide's own example has Model ""), which is why the converter is conservative (see recalls.py).

Read-only GET to www.saferproducts.gov only. No live call unless `live=True`. No scraping: only this documented API.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from ..adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..canonical import CanonicalError, raw_json_bytes
from ..http import (CallbackTransport, HttpResponse, ReadOnlyTransport, Transport, TransportError, UrllibTransport,
                    status_error)

HOST = "www.saferproducts.gov"
BASE = f"https://{HOST}/RestWebServices/Recall"
MAX_QUERIES = 12


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class CpscRecallsAdapter(SourceAdapter):
    """Fetches recall records. It is a knowledge source, not an opportunity source: its `normalize` is unused by the
    Item pipeline; `mbos_discovery.recalls.collect_recalls` consumes the raw records."""
    source = "cpsc_recalls"
    ingestion_method = "api"
    tos_risk = "low"
    access_tier = 1
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, *, live: bool = False, transport: Transport | None = None, lookback_days: int = 365 * 3,
                 clock: Callable[[], datetime] = _utcnow) -> None:
        self.live, self.lookback, self.clock = live, lookback_days, clock
        self.http = ReadOnlyTransport(transport or UrllibTransport(), frozenset({HOST}))

    @classmethod
    def from_fixture(cls, fixture_dir: str | Path, clock: Callable[[], datetime] = _utcnow, **kw) -> "CpscRecallsAdapter":
        d = Path(fixture_dir)

        def handler(method, url, headers, body):
            name = parse_qs(urlsplit(url).query).get("ProductName", [""])[0].lower().replace(" ", "-") or "all"
            f = d / f"recalls-{name}.json"
            return HttpResponse(200, f.read_bytes() if f.exists() else b"[]")

        return cls(live=True, transport=CallbackTransport(handler), clock=clock, **kw)

    def _url(self, term: str, now: datetime) -> str:
        p = {"format": "json", "ProductName": term,
             "RecallDateStart": (now - timedelta(days=self.lookback)).strftime("%Y-%m-%d"),
             "RecallDateEnd": now.strftime("%Y-%m-%d")}
        return f"{BASE}?{urlencode(p)}"

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        if not self.live:
            res.error = SourceError("config", "live CPSC calls not enabled for this profile (set live = true)")
            return res
        now = self.clock()
        seen: set[str] = set()
        for term in list(profile.keywords)[:MAX_QUERIES] or [""]:
            url = self._url(term, now)
            try:
                r = self.http.request("GET", url, {"Accept": "application/json"})
            except TransportError as e:
                res.error, res.records = SourceError("network", str(e)), []
                return res
            res.requests_made += 1
            err = status_error(r, "CPSC")
            if err:
                res.error, res.records = err, []
                return res
            try:
                data = json.loads(r.body)
                if not isinstance(data, list):
                    raise ValueError("top-level JSON is not a list of recalls")
            except ValueError as e:
                res.error, res.records = SourceError("parse", f"CPSC response malformed: {e}", r.status), []
                return res
            for rec in data:
                rid = str(rec.get("RecallID")) if isinstance(rec, dict) else None
                if rid and rid in seen:
                    continue
                if rid:
                    seen.add(rid)
                try:
                    res.records.append(RawRecord(raw_json_bytes(rec), rec, now, url))
                except CanonicalError:
                    res.records.append(RawRecord(json.dumps(rec).encode(), None, now, url))
        return res

    def normalize(self, payload, fetched_at):               # pragma: no cover — knowledge source; see recalls.py
        raise NormalizationError("cpsc_recalls records are knowledge evidence, not Items; use recalls.collect_recalls")
