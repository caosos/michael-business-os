"""NHTSA recalls and consumer complaints by vehicle — `project_vehicle` knowledge. READY_QUEUE B-17 (ADR-02-0202 tier 1).

FACT (confirmed on the live API 2026-10-07 with one read-only GET per endpoint, plus the field list below):
    GET https://api.nhtsa.gov/recalls/recallsByVehicle?make=<m>&model=<m>&modelYear=<y>
        → {"Count", "Message", "results": [{Manufacturer, NHTSACampaignNumber, NHTSAActionNumber,
           ReportReceivedDate ("MM/DD/YYYY"), ModelYear, Make, Model, Component, Summary, Consequence, Remedy, Notes,
           parkIt, parkOutSide, overTheAirUpdate}]}
    GET https://api.nhtsa.gov/complaints/complaintsByVehicle?make=<m>&model=<m>&modelYear=<y>
        → {"count", "message", "results": [{odiNumber, manufacturer, crash, fire, numberOfInjuries, numberOfDeaths,
           dateOfIncident, dateComplaintFiled, vin (partial), components, summary, products[…]}]}
    (Note the key-case difference: Count/Message vs count/message.)
UNKNOWN: rate limits and terms (nothing stated on the responses; the documentation page returns 403 to a plain
fetcher). So: queries are explicit and few, 429/403 → the shared block freeze, and live use needs `live=True`.
Not covered here: technical service bulletins (downloadable files, not an API), per 03's source plan.

Queries are EXPLICIT (make, model, year) — never parsed out of listing text, because a guessed make/model/year would
put a recall on the wrong vehicle. Retention: each recall is its own raw record; a complaints response is retained
whole per query (consumer narratives and partial VINs stay in raw and never reach an entry).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from ..adapter import FetchResult, NormalizationError, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..canonical import CanonicalError, raw_json_bytes
from ..http import (CallbackTransport, HttpResponse, ReadOnlyTransport, Transport, TransportError, UrllibTransport,
                    status_error)

HOST = "api.nhtsa.gov"
RECALLS = f"https://{HOST}/recalls/recallsByVehicle"
COMPLAINTS = f"https://{HOST}/complaints/complaintsByVehicle"
MAX_VEHICLES = 25
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 \-./]{0,39}$")


@dataclass(frozen=True)
class VehicleQuery:
    make: str
    model: str
    year: int

    def __post_init__(self) -> None:
        if not (_NAME.match(self.make) and _NAME.match(self.model) and 1950 <= int(self.year) <= datetime.now().year + 2):
            raise ValueError(f"invalid vehicle query {self!r}")

    @property
    def label(self) -> str:
        return f"{self.year} {self.make} {self.model}"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


class NhtsaAdapter(SourceAdapter):
    """Fetches recalls (one raw record each) and complaints (one raw record per query) for explicit vehicles."""
    source = "nhtsa"
    ingestion_method = "api"
    tos_risk = "low"
    access_tier = 1
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, vehicles: list[VehicleQuery], *, live: bool = False, transport: Transport | None = None,
                 include_complaints: bool = True, clock: Callable[[], datetime] = _utcnow) -> None:
        self.vehicles = list(vehicles)[:MAX_VEHICLES]
        self.live, self.include_complaints, self.clock = live, include_complaints, clock
        self.http = ReadOnlyTransport(transport or UrllibTransport(), frozenset({HOST}))

    @classmethod
    def from_fixture(cls, fixture_dir: str | Path, vehicles: list[VehicleQuery], clock=_utcnow, **kw) -> "NhtsaAdapter":
        d = Path(fixture_dir)

        def handler(method, url, headers, body):
            u = urlsplit(url)
            q = parse_qs(u.query)
            kind = "recalls" if "recalls" in u.path else "complaints"
            name = "-".join([kind, _slug(q["make"][0]), _slug(q["model"][0]), q["modelYear"][0]])
            f = d / f"{name}.json"
            empty = b'{"Count":0,"Message":"ok","results":[]}'
            return HttpResponse(200, f.read_bytes() if f.exists() else empty)

        return cls(vehicles, live=True, transport=CallbackTransport(handler), clock=clock, **kw)

    @staticmethod
    def url(endpoint: str, v: VehicleQuery) -> str:
        base = RECALLS if endpoint == "recalls" else COMPLAINTS
        return f"{base}?{urlencode({'make': v.make, 'model': v.model, 'modelYear': str(v.year)})}"

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        if not self.live:
            res.error = SourceError("config", "live NHTSA calls not enabled for this profile (set live = true)")
            return res
        now = self.clock()
        for v in self.vehicles:
            for endpoint in ("recalls",) + (("complaints",) if self.include_complaints else ()):
                url = self.url(endpoint, v)
                try:
                    r = self.http.request("GET", url, {"Accept": "application/json"})
                except TransportError as e:
                    res.error, res.records = SourceError("network", str(e)), []
                    return res
                res.requests_made += 1
                err = status_error(r, "NHTSA")
                if err:
                    res.error, res.records = err, []
                    return res
                try:
                    data = json.loads(r.body)
                    results = data.get("results")
                    if not isinstance(results, list):
                        raise ValueError("no results[] array")
                except (ValueError, AttributeError) as e:
                    res.error, res.records = SourceError("parse", f"NHTSA response malformed: {e}", r.status), []
                    return res
                query = {"make": v.make, "model": v.model, "year": v.year}
                payloads = ([{"endpoint": endpoint, "query": query, "url": url, "record": rec} for rec in results]
                            if endpoint == "recalls" else
                            [{"endpoint": endpoint, "query": query, "url": url, "results": results}])
                for p in payloads:
                    try:
                        res.records.append(RawRecord(raw_json_bytes(p), p, now, url))
                    except CanonicalError:
                        res.records.append(RawRecord(json.dumps(p).encode(), None, now, url))
        return res

    def normalize(self, payload, fetched_at):               # pragma: no cover — knowledge source
        raise NormalizationError("nhtsa records are knowledge evidence, not Items; use vehicle_safety.collect")

