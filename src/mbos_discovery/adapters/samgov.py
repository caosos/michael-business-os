"""SAM.gov Get Opportunities v2 — service lane (`gov_contract` leads), ADR-02-0202 tier 1. READY_QUEUE B-07.

FACT (open.gsa.gov/api/get-opportunities-public-api, read 2026-10-07):
    GET https://api.sam.gov/opportunities/v2/search?api_key=KEY&postedFrom=MM/dd/yyyy&postedTo=MM/dd/yyyy
        [&limit<=1000&offset&ptype&state&ncode&zip&rdlfrom&rdlto&typeOfSetAside]
    Response {totalRecords, limit, offset, opportunitiesData[], links}; opportunity fields include noticeId, title,
    solicitationNumber, postedDate, type, baseType, responseDeadLine, naicsCode, active, description, uiLink,
    placeOfPerformance, officeAddress, pointOfContact, award. Daily request limits depend on the account role.

* One request per configured state (Place of Performance), posted in the last `lookback_days`; notice types default
  to solicitations / combined / pre-solicitations / sources-sought (`o,k,p,r`). `g` (sale of surplus property) is a
  possible later FLIP source — not in this task.
* `api_key` must travel in the query (per spec) → every recorded URL is redacted. `description` is a key-requiring
  link and is NOT fetched; points of contact stay in the raw artifact only.
* Category: NAICS first (table below), then service keyword rules, else `other_service` + `needs_review`.
* **No live call without explicit enablement** (`live=True`); key from `SAMGOV_API_KEY`.
* Fixtures are hand-built from the documented fields (UNKNOWN until first live call: nested shapes of
  placeOfPerformance/officeAddress — the adapter accepts {code,name} objects or plain strings).
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
                    redact, status_error)
from ..normalize import base_flags, classify, clean_text, match_text, norm_ts

HOST = "api.sam.gov"
BASE = f"https://{HOST}/opportunities/v2/search"
DEFAULT_PTYPES = "o,k,p,r"

# NAICS → Item v1 service category (exact code first, then 4-digit prefix). INFERENCE: mapping chosen for Michael's
# service lines (ADR-0007); anything else falls to keyword rules / other_service.
NAICS = {
    "811310": "equipment_repair", "811411": "equipment_repair", "811412": "equipment_repair",
    "811210": "technical_service", "811212": "technical_service", "811213": "technical_service",
    "541512": "technical_service", "541513": "technical_service", "541519": "technical_service",
    "811111": "mechanical_service", "811118": "mechanical_service", "811198": "mechanical_service",
    "238310": "drywall_repair",
    "236118": "handyman", "238990": "handyman", "561210": "handyman",
    "238210": "smart_home_install",
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SamGovAdapter(SourceAdapter):
    source = "samgov"
    ingestion_method = "api"
    tos_risk = "low"
    access_tier = 1
    lanes = frozenset({"service"})
    adapter_version = "1.0.0"

    def __init__(self, api_key: str | None, *, live: bool = False, transport: Transport | None = None,
                 states: tuple[str, ...] = ("AR",), lookback_days: int = 14, ptypes: str = DEFAULT_PTYPES,
                 clock: Callable[[], datetime] = _utcnow) -> None:
        self.api_key, self.live, self.states, self.lookback, self.ptypes, self.clock = (
            api_key, live, tuple(states), lookback_days, ptypes, clock)
        self.http = ReadOnlyTransport(transport or UrllibTransport(), frozenset({HOST}))

    @classmethod
    def from_env(cls, environ, *, live: bool = False, **kw) -> "SamGovAdapter":
        return cls(environ.get("SAMGOV_API_KEY"), live=live, **kw)

    @classmethod
    def from_fixture(cls, fixture_dir: str | Path, clock: Callable[[], datetime] = _utcnow, **kw) -> "SamGovAdapter":
        d = Path(fixture_dir)

        def handler(method, url, headers, body):
            st = parse_qs(urlsplit(url).query).get("state", [""])[0]
            f = d / f"opportunities-{st}.json"
            return HttpResponse(200, f.read_bytes() if f.exists() else b'{"totalRecords":0,"opportunitiesData":[]}')

        return cls("fixture-key", live=True, transport=CallbackTransport(handler), clock=clock, **kw)

    def _url(self, state: str, profile: SearchProfile, now: datetime) -> str:
        params = {"api_key": self.api_key or "", "postedFrom": (now - timedelta(days=self.lookback)).strftime("%m/%d/%Y"),
                  "postedTo": now.strftime("%m/%d/%Y"), "ptype": self.ptypes, "state": state,
                  "limit": str(min(max(profile.limit, 1), 1000)), "offset": "0"}
        return f"{BASE}?{urlencode(params)}"

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        if not self.live:
            res.error = SourceError("config", "live SAM.gov calls not enabled for this profile (set live = true)")
            return res
        if not self.api_key:
            res.error = SourceError("config", "SAMGOV_API_KEY not set (free key from SAM.gov account)")
            return res
        now = self.clock()
        for state in self.states:
            url = self._url(state, profile, now)
            try:
                r = self.http.request("GET", url, {"Accept": "application/json"})
            except TransportError as e:
                res.error, res.records = SourceError("network", str(e)), []
                return res
            res.requests_made += 1
            err = status_error(r, "SAM.gov")
            if err:
                res.error, res.records = err, []
                return res
            try:
                data = json.loads(r.body)
                opps = data.get("opportunitiesData")
                if not isinstance(opps, list):
                    raise ValueError("no opportunitiesData[]")
            except (ValueError, AttributeError) as e:
                res.error, res.records = SourceError("parse", f"SAM.gov response malformed: {e}", r.status), []
                return res
            public = redact(url)
            for o in opps:
                try:
                    res.records.append(RawRecord(raw_json_bytes(o), o, now, public))
                except CanonicalError:
                    res.records.append(RawRecord(json.dumps(o).encode(), None, now, public))
        return res

    def normalize(self, o: dict, fetched_at: datetime) -> Normalized:
        if not isinstance(o, dict) or not o.get("noticeId") or not o.get("title"):
            raise NormalizationError("SAM.gov opportunity missing noticeId/title")
        title = clean_text(o["title"], 300)
        naics = clean_text(o.get("naicsCode"))[:6]
        category = NAICS.get(naics)
        matched = category is not None
        if not matched:
            category, matched = classify("service", match_text(title))
        pop = o.get("placeOfPerformance") or {}
        city, state = pop.get("city"), pop.get("state")
        loc = {k: v for k, v in {
            "city": clean_text(city.get("name") if isinstance(city, dict) else city).title(),
            "state": clean_text(state.get("code") if isinstance(state, dict) else state).upper()[:2],
            "zip": clean_text(pop.get("zip"))[:5]}.items() if v}
        deadline = norm_ts(o.get("responseDeadLine"))
        normalized = {
            "title": title,
            "condition": "n/a",
            "price": {"type": "quote_requested"},
            "counterparty": {"role": "agency", "contact_method": "gov_poc"},
            "listing_status": "open" if str(o.get("active", "Yes")).lower() in ("yes", "true", "1") else "closed",
        }
        org = clean_text(o.get("fullParentPathName"), 100)
        if org:
            normalized["counterparty"]["name"] = org
        bits = [f"{clean_text(o.get('type'))}", f"NAICS {naics}" if naics else "",
                f"solicitation {clean_text(o.get('solicitationNumber'))}" if o.get("solicitationNumber") else "",
                f"set-aside {clean_text(o.get('typeOfSetAsideDescription') or o.get('typeOfSetAside'))}"
                if (o.get("typeOfSetAsideDescription") or o.get("typeOfSetAside")) else ""]
        desc = "; ".join(b for b in bits if b)
        if desc:
            normalized["description"] = desc
        if deadline:
            normalized["ends_at"] = deadline
        if loc:
            normalized["location"] = loc
        flags = base_flags(price=normalized["price"], bid_count=None, ends_at=deadline, fetched_at=fetched_at,
                           matched=matched, tier=None, texts=(title, desc))
        if flags:
            normalized["flags"] = flags
        url = clean_text(o.get("uiLink")) or f"samgov://notice/{clean_text(o['noticeId'])}"
        return Normalized(source_listing_id=clean_text(o["noticeId"]), url=url, type="service", category=category,
                          opportunity_kind="gov_contract", normalized=normalized,
                          subcategory=f"NAICS {naics}" if naics else None)
