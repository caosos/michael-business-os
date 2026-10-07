"""Trash Nothing API adapter — flip lane (free items), ADR-02-0202 tier 1 (official API, read-only). B-03.

Endpoint (trashnothing.com/api/v1.4/trashnothing-openapi.yaml, read 2026-10-07):
    GET https://trashnothing.com/api/v1.4/posts?types=offer&sources=groups,trashnothing
        &latitude=..&longitude=..&radius=<meters, <= 80500>&per_page=<=100&page=N&api_key=KEY
Response: {"posts": [Post], "num_posts", "page", "per_page", "num_pages", ...};
Post = {post_id, source, group_id, user_id, title, content, date, type, outcome, latitude, longitude,
        footer, photos, expiration, reselling, url, repost_count}.

* Only `offer` posts are requested. `outcome` set (satisfied/withdrawn) → listing_status `gone`.
* The spec puts `api_key` in the query string, so the URL recorded in provenance is the redacted one.
  `user_id` and `footer` stay in the raw artifact only; they never reach the Item.
* **No live call without explicit enablement** (`live=True`); key from `TRASHNOTHING_API_KEY`.
* Policy note (RECOMMENDATION, for Michael — not decided here): items are gifts from community groups,
  and some groups' rules forbid taking items to resell. Trash Nothing's own Terms restrict redistributing
  *content*, not reselling items (read 2026-10-07). Discovery is read-only either way; whether to act on
  free-item flips is a business-policy question, so these Items are flagged `needs_review`.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from ..adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..canonical import CanonicalError, raw_json_bytes
from ..http import (CallbackTransport, HttpResponse, ReadOnlyTransport, Transport, TransportError, UrllibTransport,
                    redact, status_error)
from ..normalize import (HOME_BASE, MAX_DESCRIPTION, base_flags, classify, clean_text, geo_tier, haversine_miles,
                         match_text)

HOST = "trashnothing.com"
BASE = f"https://{HOST}/api/v1.4/posts"
MAX_RADIUS_M = 80500
_PREFIX = re.compile(r"^\s*(offer|offered|free)\s*[:\-–]\s*", re.IGNORECASE)
_LOC_SUFFIX = re.compile(r"\s*\([^()]*\)\s*$")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TrashNothingAdapter(SourceAdapter):
    source = "trashnothing"
    ingestion_method = "api"
    tos_risk = "low"
    access_tier = 1
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, api_key: str | None, *, live: bool = False, transport: Transport | None = None,
                 center: tuple[float, float] = HOME_BASE, clock: Callable[[], datetime] = _utcnow) -> None:
        self.api_key, self.live, self.center, self.clock = api_key, live, center, clock
        self.http = ReadOnlyTransport(transport or UrllibTransport(), frozenset({HOST}))

    @classmethod
    def from_env(cls, environ, *, live: bool = False, **kw) -> "TrashNothingAdapter":
        return cls(environ.get("TRASHNOTHING_API_KEY"), live=live, **kw)

    @classmethod
    def from_fixture(cls, fixture_dir: str | Path, clock: Callable[[], datetime] = _utcnow) -> "TrashNothingAdapter":
        d = Path(fixture_dir)

        def handler(method, url, headers, body):
            page = parse_qs(urlsplit(url).query).get("page", ["1"])[0]
            f = d / f"posts-page{page}.json"
            return HttpResponse(200, f.read_bytes() if f.exists() else b'{"posts":[],"num_pages":1}')

        return cls("fixture-key", live=True, transport=CallbackTransport(handler), clock=clock)

    def _url(self, profile: SearchProfile, page: int) -> str:
        params = {"types": "offer", "sources": "groups,trashnothing", "sort_by": "date",
                  "latitude": f"{self.center[0]:.4f}", "longitude": f"{self.center[1]:.4f}",
                  "radius": str(min(int(profile.radius_miles * 1609.344), MAX_RADIUS_M)),
                  "per_page": str(min(max(profile.limit, 1), 100)), "page": str(page),
                  "api_key": self.api_key or ""}
        return f"{BASE}?{urlencode(params)}"

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        if not self.live:
            res.error = SourceError("config", "live Trash Nothing calls not enabled for this profile (set live = true)")
            return res
        if not self.api_key:
            res.error = SourceError("config", "TRASHNOTHING_API_KEY not set")
            return res
        page, pages = 1, 1
        while page <= min(pages, profile.max_pages):
            url = self._url(profile, page)
            public = redact(url)
            try:
                r = self.http.request("GET", url, {"Accept": "application/json"})
            except TransportError as e:
                res.error, res.records = SourceError("network", str(e)), []
                return res
            res.requests_made += 1
            err = status_error(r, "Trash Nothing")
            if err:
                res.error, res.records = err, []
                return res
            try:
                data = json.loads(r.body)
                posts = data["posts"]
                if not isinstance(posts, list):
                    raise ValueError("posts is not a list")
                pages = int(data.get("num_pages") or 1)
            except (ValueError, KeyError, TypeError) as e:
                res.error, res.records = SourceError("parse", f"Trash Nothing response malformed: {e}", r.status), []
                return res
            fetched_at = self.clock()
            for post in posts:
                try:
                    res.records.append(RawRecord(raw_json_bytes(post), post, fetched_at, public))
                except CanonicalError:
                    res.records.append(RawRecord(json.dumps(post).encode(), None, fetched_at, public))
            page += 1
        return res

    def normalize(self, post: dict, fetched_at: datetime) -> Normalized:
        if not isinstance(post, dict) or not post.get("post_id") or not post.get("title"):
            raise NormalizationError("Trash Nothing post missing post_id/title")
        if post.get("type") not in (None, "offer"):
            raise NormalizationError(f"not an offer post (type={post.get('type')!r})")
        raw_title = clean_text(post["title"], 300)
        title = _LOC_SUFFIX.sub("", _PREFIX.sub("", raw_title)) or raw_title
        desc = clean_text(post.get("content"), MAX_DESCRIPTION)
        category, matched = classify("flip", match_text(title), match_text(title, desc))

        price = {"amount": 0, "currency": "USD", "type": "free"}
        location, tier = {}, None
        lat, lng = post.get("latitude"), post.get("longitude")
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            location = {"lat": round(float(lat), 4), "lng": round(float(lng), 4)}
            tier = geo_tier(haversine_miles(self.center, (float(lat), float(lng))))
            location["geo_tier"] = tier
        normalized = {
            "title": title,
            "condition": "used",
            "price": price,
            "counterparty": {"role": "other", "contact_method": "platform"},
            "listing_status": "gone" if post.get("outcome") else "active",
            "images": [],
        }
        if desc:
            normalized["description"] = desc
        if location:
            normalized["location"] = location
        flags = set(base_flags(price=price, bid_count=None, ends_at=None, fetched_at=fetched_at, matched=matched,
                               tier=tier, texts=(raw_title, desc, clean_text(post.get("footer")))))
        flags.add("needs_review")          # gift-economy reselling norms: business-policy review (see module doc)
        normalized["flags"] = sorted(flags)
        url = clean_text(post.get("url")) or f"trashnothing://post/{clean_text(post['post_id'])}"   # no guessed web URL
        return Normalized(source_listing_id=clean_text(post["post_id"]), url=url, type="flip", category=category,
                          opportunity_kind="free_item", normalized=normalized)
