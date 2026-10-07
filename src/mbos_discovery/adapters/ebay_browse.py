"""eBay Browse API adapter — flip lane, ADR-02-0202 tier 1 (official API, read-only).

Live path: OAuth2 client-credentials (application token, scope `api_scope`) then
GET /buy/browse/v1/item_summary/search with used-condition + local-pickup-radius filters
around Conway (72034). Credentials come from the environment:

    EBAY_CLIENT_ID, EBAY_CLIENT_SECRET, EBAY_ENV=production|sandbox

Without credentials the adapter fails *safely* (error kind `config`, zero requests).
`EbayBrowseAdapter.from_fixture(dir)` runs the identical request/parse/normalize code
against recorded responses so the lane is buildable and testable with no account.
See docs/runbooks/ebay-live-credentials.md for the path to live data.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs, urlencode, urlsplit

from ..adapter import (FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile,
                       SourceAdapter, SourceError)
from ..http import (CallbackTransport, HttpResponse, ReadOnlyTransport, Transport, TransportError,
                    UrllibTransport, status_error)
from ..canonical import CanonicalError, raw_json_bytes
from ..normalize import (MAX_DESCRIPTION, base_flags, classify, clean_text, geo_tier, match_text,
                         money, norm_ts)

ENVIRONMENTS = {
    "production": ("api.ebay.com", "https://api.ebay.com/identity/v1/oauth2/token"),
    "sandbox": ("api.sandbox.ebay.com", "https://api.sandbox.ebay.com/identity/v1/oauth2/token"),
}
SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE = "EBAY_US"

# eBay conditionId → contract condition. 1000–1750 new; 2000–6000 refurbished/used; 7000 parts.
def _condition(summary: dict) -> str:
    cid = str(summary.get("conditionId") or "")
    if cid.isdigit():
        c = int(cid)
        if c < 2000:
            return "new"
        if c >= 7000:
            return "parts"
        return "used"
    text = (summary.get("condition") or "").lower()
    if "parts" in text:
        return "parts"
    if "new" in text and "used" not in text:
        return "new"
    if text:
        return "used"
    return "unknown"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EbayBrowseAdapter(SourceAdapter):
    source = "ebay"
    ingestion_method = "api"
    tos_risk = "low"
    access_tier = 1
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, client_id: str | None, client_secret: str | None, env: str = "production",
                 transport: Transport | None = None, clock: Callable[[], datetime] = _utcnow) -> None:
        if env not in ENVIRONMENTS:
            raise ValueError(f"EBAY_ENV must be one of {sorted(ENVIRONMENTS)}")
        self.client_id, self.client_secret, self.env = client_id, client_secret, env
        host, token_url = ENVIRONMENTS[env]
        self.base = f"https://{host}"
        self.token_url = token_url
        self.http = ReadOnlyTransport(transport or UrllibTransport(), frozenset({host}), frozenset({token_url}))
        self.clock = clock
        self.scope = SCOPE
        self.list_key = "itemSummaries"
        self._token: tuple[str, datetime] | None = None

    @classmethod
    def from_env(cls, environ, **kw) -> "EbayBrowseAdapter":
        return cls(environ.get("EBAY_CLIENT_ID"), environ.get("EBAY_CLIENT_SECRET"),
                   environ.get("EBAY_ENV", "production"), **kw)

    @classmethod
    def from_fixture(cls, fixture_dir: str | Path, clock: Callable[[], datetime] = _utcnow) -> "EbayBrowseAdapter":
        """Recorded responses: token.json, and search-<slug(q)>[-offset<N>].json per query page."""
        d = Path(fixture_dir)

        def handler(method, url, headers, body):
            if method == "POST":
                return HttpResponse(200, (d / "token.json").read_bytes())
            qs = parse_qs(urlsplit(url).query)
            name = "search-" + _slug(qs.get("q", [""])[0])
            if qs.get("offset", ["0"])[0] != "0":
                name += "-offset" + qs["offset"][0]
            f = d / f"{name}.json"
            return HttpResponse(200, f.read_bytes() if f.exists() else b'{"total":0,"itemSummaries":[]}')

        return cls("fixture-client", "fixture-secret", "production", CallbackTransport(handler), clock)

    # ---- fetch ---------------------------------------------------------------------
    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        if not (self.client_id and self.client_secret):
            res.error = SourceError("config", "EBAY_CLIENT_ID / EBAY_CLIENT_SECRET not set; "
                                    "see docs/runbooks/ebay-live-credentials.md (or use --fixtures)")
            return res
        seen: set[str] = set()
        for q in profile.keywords or ("",):
            url: str | None = self._search_url(q, profile)
            pages = 0
            while url and pages < profile.max_pages:
                body, err = self._get_json(url, res)
                if err:
                    res.error, res.records = err, []
                    return res
                fetched_at = self.clock()
                for s in body.get(self.list_key) or []:
                    iid = s.get("itemId") if isinstance(s, dict) else None
                    if iid and iid in seen:
                        continue                    # same listing hit by two keywords
                    if iid:
                        seen.add(iid)
                    try:
                        res.records.append(RawRecord(raw_json_bytes(s), s, fetched_at, url))
                    except CanonicalError:      # out of MBOS-CJSON-1 profile: keep bytes, quarantine
                        res.records.append(RawRecord(json.dumps(s).encode(), None, fetched_at, url))
                pages += 1
                nxt = body.get("next")
                url = nxt if nxt and urlsplit(nxt).hostname == urlsplit(self.base).hostname else None
        return res

    def _search_url(self, q: str, p: SearchProfile) -> str:
        filters = [
            "conditions:{USED}",
            "buyingOptions:{FIXED_PRICE|AUCTION|BEST_OFFER}",
            "deliveryOptions:{SELLER_ARRANGED_LOCAL_PICKUP}",
            "pickupCountry:US",
            f"pickupPostalCode:{p.postal_code}",
            f"pickupRadius:{p.radius_miles}",
            "pickupRadiusUnit:mi",
        ]
        if p.max_price is not None:
            filters += [f"price:[..{p.max_price:g}]", "priceCurrency:USD"]
        params = {"q": q, "limit": str(min(max(p.limit, 1), 200)), "offset": "0", "filter": ",".join(filters)}
        return f"{self.base}/buy/browse/v1/item_summary/search?{urlencode(params)}"

    def _get_json(self, url: str, res: FetchResult) -> tuple[dict, SourceError | None]:
        for attempt in (1, 2):
            tok, err = self._bearer(res, force=attempt == 2)
            if err:
                return {}, err
            try:
                r = self.http.request("GET", url, {"Authorization": f"Bearer {tok}",
                                                   "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
                                                   "Accept": "application/json"})
            except TransportError as e:
                return {}, SourceError("network", str(e))
            res.requests_made += 1
            if r.status == 401 and attempt == 1:
                continue                            # token expired early: refresh once
            err = status_error(r, "eBay")
            if err:
                return {}, err
            try:
                data = json.loads(r.body)
                if not isinstance(data, dict):
                    raise ValueError("top-level JSON is not an object")
                return data, None
            except ValueError as e:
                return {}, SourceError("parse", f"search response not JSON: {e}", r.status)
        return {}, SourceError("auth", "401 after token refresh", 401)

    def _bearer(self, res: FetchResult, force: bool = False) -> tuple[str, SourceError | None]:
        now = self.clock()
        if self._token and not force and self._token[1] > now:
            return self._token[0], None
        basic = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        try:
            r = self.http.request("POST", self.token_url,
                                  {"Authorization": f"Basic {basic}",
                                   "Content-Type": "application/x-www-form-urlencoded"},
                                  urlencode({"grant_type": "client_credentials", "scope": self.scope}).encode())
        except TransportError as e:
            return "", SourceError("network", f"token: {e}")
        res.requests_made += 1
        if r.status in (400, 401):
            return "", SourceError("auth", f"token request rejected ({r.status}); check credentials", r.status)
        err = status_error(r, "eBay")
        if err:
            return "", err
        try:
            data = json.loads(r.body)
            token, ttl = data["access_token"], int(data.get("expires_in", 7200))
        except (ValueError, KeyError, TypeError) as e:
            return "", SourceError("parse", f"token response malformed: {e}", r.status)
        self._token = (token, now + timedelta(seconds=max(ttl - 120, 60)))
        return token, None

    # ---- normalize (pure) ----------------------------------------------------------
    def normalize(self, s: dict, fetched_at: datetime) -> Normalized:
        if not isinstance(s, dict) or not s.get("itemId") or not s.get("title"):
            raise NormalizationError("eBay summary missing itemId/title")
        title = clean_text(s["title"], 300)
        desc = clean_text(s.get("shortDescription"), MAX_DESCRIPTION)
        cats = " ".join(c.get("categoryName", "") for c in s.get("categories") or [] if isinstance(c, dict))
        category, matched = classify("flip", match_text(title), match_text(title, cats))

        options = set(s.get("buyingOptions") or [])
        bid_count = s.get("bidCount")
        bid_count = int(bid_count) if isinstance(bid_count, (int, str)) and str(bid_count).isdigit() else None
        if "AUCTION" in options:
            cur = money((s.get("currentBidPrice") or {}).get("value"))
            if cur is not None and (bid_count or 0) > 0:
                price = {"amount": cur, "currency": (s.get("currentBidPrice") or {}).get("currency", "USD"),
                         "type": "auction_current"}
            else:
                amt = money((s.get("price") or s.get("currentBidPrice") or {}).get("value"))
                price = {"amount": amt or 0.0, "currency": "USD", "type": "starting_bid"}
            kind = "auction_lot"
        else:
            amt = money((s.get("price") or {}).get("value"))
            price = {"amount": amt, "currency": (s.get("price") or {}).get("currency", "USD"), "type": "fixed"}
            if amt is None:
                price = {"type": "fixed"}
            kind = "buy_item"
        if price.get("amount") == 0 and kind == "buy_item":
            price["type"] = "free"

        ends_at = norm_ts(s.get("itemEndDate"))
        loc_in = s.get("itemLocation") or {}
        location = {k: v for k, v in {
            "city": clean_text(loc_in.get("city")) or None,
            "state": clean_text(loc_in.get("stateOrProvince")) or None,
            "zip": clean_text(loc_in.get("postalCode")) or None,
        }.items() if v}
        tier = None
        dist = s.get("distanceFromPickupLocation") or {}
        if dist.get("value") is not None:
            miles = float(dist["value"])
            if str(dist.get("unitOfMeasure", "")).upper().startswith("K"):
                miles /= 1.609344
            tier = geo_tier(miles)
            location["geo_tier"] = tier

        seller = s.get("seller") or {}
        counterparty = {"role": "seller", "contact_method": "platform"}
        if seller.get("username"):
            counterparty["name"] = clean_text(seller["username"])
        if seller.get("sellerAccountType"):
            counterparty["is_dealer"] = seller["sellerAccountType"] == "BUSINESS"

        normalized = {
            "title": title,
            "condition": _condition(s),
            "price": price,
            "counterparty": counterparty,
            "listing_status": "active",
            "images": [],               # image URLs stay in raw; sha256 image artifacts are a wave-two item
        }
        if desc:
            normalized["description"] = desc
        if ends_at:
            normalized["ends_at"] = ends_at
        if bid_count is not None:
            normalized["bid_count"] = bid_count
        if location:
            normalized["location"] = location
        flags = base_flags(price=price, bid_count=bid_count, ends_at=ends_at, fetched_at=fetched_at,
                           matched=matched, tier=tier, texts=(title, desc))
        if flags:
            normalized["flags"] = flags

        url = s.get("itemWebUrl") or f"https://www.ebay.com/itm/{s['itemId']}"
        first_cat = next((c.get("categoryName") for c in s.get("categories") or []
                          if isinstance(c, dict) and c.get("categoryName")), None)
        sub = clean_text(first_cat, 120) or None
        return Normalized(source_listing_id=str(s["itemId"]), url=url, type="flip", category=category,
                          opportunity_kind=kind, normalized=normalized, subcategory=sub)


def _slug(q: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", q.lower()).strip("-") or "all"
