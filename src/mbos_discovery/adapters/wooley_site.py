"""B-26: Wooley Auctioneers auction EVENTS from wooleyauctioneers.com (read-only, AUCTION-EVENT level).

Source boundary (FACT, Agent 01 2026-10-11): lot-level data (lot numbers, current bid, bid count, lot images) lives only on
`wooleyauctioneers.hibid.com`, whose Terms of Use (2022-11-22, s.9) prohibit scraping, extraction, data-mining, aggregation and
screenshots. This module therefore NEVER fetches, parses or screenshots a hibid.com URL: the HiBid catalog link is stored as
text for the human "view/bid on HiBid" button only, and `fetch` refuses any hibid.com host before a request is built.
Lot number, current bid, bid count and lot image are UNKNOWN on every record (NEED: written HiBid permission or a Wooley feed).

Event data comes from Wooley's own site (robots.txt: only /wp-admin/ disallowed, Crawl-delay 10): the current-auctions page
(`/auctions/`, WordPress posts in category `live-auction`) and each auction page linked from it. The source id is the auction
page slug, and the raw payload carries no clock value, so a repeat parse of the same page is byte-identical (same raw_ref).

Live fetch is OFF unless `live=True`; it sends an identifying User-Agent, waits >= 10 s between requests, fetches only
wooleyauctioneers.com pages linked from the current-auctions page, and turns HTTP errors/timeouts into an honest `SourceError`.
Without `live`, `fetch` reads archived pages from `pages_dir` (`auctions.html`, `<slug>.html`) and makes no request.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .. import auctions as A
from ..adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..auctions import UNKNOWN, AuctionLot, Field, place_coords
from ..canonical import raw_json_bytes
from ..http import HttpResponse, ReadOnlyTransport, Transport, TransportError, UrllibTransport, status_error
from ..ids import iso
from ..normalize import HOME_BASE, base_flags, classify, clean_text, geo_tier, haversine_miles, match_text

SOURCE = "wooley_auctioneers"
SITE_HOST = "wooleyauctioneers.com"
LISTING_URL = f"https://{SITE_HOST}/auctions/"
USER_AGENT = "DealSnifferBot/1.0 (read-only; auction events only)"
CRAWL_DELAY_S = 10.0
MAX_EVENTS = 10
LOT_LEVEL_UNKNOWN = ("lot_number", "current_bid", "bid_count", "lot_image")
_CENTRAL = ZoneInfo("America/Chicago")
_FIXED_TZ = {"CDT": timezone(timedelta(hours=-5)), "CST": timezone(timedelta(hours=-6))}
_TAG = re.compile(r"<[^>]+>")
_WHEN = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})\s+at\s+(\d{1,2}):(\d{2})\s*([AP]M)\s*(CDT|CST|CT)\b", re.I)
_CITY_STATE = re.compile(r"([A-Za-z .'-]+?),?\s+(Arkansas|AR)\b", re.I)


class HibidRefused(Exception):
    """A hibid.com URL reached a fetch path. HiBid's Terms of Use forbid automated access."""


def is_hibid(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "hibid.com" or host.endswith(".hibid.com")


def _text(s: str) -> str:
    return clean_text(html.unescape(_TAG.sub(" ", s.replace("<br />", " ").replace("<br>", " "))), 4000)


def parse_when(s: str) -> tuple[str | None, bool]:
    """'10/13/26 at 6:00 PM CDT' -> ('2026-10-13T18:00:00-05:00', exact). 'CT' resolves via America/Chicago (INFERENCE)."""
    m = _WHEN.search(s or "")
    if not m:
        return None, False
    mo, d, y, hh, mm, ap, zone = m.groups()
    y = int(y) + (2000 if int(y) < 100 else 0)
    hh = int(hh) % 12 + (12 if ap.upper() == "PM" else 0)
    zone = zone.upper()
    try:
        naive = datetime(y, int(mo), int(d), hh, int(mm))
    except ValueError:
        return None, False
    dt = naive.replace(tzinfo=_FIXED_TZ[zone] if zone in _FIXED_TZ else _CENTRAL)
    return dt.isoformat(), zone in _FIXED_TZ


def event_category(headline: str | None) -> str | None:
    """Coarse event category from the page headline's first segment: 'Heavy Equipment • Tractors ...' -> 'auction event: heavy equipment'."""
    first = re.split(r"[•|;]", headline or "")[0].strip().lower()
    return f"auction event: {first}" if first else None


def _slug(url: str) -> str:
    return urlsplit(url).path.strip("/").rsplit("/", 1)[-1]


def _site_url(url: str) -> str | None:
    p = urlsplit(url)
    return url if p.scheme == "https" and p.hostname == SITE_HOST and not is_hibid(url) else None


def _event_image_url(value: str) -> str | None:
    """Accept only a first-party HTTPS event-cover URL. This is not a HiBid lot image."""
    try:
        url = html.unescape(value).strip()
        p = urlsplit(url)
        port = p.port
    except (AttributeError, ValueError):
        return None
    return url if p.scheme == "https" and p.hostname == SITE_HOST and p.username is None and p.password is None and port in (None, 443) else None


def parse_listing(page: str) -> list[dict]:
    """Current auctions: <article> posts in category `live-auction`. Past auctions are ignored."""
    events = []
    for block in re.split(r'(?=<article id="post-)', page)[1:]:
        cls = re.match(r'<article id="[^"]*" class="([^"]*)"', block)
        if not cls or "category-live-auction" not in cls.group(1).split():
            continue
        block = block.split("</article>", 1)[0]
        link = re.search(r'<h3 class="title"><a href="([^"]+)">(.*?)</a>', block, re.S)
        url = _site_url(html.unescape(link.group(1))) if link else None
        if not url:
            continue
        cats = [html.unescape(t) for slug, t in re.findall(r'<a class="([^"]+)" href="https://wooleyauctioneers\.com/auctions/[^"]+/">([^<]+)</a>', block)
                if slug != "live-auction"]
        ex = re.search(r'<div class="excerpt">(.*?)</div>', block, re.S)
        image = re.search(r'<span[^>]*class="[^"]*\bpost-featured-img\b[^"]*"[^>]*>\s*<img[^>]*\b(?:data-nectar-img-src|src)="([^"]+)"', block, re.S)
        event = {"url": url, "slug": _slug(url), "title": _text(link.group(2)), "categories": cats,
                 "excerpt": _text(ex.group(1)) if ex else ""}
        event_image_url = _event_image_url(image.group(1)) if image else None
        if event_image_url:
            event["event_image_url"] = event_image_url
        events.append(event)
    return events


def parse_detail(page: str, url: str) -> dict:
    """Auction page -> event facts. Anything absent stays out of the dict (becomes UNKNOWN downstream)."""
    out: dict = {}
    m = re.search(r'<h3 class="acDetailEventLabel">(.*?)</h3>', page, re.S)
    if m:
        out["sale_type"] = _text(m.group(1))
    info = re.search(r'<div class="acDetailEventInfo">(.*?)</div>', page, re.S)
    if info:
        b = re.search(r"Begin[s]?:</strong>\s*([^<]+)", info.group(1))
        e = re.search(r"Ends:</strong>\s*([^<]+)", info.group(1))
        out["begins_text"], out["ends_text"] = (_text(b.group(1)) if b else ""), (_text(e.group(1)) if e else "")
        if m:
            h = re.search(r"<h3><strong>(.*?)</strong></h3>", page[info.end():], re.S)
            if h:
                out["category_headline"] = _text(h.group(1))
        body = page[info.end():]
        body = body.split("selected highlights only", 1)[0]       # B-30: the page's own "selected highlights" list items
        items = [_text(li) for li in re.findall(r"<li>(.*?)</li>", body, re.S)]
        if items:
            out["highlights"] = [i for i in items if i]
    for href in re.findall(r'href="(https?://[^"]*hibid\.com[^"]*)"', page):
        out["hibid_catalog_url"] = html.unescape(href)          # link text only; never requested
        break
    loc = re.search(r"AUCTION LOCATION:</strong><br />(.*?)</p>", page, re.S)
    if loc:
        out["address"] = _text(loc.group(1))
    pre = re.search(r"PREVIEW/INSPECTION:</strong>\s*(.*?)</p>", page, re.S)
    if pre:
        out["preview"] = _text(pre.group(1))
    bp = re.search(r"BUYER(?:’|&#8217;|')S PREMIUM:</strong>\s*([\d.]+)\s*%", page)
    if bp:
        out["buyer_premium_pct"] = float(bp.group(1))
    art = re.search(r'<article[^>]*class="([^"]*)"', page)
    if art:
        out["category_slugs"] = [c[len("category-"):] for c in art.group(1).split()
                                 if c.startswith("category-") and c != "category-live-auction"]
    return out


class WooleySiteAdapter(SourceAdapter):
    """Auction-event adapter. `pages_dir` = archived pages (offline); `live=True` = real fetches (default OFF)."""
    source = SOURCE
    ingestion_method = "scrape"
    tos_risk = "low"
    access_tier = 3
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, pages_dir: str | Path | None = None, *, live: bool = False, transport: Transport | None = None,
                 clock: Callable[[], datetime] | None = None, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic, timeout: float = 20.0,
                 crawl_delay: float = CRAWL_DELAY_S) -> None:
        self.pages_dir = Path(pages_dir) if pages_dir else None
        self.live = live
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep, self.monotonic, self.timeout = sleep, monotonic, timeout
        self.crawl_delay = max(CRAWL_DELAY_S, crawl_delay)          # robots.txt Crawl-delay 10 is a floor
        self.http = ReadOnlyTransport(transport or UrllibTransport(follow_redirects=False), frozenset({SITE_HOST}))
        self._last: float | None = None
        self.summary: dict = {}

    # ---- fetching -------------------------------------------------------------------------------------------------
    def _get(self, url: str) -> tuple[str | None, SourceError | None]:
        if is_hibid(url):
            raise HibidRefused(f"hibid.com is never fetched (HiBid ToU s.9): {url}")
        if _site_url(url) is None:
            return None, SourceError("config", f"only https://{SITE_HOST} pages may be fetched: {url}")
        if self._last is not None:
            wait = self.crawl_delay - (self.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.monotonic()
        try:
            r: HttpResponse = self.http.request("GET", url, {"User-Agent": USER_AGENT, "Accept": "text/html"}, None, self.timeout)
        except TransportError as e:
            return None, SourceError("network", f"{SITE_HOST} unreachable (offline status): {e}")
        err = status_error(r, "Wooley Auctioneers")
        if err is None and r.status != 200:
            err = SourceError("http", f"HTTP {r.status} from {SITE_HOST}", r.status)
        return (None, err) if err else (r.body.decode("utf-8", "replace"), None)

    def _read(self, url: str, name: str) -> tuple[str | None, SourceError | None]:
        if self.live:
            return self._get(url)
        try:
            return (self.pages_dir / name).read_text(encoding="utf-8"), None      # type: ignore[operator]
        except (OSError, TypeError) as e:
            return None, SourceError("config", f"live fetch not enabled (live=True) and archived page unreadable: {e}")

    def fetch(self, profile: SearchProfile | None = None) -> FetchResult:
        res = FetchResult(SOURCE)
        before = len(self.http.log)
        now = self.clock()
        page, err = self._read(LISTING_URL, "auctions.html")
        res.requests_made = len(self.http.log) - before
        if err or page is None:
            res.error = err
            return res
        cards = parse_listing(page)[:MAX_EVENTS]
        detail_errors: dict[str, str] = {}
        for card in cards:
            body, derr = self._read(card["url"], f"{card['slug']}.html")
            if derr:
                detail_errors[card["slug"]] = derr.message
                if derr.kind in ("blocked", "rate_limited", "captcha"):
                    res.error = derr                                  # stop; a block signal freezes the source upstream
                    break
            payload = {**card, **(parse_detail(body, card["url"]) if body else {}), "detail_page": body is not None}
            res.records.append(RawRecord(raw_json_bytes(payload), payload, now, card["url"]))
        res.requests_made = len(self.http.log) - before
        self.summary = {"as_of": iso(now), "live": self.live, "events": len(res.records), "requests": res.requests_made,
                        "detail_errors": detail_errors}
        return res

    # ---- records --------------------------------------------------------------------------------------------------
    def lot(self, p: dict, fetched_at: datetime) -> AuctionLot:
        """The B-23 record for one auction EVENT (lot_id = page slug). Lot-level fields are UNKNOWN by construction."""
        if not isinstance(p, dict) or not p.get("slug") or not p.get("title"):
            raise NormalizationError("Wooley event missing slug/title")
        seen, url = iso(fetched_at), p.get("url", LISTING_URL)

        def fld(v, basis="FACT"):
            return Field(v if v not in (None, "", []) else UNKNOWN, url, seen, basis if v not in (None, "", []) else "UNKNOWN", 0)

        text = f"{p.get('begins_text') or ''} {p.get('excerpt') or ''}"
        ends_src = p.get("ends_text") or (re.search(r"Ends:\s*(.*?)(?:\s{2,}|$)", p.get("excerpt", "")) or [None, ""])[1]
        ends, ends_exact = parse_when(ends_src)
        begins, begins_exact = parse_when(p.get("begins_text") or re.sub(r".*?(Begins?|Began):", "", text, count=1))
        address = p.get("address")
        loc, loc_basis = {}, "FACT"
        if address:
            zm = re.search(r"([A-Za-z .'-]+?)\s*,?\s+(?:AR|Arkansas)\s+(\d{5})", address)
            if zm:
                loc = {"city": clean_text(zm.group(1).split("Road")[-1].split("Rd")[-1]).strip(", "), "state": "AR", "zip": zm.group(2)}
        if not loc:                                        # card only: city from the title suffix (INFERENCE)
            cm = re.search(r"([A-Za-z .'-]+),\s*(?:AR|Arkansas)\s*$", p["title"])
            if cm:
                loc, loc_basis = {"city": clean_text(cm.group(1)).split("|")[-1].split("–")[-1].strip().title(), "state": "AR"}, "INFERENCE"
        c = place_coords(loc) if loc else None
        dist = round(haversine_miles(HOME_BASE, c), 1) if c else None
        cats = p.get("categories") or [s.replace("-", " ").title() for s in p.get("category_slugs", [])]
        hl = p.get("highlights")
        hl = hl if isinstance(hl, list) else ([hl] if hl else [])
        headline = p.get("category_headline") or (hl[0] if isinstance(p.get("highlights"), str) else None)
        category, _ = classify("flip", match_text(p["title"]))        # title only: the headline lists many types (trailers is not the event)
        f = {
            "title": fld(clean_text(p["title"], 300)), "auctioneer": fld("Wooley Auctioneers"),
            "sale_type": fld(p.get("sale_type") or (p.get("excerpt") or "").split(" Begin")[0].split(" Began")[0] or None),
            "begins_at": fld(begins, "FACT" if begins_exact else "INFERENCE"),
            "closes_at": fld(ends, "FACT" if ends_exact else "INFERENCE"),
            "buyer_premium_pct": fld(p.get("buyer_premium_pct")), "sales_tax_pct": fld(None),
            "pickup": fld(None), "preview": fld(p.get("preview")), "address": fld(address),
            "location": fld(loc or None, loc_basis), "category_tags": fld(cats), "highlights": fld(hl),
            "category_headline": fld(headline), "event_category": fld(event_category(headline), "INFERENCE"),
            "rules_url": fld(p.get("url")), "hibid_catalog_url": fld(p.get("hibid_catalog_url")),
            "event_image_url": fld(p.get("event_image_url")),
            "category": fld(category, "INFERENCE"),
            "lot_number": Field(UNKNOWN, url, seen, "UNKNOWN", 0), "current_bid": Field(UNKNOWN, url, seen, "UNKNOWN", 0),
            "bid_count": Field(UNKNOWN, url, seen, "UNKNOWN", 0), "lot_image": Field(UNKNOWN, url, seen, "UNKNOWN", 0),
        }
        return AuctionLot(SOURCE, p["slug"], f, dist)

    def normalize(self, payload: dict, fetched_at: datetime) -> Normalized:
        lot = self.lot(payload, fetched_at)
        ends = lot.get("closes_at")
        ends = None if ends == UNKNOWN else datetime.fromisoformat(ends).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        bp = lot.get("buyer_premium_pct")
        price: dict = {"currency": "USD"}                          # no amount is known, so no price.type; premium only if stated
        if isinstance(bp, float):
            price["buyer_premium_pct"] = bp
        loc = lot.get("location") if isinstance(lot.get("location"), dict) else {}
        n: dict = {"title": lot.get("title"), "condition": "unknown", "price": price,
                   "counterparty": {"role": "auction_house", "name": "Wooley Auctioneers"},
                   "listing_status": "active", "images": []}
        if lot.get("highlights") != UNKNOWN:
            n["description"] = clean_text("; ".join(lot.get("highlights")), 4000)
        if ends:
            n["ends_at"] = ends
        if loc:
            n["location"] = {**loc, **({"geo_tier": geo_tier(lot.distance_miles)} if lot.distance_miles is not None else {})}
        category = lot.get("category")
        flags = base_flags(price=price, bid_count=None, ends_at=ends, fetched_at=fetched_at, matched=category != "other_asset",
                           tier=None, texts=(lot.get("title"), " ".join(lot.get("highlights")) if lot.get("highlights") != UNKNOWN else None))
        flags = sorted(set(flags) | {"needs_review"})              # event card only: no lot, bid or image data exists
        n["flags"] = flags
        return Normalized(source_listing_id=lot.lot_id, url=lot.get("rules_url"), type="flip", category=category,
                          opportunity_kind="auction_lot", normalized=n)
