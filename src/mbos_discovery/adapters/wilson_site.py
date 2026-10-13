"""B-28: Wilson Auctioneers (Hot Springs AR) auction EVENTS from wilsonauctioneers.com/auctions/ (read-only, EVENT level).

Source boundary (FACT, Agent 01 2026-10-12): Wilson's bidding runs on BidWrangler, whose Terms of Use forbid data mining. This module
NEVER fetches a `*.bidwrangler.com` URL and `_get` refuses it before a request is built; any BidWrangler link is kept as text for the
human only. Lot number, current bid, bid count and lot image are UNKNOWN on every record.

Everything an event card needs is on the /auctions/ LIST page (title, sale type, location, start/end, details, on-site auction link), so
live mode makes exactly ONE request per run, never a detail-page fetch. robots.txt: only /wp-admin/ disallowed, Crawl-delay 10; no terms
page found. Live is OFF unless `live=True`; anonymous User-Agent; >= 10 s between requests (floor) and at most one live run per hour.
The site writes 'CST' even in daylight time, so times are read as America/Chicago local time (INFERENCE), never a fixed UTC-6.
"""

from __future__ import annotations

import html
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

from ..adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..auctions import UNKNOWN, AuctionLot, Field, place_coords
from ..canonical import raw_json_bytes
from ..http import HttpResponse, ReadOnlyTransport, Transport, TransportError, UrllibTransport, status_error
from ..ids import iso
from ..normalize import HOME_BASE, base_flags, classify, clean_text, geo_tier, haversine_miles, match_text

SOURCE = "wilson_auctioneers"
SITE_HOST = "wilsonauctioneers.com"
IMAGE_HOST = "d37cbsn538t2ha.cloudfront.net"
LISTING_URL = f"https://{SITE_HOST}/auctions/"
USER_AGENT = "DealSnifferBot/1.0 (read-only; auction events only)"
CRAWL_DELAY_S = 10.0
MIN_RUN_INTERVAL_S = 3600.0
MAX_EVENTS = 40
LOT_LEVEL_UNKNOWN = ("lot_number", "current_bid", "bid_count", "lot_image")
_CENTRAL = ZoneInfo("America/Chicago")
_TAG = re.compile(r"<[^>]+>")
_WHEN = re.compile(r"([A-Z][a-z]{2})\s+(\d{1,2})\s+(\d{4})\s*(?:–|-|&ndash;)?\s*(\d{1,2}):(\d{2})\s*([ap]m)\s*(?:CST|CDT|CT)\b", re.I)
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}
_ADDR = re.compile(r"^(.*?),\s*([^,]+?),\s*(?:AR|Arkansas)\s+(\d{5})\s*$", re.I)


class BidWranglerRefused(Exception):
    """A bidwrangler.com URL reached a fetch path. BidWrangler's Terms of Use forbid data mining."""


def is_bidwrangler(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "bidwrangler.com" or host.endswith(".bidwrangler.com")


def _text(s: str) -> str:
    return clean_text(html.unescape(_TAG.sub(" ", s)), 4000)


def parse_when(s: str) -> str | None:
    """'Oct 13 2026 – 7:00pm CST' -> '2026-10-13T19:00:00-05:00' (America/Chicago local; the label CST/CDT is not trusted)."""
    m = _WHEN.search(html.unescape(s or "").replace("\xa0", " "))
    if not m or m.group(1).lower() not in _MONTHS:
        return None
    mon, d, y, hh, mm, ap = m.groups()
    hour = int(hh) % 12 + (12 if ap.lower() == "pm" else 0)
    try:
        return datetime(int(y), _MONTHS[mon.lower()], int(d), hour, int(mm), tzinfo=_CENTRAL).isoformat()
    except ValueError:
        return None


def date_reasons(p: dict) -> dict[str, str]:
    """Why begins_at / closes_at are UNKNOWN for one event (empty when both are parsed). Live/Simulcast states only a start."""
    online = "online" in (p.get("sale_type") or "").lower()
    out: dict[str, str] = {}
    for key, text in (("begins_at", p.get("starts_text")), ("closes_at", p.get("ends_text"))):
        if parse_when(text or "") and (key == "begins_at" or online):
            continue
        if key == "closes_at" and not online:
            out[key] = "live/simulcast card states one start time only; no end time is published"
        elif not text:
            out[key] = "card has no date line"
        elif text.strip().lower() == "active":
            out[key] = "card says 'Active': already open, no start stated"
        else:
            out[key] = f"date line not parseable (no date+time+zone): {text[:60]!r}"
    return out


def _site_url(url: str) -> str | None:
    p = urlsplit(url)
    return url if p.scheme == "https" and p.hostname == SITE_HOST and not is_bidwrangler(url) else None


def _event_image_url(value: str) -> str | None:
    """Accept only Wilson's HTTPS event-gallery CDN URL. This is not a BidWrangler lot image."""
    try:
        url = html.unescape(value).strip()
        p = urlsplit(url)
        port = p.port
    except (AttributeError, ValueError):
        return None
    return url if p.scheme == "https" and p.hostname == IMAGE_HOST and p.username is None and p.password is None and port in (None, 443) else None


def parse_listing(page: str) -> list[dict]:
    """One dict per `auction-item` card. Anything absent stays out of the dict (UNKNOWN downstream)."""
    events: list[dict] = []
    for block in page.split('<div class="auction-item')[1:]:
        block = re.sub(r"<svg.*?</svg>", "", block, flags=re.S)
        link = re.search(r'<a href="([^"]+)">\s*<p class="auction-type">(.*?)</p>\s*<h3 class="auction-name">(.*?)</h3>', block, re.S)
        if not link:
            continue
        href = html.unescape(link.group(1))
        url = _site_url(urljoin(LISTING_URL, href))
        seg = [s for s in urlsplit(href).path.strip("/").split("/") if s]
        if not url or len(seg) < 2:
            continue
        ev: dict = {"url": url, "slug": "-".join(seg[1:]), "path_category": seg[1] if len(seg) > 2 else "",
                    "sale_type": _text(link.group(2)), "title": _text(link.group(3))}
        image = re.search(r'<div class="auction-listing-gallery">.*?<img[^>]*\bsrc="([^"]+)"', block, re.S)
        event_image_url = _event_image_url(image.group(1)) if image else None
        if event_image_url:
            ev["event_image_url"] = event_image_url
        times = re.findall(r'<p class="title-desc">\s*(Auction Start|Auction End)</p>\s*<p class="auction-datetime[^"]*">(.*?)</p>', block, re.S)
        for label, val in times:
            val = _text(val)
            ev["starts_text" if label == "Auction Start" else "ends_text"] = val
        loc = re.search(r'<p class="title-desc">Location</p>\s*<p>(.*?)</p>', block, re.S)
        if loc:
            ev["address"] = _text(loc.group(1)).replace(" ,", ",")
        det = re.search(r'<p class="title-desc">Details</p>\s*<p>(.*?)</p>', block, re.S)
        if det:
            ev["details"] = _text(det.group(1))
        for h in re.findall(r'href="(https?://[^"]*bidwrangler\.com[^"]*)"', block):
            ev["bidwrangler_url"] = html.unescape(h)               # text only; never requested
            break
        events.append(ev)
    return events


class WilsonSiteAdapter(SourceAdapter):
    """Auction-event adapter. `pages_dir` = archived page (offline); `live=True` = one real fetch per run (default OFF)."""
    source = SOURCE
    ingestion_method = "scrape"
    tos_risk = "low"
    access_tier = 3
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, pages_dir: str | Path | None = None, *, live: bool = False, transport: Transport | None = None,
                 clock: Callable[[], datetime] | None = None, sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic, timeout: float = 20.0,
                 crawl_delay: float = CRAWL_DELAY_S, min_run_interval: float = MIN_RUN_INTERVAL_S) -> None:
        self.pages_dir = Path(pages_dir) if pages_dir else None
        self.live = live
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.sleep, self.monotonic, self.timeout = sleep, monotonic, timeout
        self.crawl_delay = max(CRAWL_DELAY_S, crawl_delay)          # robots.txt Crawl-delay 10 is a floor
        self.min_run_interval = max(MIN_RUN_INTERVAL_S, min_run_interval)   # at most hourly
        self.http = ReadOnlyTransport(transport or UrllibTransport(follow_redirects=False), frozenset({SITE_HOST}))
        self._last: float | None = None
        self._last_run: float | None = None
        self.summary: dict = {}

    def _get(self, url: str) -> tuple[str | None, SourceError | None]:
        if is_bidwrangler(url):
            raise BidWranglerRefused(f"bidwrangler.com is never fetched (BidWrangler ToU): {url}")
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
        err = status_error(r, "Wilson Auctioneers")
        if err is None and r.status != 200:
            err = SourceError("http", f"HTTP {r.status} from {SITE_HOST}", r.status)
        return (None, err) if err else (r.body.decode("utf-8", "replace"), None)

    def _read(self) -> tuple[str | None, SourceError | None]:
        if self.live:
            now = self.monotonic()
            if self._last_run is not None and now - self._last_run < self.min_run_interval:
                return None, SourceError("config", f"live run skipped: at most one per {int(self.min_run_interval)} s")
            self._last_run = now
            return self._get(LISTING_URL)
        try:
            return (self.pages_dir / "auctions.html").read_text(encoding="utf-8"), None      # type: ignore[operator]
        except (OSError, TypeError) as e:
            return None, SourceError("config", f"live fetch not enabled (live=True) and archived page unreadable: {e}")

    def fetch(self, profile: SearchProfile | None = None) -> FetchResult:
        res = FetchResult(SOURCE)
        before = len(self.http.log)
        now = self.clock()
        page, err = self._read()
        res.requests_made = len(self.http.log) - before
        if err or page is None:
            res.error = err
            return res
        for ev in parse_listing(page)[:MAX_EVENTS]:
            res.records.append(RawRecord(raw_json_bytes(ev), ev, now, ev["url"]))
        self.summary = {"as_of": iso(now), "live": self.live, "events": len(res.records), "requests": res.requests_made}
        return res

    def lot(self, p: dict, fetched_at: datetime) -> AuctionLot:
        """The B-23 record for one auction EVENT (lot_id = path slug). Lot-level fields are UNKNOWN by construction."""
        if not isinstance(p, dict) or not p.get("slug") or not p.get("title"):
            raise NormalizationError("Wilson event missing slug/title")
        seen, url = iso(fetched_at), p.get("url", LISTING_URL)

        def fld(v, basis="FACT"):
            ok = v not in (None, "", [])
            return Field(v if ok else UNKNOWN, url, seen, basis if ok else "UNKNOWN", 0)

        starts, ends = parse_when(p.get("starts_text", "")), parse_when(p.get("ends_text", ""))
        online = "online" in (p.get("sale_type") or "").lower()
        address = p.get("address")
        loc: dict = {}
        am = _ADDR.match(address or "")
        if am:
            loc = {"city": clean_text(am.group(2)), "state": "AR", "zip": am.group(3)}
        c = place_coords(loc) if loc else None
        dist = round(haversine_miles(HOME_BASE, c), 1) if c else None
        pc = p.get("path_category") or ""
        category, _ = classify("flip", match_text(p["title"]), match_text(p.get("details") or ""))
        f = {
            "title": fld(clean_text(p["title"], 300)), "auctioneer": fld("Wilson Auctioneers"),
            "sale_type": fld(p.get("sale_type")),
            # online: 'Active' means already open (no date); live/simulcast: the single date is the event start
            "begins_at": fld(starts, "INFERENCE"), "closes_at": fld(ends if online else None, "INFERENCE"),
            "date_unknown_reason": fld("; ".join(f"{k}: {v}" for k, v in date_reasons(p).items()) or None),
            "buyer_premium_pct": fld(None), "sales_tax_pct": fld(None), "pickup": fld(None), "preview": fld(None),
            "address": fld(address), "location": fld(loc or None), "category_tags": fld([pc.replace("-", " ")] if pc else []),
            "highlights": fld([p["details"]] if p.get("details") else []),
            "rules_url": fld(p.get("url")), "bidwrangler_url": fld(p.get("bidwrangler_url")),
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
        price: dict = {"currency": "USD"}                          # no amount, premium or type is stated on the list page
        loc = lot.get("location") if isinstance(lot.get("location"), dict) else {}
        hl = lot.get("highlights")
        n: dict = {"title": lot.get("title"), "condition": "unknown", "price": price,
                   "counterparty": {"role": "auction_house", "name": "Wilson Auctioneers"},
                   "listing_status": "active", "images": []}
        if hl != UNKNOWN:
            n["description"] = clean_text("; ".join(hl), 4000)
        if ends:
            n["ends_at"] = ends
        if loc:
            n["location"] = {**loc, **({"geo_tier": geo_tier(lot.distance_miles)} if lot.distance_miles is not None else {})}
        category = lot.get("category")
        flags = base_flags(price=price, bid_count=None, ends_at=ends, fetched_at=fetched_at, matched=category != "other_asset",
                           tier=None, texts=(lot.get("title"), " ".join(hl) if hl != UNKNOWN else None))
        n["flags"] = sorted(set(flags) | {"needs_review"})        # event card only: no lot, bid or image data exists
        return Normalized(source_listing_id=lot.lot_id, url=lot.get("rules_url"), type="flip", category=category,
                          opportunity_kind="auction_lot", normalized=n)
