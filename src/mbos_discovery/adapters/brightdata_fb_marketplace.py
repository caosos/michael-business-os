"""Facebook Marketplace via the Bright Data Scraper API: owner-accepted provider route (b). B-43.

Owner chose route (b) on 2026-10-12 (docs/handoff/B42_FACEBOOK_MARKETPLACE_ROUTES.md on lane 07, 632947d).
Meta has NOT given us permission; every record is labelled `SOURCE_COMPLIANCE` and flagged `needs_review`.

Bright Data API (docs.brightdata.com, read 2026-10-12):
    POST https://api.brightdata.com/datasets/v3/scrape?dataset_id=gd_lvt9iwuh6fbcwmx1a   Authorization: Bearer <token>
    * async: a slow /scrape answers HTTP 202 {"snapshot_id"}; poll GET /datasets/v3/progress/<id> ("running" ->
      "ready" | "failed") with back-off up to WAIT_CAP_S, then GET /datasets/v3/snapshot/<id>?format=json.
    * discovery:  &type=discover_new&discover_by=keyword&limit_per_input=N
                  body {"input": [{"keyword", "city", "radius", "date_listed"?}]}  -> rows with only "url"
    * by URL:     body {"input": [{"url": ".../marketplace/item/<id>"}]}  -> full listing records
    Record fields: url, title, description, initial_price, final_price, currency, product_id, condition, brand,
    color, location, country_code, images, videos, listing_date, plus seller fields (seller_description, profile_id).
    UNKNOWN until the live smoke: the exact `city` spelling accepted, whether `radius` is honoured, async (202) use.

* Seller name/profile fields are DROPPED in `fetch`, before the raw bytes are hashed or stored.
* The token is read from a 0600 file at call time, never logged, never in an exception, URL or `repr`.
* Hard cap of HARD_CAP records per fetch (smoke limit), applied to discovery and to output.
* **No live call without `live=True`.**
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..canonical import CanonicalError, raw_json_bytes
from ..http import (CallbackTransport, HttpResponse, ReadOnlyTransport, Transport, TransportError, UrllibTransport,
                    status_error)
from ..normalize import (HOME_BASE, MAX_DESCRIPTION, base_flags, classify, clean_text, geo_tier, haversine_miles,
                         match_text)

HOST = "api.brightdata.com"
SCRAPE_URL = f"https://{HOST}/datasets/v3/scrape"
DATASET_ID = "gd_lvt9iwuh6fbcwmx1a"
PROGRESS_URL = f"https://{HOST}/datasets/v3/progress/"
SNAPSHOT_URL = f"https://{HOST}/datasets/v3/snapshot/"
HARD_CAP = 20
WAIT_CAP_S = 300.0                               # total wait for an async (202) snapshot
BACKOFF_S = (5.0, 10.0, 20.0, 30.0)              # then 30 s
TOKEN_FILE = Path("~/.config/mbos/secrets/BRIGHTDATA_TOKEN")
SOURCE_COMPLIANCE = "UNKNOWN (no Meta permission; owner-accepted provider route)"
# Seller / profile fields never stored (B-42: drop at ingest). Matched on the lower-cased key.
_SELLER_KEY = re.compile(r"seller|profile|owner|user_?name|user_?id|poster|vendor|contact", re.IGNORECASE)
_ITEM_ID = re.compile(r"/marketplace/item/(\d+)")
_CITY_STATE = re.compile(r"^\s*([^,]+?)\s*,\s*([A-Za-z]{2})\b")
_CONDITIONS = (("new", "new"), ("like new", "used"), ("used", "used"), ("good", "used"), ("fair", "used"),
               ("parts", "parts"), ("salvage", "parts"))


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def read_token(path: str | Path = TOKEN_FILE) -> str | None:
    try:
        return Path(path).expanduser().read_text().strip() or None
    except OSError:
        return None


def strip_seller(record: dict) -> dict:
    return {k: v for k, v in record.items() if not _SELLER_KEY.search(str(k))}


def _num(v) -> float | None:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"\d[\d,]*(?:\.\d+)?", v)
        if m:
            return float(m.group(0).replace(",", ""))
    return None


class BrightDataFbMarketplaceAdapter(SourceAdapter):
    source = "brightdata_fb"
    ingestion_method = "api"
    tos_risk = "high"
    access_tier = 4
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, token: str | None = None, *, live: bool = False, transport: Transport | None = None,
                 token_file: str | Path = TOKEN_FILE, city: str = "Conway, AR", center: tuple[float, float] = HOME_BASE,
                 clock: Callable[[], datetime] = _utcnow, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic) -> None:
        self._token = token.strip() if token else None
        self._sleep, self._mono = sleep, monotonic
        self._token_file, self.live, self.city, self.center, self.clock = token_file, live, city, center, clock
        self.http = ReadOnlyTransport(transport or UrllibTransport(), frozenset({HOST}),
                                      frozenset({SCRAPE_URL}))
        self.last_cost: str | None = None        # cost text the provider returned, if any (header), for the receipt

    def __repr__(self) -> str:
        return f"BrightDataFbMarketplaceAdapter(live={self.live})"

    @classmethod
    def from_fixture(cls, fixture_dir: str | Path, clock: Callable[[], datetime] = _utcnow
                     ) -> "BrightDataFbMarketplaceAdapter":
        d = Path(fixture_dir)

        def handler(method, url, headers, body):
            name = "discover.json" if "discover_new" in url else "listings.json"
            return HttpResponse(200, (d / name).read_bytes())

        return cls("fixture-token", live=True, transport=CallbackTransport(handler), clock=clock)

    # ------------------------------------------------------------------ fetch
    def _scrub(self, text: str, token: str | None) -> str:
        return text.replace(token, "[redacted]") if token else text

    def _post(self, token: str, query: str, inputs: list[dict]) -> HttpResponse:
        url = f"{SCRAPE_URL}?dataset_id={DATASET_ID}&include_errors=true{query}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                   "Accept": "application/json"}
        return self.http.request("POST", url, headers, json.dumps({"input": inputs}).encode(), timeout=120.0)

    def _resolve(self, token: str, r: HttpResponse, res: FetchResult) -> HttpResponse:
        """A 202 carries a snapshot id: poll progress with back-off (cap WAIT_CAP_S), then fetch the snapshot."""
        if r.status != 202:
            return r
        try:
            sid = str(json.loads(r.body.decode("utf-8", "replace")).get("snapshot_id") or "")
        except (ValueError, AttributeError):
            sid = ""
        if not re.fullmatch(r"[A-Za-z0-9_\-]{3,64}", sid):
            return HttpResponse(502, b"")          # 202 without a usable snapshot id -> http error
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        start, n = self._mono(), 0
        while True:
            p = self.http.request("GET", PROGRESS_URL + sid, headers, None, timeout=60.0)
            res.requests_made += 1
            if p.status != 200:
                return p
            try:
                status = str(json.loads(p.body.decode("utf-8", "replace")).get("status", "")).lower()
            except (ValueError, AttributeError):
                status = ""
            if status == "ready":
                break
            if status in ("failed", "error", "canceled", "cancelled"):
                return HttpResponse(502, b"")
            delay = BACKOFF_S[min(n, len(BACKOFF_S) - 1)]
            n += 1
            if self._mono() - start + delay > WAIT_CAP_S:
                return HttpResponse(504, b"")      # wait cap reached
            self._sleep(delay)
        snap = self.http.request("GET", f"{SNAPSHOT_URL}{sid}?format=json", headers, None, timeout=120.0)
        res.requests_made += 1
        cost = snap.headers.get("x-cost") or r.headers.get("x-cost")
        return HttpResponse(snap.status, snap.body, {**snap.headers, **({"x-cost": cost} if cost else {})})

    @staticmethod
    def _rows(body: bytes) -> list[dict]:
        text = body.decode("utf-8", "replace").strip()
        try:
            data = json.loads(text)
        except ValueError:                        # NDJSON is the provider default
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        if isinstance(data, dict):
            data = data.get("data") if isinstance(data.get("data"), list) else [data]
        if not isinstance(data, list):
            raise ValueError("response is not a list of records")
        return [r for r in data if isinstance(r, dict)]

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        if not self.live:
            res.error = SourceError("config", "live Bright Data calls not enabled for this profile (set live = true)")
            return res
        token = self._token or read_token(self._token_file)
        if not token:
            res.error = SourceError("config", "Bright Data token file missing or empty")
            return res
        cap = min(max(profile.limit, 1), HARD_CAP)
        keyword = " ".join(profile.keywords[:1]).strip()
        if not keyword:
            res.error = SourceError("config", "no keyword in profile")
            return res
        inputs = [{"keyword": keyword, "city": self.city, "radius": int(profile.radius_miles)}]
        uri = f"{SCRAPE_URL}?dataset_id={DATASET_ID}"
        try:
            r = self._post(token, f"&type=discover_new&discover_by=keyword&limit_per_input={cap}", inputs)
            res.requests_made += 1
            r = self._resolve(token, r, res)
            err = self._error(r, token)
            if err:
                res.error = err
                return res
            found = self._rows(r.body)[:cap]
            full = [x for x in found if x.get("title")]
            urls = [{"url": x["url"]} for x in found if not x.get("title") and isinstance(x.get("url"), str)]
            if urls:
                r2 = self._post(token, "&limit_per_input=1", urls[:cap])
                res.requests_made += 1
                r2 = self._resolve(token, r2, res)
                err = self._error(r2, token)
                if err:
                    res.error = err
                    return res
                full += self._rows(r2.body)
                self.last_cost = r2.headers.get("x-cost") or r.headers.get("x-cost")
            else:
                self.last_cost = r.headers.get("x-cost")
        except TransportError as e:
            res.error = SourceError("network", self._scrub(str(e), token))
            return res
        except (ValueError, TypeError) as e:
            res.error = SourceError("parse", self._scrub(f"Bright Data response malformed: {e}", token))
            return res
        fetched_at = self.clock()
        for row in full[:cap]:
            if row.get("error") and not row.get("title"):
                continue                           # provider error row, not a listing
            rec = {**strip_seller(row), "source_compliance": SOURCE_COMPLIANCE}
            try:
                res.records.append(RawRecord(raw_json_bytes(rec), rec, fetched_at, uri))
            except CanonicalError:
                res.records.append(RawRecord(json.dumps(rec, default=str).encode(), None, fetched_at, uri))
        return res

    def _error(self, r: HttpResponse, token: str) -> SourceError | None:
        if r.status == 504:
            return SourceError("network", "Bright Data snapshot not ready within the wait cap", 504)
        if r.status == 401:
            return SourceError("auth", "Bright Data rejected the token (401)", 401)
        err = status_error(r, "Bright Data")
        if err:
            return SourceError(err.kind, self._scrub(err.message, token), err.status)
        return None

    # -------------------------------------------------------------- normalize
    def normalize(self, rec: dict, fetched_at: datetime) -> Normalized:
        if not isinstance(rec, dict) or not rec.get("title"):
            raise NormalizationError("Bright Data Marketplace record missing title")
        url = clean_text(rec.get("url"))
        pid = clean_text(rec.get("product_id")) or (_ITEM_ID.search(url).group(1) if _ITEM_ID.search(url) else "")
        if not pid:
            raise NormalizationError("Bright Data Marketplace record missing product_id")
        title = clean_text(rec["title"], 300)
        desc = clean_text(rec.get("description"), MAX_DESCRIPTION)
        category, matched = classify("flip", match_text(title), match_text(title, desc))

        amount = _num(rec.get("final_price"))
        if amount is None:
            amount = _num(rec.get("initial_price"))
        price: dict[str, Any] = {"currency": clean_text(rec.get("currency")) or "USD"}
        if amount is not None:
            price.update(amount=amount, type="free" if amount == 0 else "fixed")

        cond_raw = match_text(rec.get("condition"))
        condition = next((v for k, v in _CONDITIONS if k in cond_raw), "unknown")

        location: dict[str, Any] = {}
        loc = rec.get("location")
        loc_text = clean_text(loc.get("name") or loc.get("text") if isinstance(loc, dict) else loc)
        m = _CITY_STATE.match(loc_text)
        if m:
            location.update(city=m.group(1), state=m.group(2).upper())
        src = loc if isinstance(loc, dict) else rec
        lat, lng = (src.get("latitude", src.get("lat")), src.get("longitude", src.get("lng", src.get("lon"))))
        tier = None
        if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
            location.update(lat=round(float(lat), 4), lng=round(float(lng), 4))
            tier = geo_tier(haversine_miles(self.center, (float(lat), float(lng))))
            location["geo_tier"] = tier

        normalized: dict[str, Any] = {"title": title, "condition": condition, "price": price,
                                      "counterparty": {"role": "seller", "contact_method": "platform"},
                                      "listing_status": "active", "images": []}
        if desc:
            normalized["description"] = desc
        if location:
            normalized["location"] = location
        flags = set(base_flags(price=price if "amount" in price else None, bid_count=None, ends_at=None,
                               fetched_at=fetched_at, matched=matched, tier=tier, texts=(title, desc)))
        flags.add("needs_review")                  # compliance UNKNOWN: every record is reviewed
        normalized["flags"] = sorted(flags)
        imgs = rec.get("images")
        urls = [u for u in imgs if isinstance(u, str) and u.startswith("https://")] if isinstance(imgs, list) else []
        hints: dict[str, Any] = {"source_compliance": SOURCE_COMPLIANCE}
        if rec.get("listing_date"):
            hints["listing_date"] = clean_text(rec["listing_date"])
        if urls:
            hints["image_urls"] = urls
        return Normalized(source_listing_id=pid, url=url or f"https://www.facebook.com/marketplace/item/{pid}",
                          type="flip", category=category, opportunity_kind="buy_item",
                          normalized=normalized, match_hints=hints)
