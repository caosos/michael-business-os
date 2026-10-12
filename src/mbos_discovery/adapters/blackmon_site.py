"""B-29: Blackmon Auctions (Lonoke AR) auction EVENTS from its own Squarespace RSS feed plus event pages (read-only, EVENT level).

Source boundary (FACT, Agent 01 2026-10-12): robots.txt allows `blackmonauctions.com/auctions?format=rss` and the event pages.
Bidding runs on Proxibid, whose `blackmon.proxibid.com` robots says `Disallow: /`. This module NEVER fetches a `*.proxibid.com` URL
(`_get` refuses it before a request is built); the Proxibid link is kept as text for the human only. Lot number, current bid, bid count
and lot image are UNKNOWN on every record.

Feed `pubDate` is a PUBLISH date (an Oct 2026 sale can be published Dec 2025), so event dates come only from the event page. The feed
lists current AND past auctions; only events whose page date is today (America/Chicago) or later are kept. Event pages are fetched only for
feed items. Live is OFF unless `live=True`; anonymous User-Agent; >= 10 s between requests (floor) and at most one live run per hour.
Page times carry no zone label; they are read as America/Chicago local time (INFERENCE).
"""

from __future__ import annotations

import html
import re
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from ..adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..auctions import UNKNOWN, AuctionLot, Field, place_coords
from ..canonical import raw_json_bytes
from ..http import HttpResponse, ReadOnlyTransport, Transport, TransportError, UrllibTransport, status_error
from ..ids import iso
from ..normalize import HOME_BASE, base_flags, classify, clean_text, geo_tier, haversine_miles, match_text

SOURCE = "blackmon_auctions"
SITE_HOST = "www.blackmonauctions.com"
SITE_HOSTS = frozenset({SITE_HOST, "blackmonauctions.com"})
FEED_URL = f"https://{SITE_HOST}/auctions?format=rss"
USER_AGENT = "DealSnifferBot/1.0 (read-only; auction events only)"
CRAWL_DELAY_S = 10.0
MIN_RUN_INTERVAL_S = 3600.0
MAX_EVENTS = 40
LOT_LEVEL_UNKNOWN = ("lot_number", "current_bid", "bid_count", "lot_image")
_CENTRAL = ZoneInfo("America/Chicago")
_TAG = re.compile(r"<[^>]+>")
_ADDR = re.compile(r"^(?:.*?,\s*)?([^,]+?),\s*(?:AR|Arkansas)\s+(\d{5})\s*$", re.I)
_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*([ap]m)", re.I)
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


class ProxibidRefused(Exception):
    """A proxibid.com URL reached a fetch path. blackmon.proxibid.com robots.txt says Disallow: /."""


def is_proxibid(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return host == "proxibid.com" or host.endswith(".proxibid.com")


def _text(s: str) -> str:
    return clean_text(html.unescape(_TAG.sub(" ", s)).replace(" ", " ").replace("\xa0", " "), 4000)


def _site_url(url: str) -> str | None:
    p = urlsplit(url)
    ok = p.scheme == "https" and p.hostname in SITE_HOSTS and not is_proxibid(url) and p.path.startswith("/auctions")
    return url if ok else None


def parse_feed(xml: str) -> list[dict]:
    """One dict per feed `<item>` (title, url, slug, guid, published, Proxibid link as text). Publish dates are NOT event dates."""
    out: list[dict] = []
    for block in xml.split("<item>")[1:]:
        def tag(n: str) -> str:
            m = re.search(rf"<{n}>(.*?)</{n}>", block, re.S)
            return html.unescape(m.group(1)).strip() if m else ""
        url, title = tag("link"), _text(tag("title"))
        seg = [s for s in urlsplit(url).path.strip("/").split("/") if s]
        if not title or not _site_url(url) or len(seg) < 2:
            continue
        item = {"url": url, "slug": seg[-1], "title": title, "guid": tag("guid"), "published_at": tag("pubDate")}
        px = re.search(r'<a href="(https?://[^"]*proxibid\.com/[^"]*/event-catalog/[^"]*)"', html.unescape(block))   # the feed body's Bid Now button
        if px:
            item["proxibid_url"] = px.group(1)                    # text only; never requested
        out.append(item)
    return out


def parse_local(day: str, clock_text: str) -> str | None:
    """('2026-10-13', '9:00 AM') -> '2026-10-13T09:00:00-05:00' (America/Chicago local; the page names no zone)."""
    m, d = _TIME.search(clock_text or ""), _DATE.fullmatch(day or "")
    if not m or not d:
        return None
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "pm" else 0)
    try:
        y, mo, dd = (int(x) for x in day.split("-"))
        return datetime(y, mo, dd, hour, int(m.group(2)), tzinfo=_CENTRAL).isoformat()
    except ValueError:
        return None


def parse_event_page(page: str) -> dict:
    """Event facts from the Squarespace event page. Anything absent stays out of the dict (UNKNOWN downstream)."""
    art = re.search(r'<article class="eventitem.*?</article>', page, re.S)
    body = art.group(0) if art else page
    ev: dict = {}
    t = re.search(r'<h1 class="eventitem-title"[^>]*>(.*?)</h1>', body, re.S)
    if t:
        ev["page_title"] = _text(t.group(1))
    d = re.search(r'<time class="event-date" datetime="([^"]*)"', body)
    if d:
        ev["start_date"] = d.group(1)
    for key, cls in (("start", "start"), ("end", "end")):
        m = re.search(rf'<time class="event-time-localized-{cls}" datetime="([^"]*)">(.*?)</time>', body, re.S)
        if m:
            ev[f"{key}_date"] = m.group(1)
            ev[f"{key}_time"] = _text(m.group(2))
    lines = [_text(x) for x in re.findall(r'<span class="eventitem-meta-address-line[^"]*">(.*?)</span>', body, re.S)]
    if any(lines):
        ev["location_text"] = ", ".join(x for x in lines if x)
    txt = _text(re.sub(r"<br\s*/?>", ". ", body))
    ty = re.search(r"Type Auction:\s*([^.]+)", txt)
    if ty:
        ev["sale_type"] = clean_text(ty.group(1), 80)
    bp = re.search(r"Buyers?\s*Premium[^%.]{0,80}?(\d+(?:\.\d+)?)\s*%", txt, re.I)
    if bp:
        ev["buyer_premium_pct"] = float(bp.group(1))
    return ev


def event_end_day(ev: dict) -> date | None:
    for k in ("end_date", "start_date"):
        if _DATE.fullmatch(ev.get(k) or ""):
            return date.fromisoformat(ev[k])
    return None


class BlackmonSiteAdapter(SourceAdapter):
    """Auction-event adapter. `pages_dir` = archived feed `auctions.rss` + `event-<slug>.html` (offline); `live=True` = real fetches (default OFF)."""
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
        self.crawl_delay = max(CRAWL_DELAY_S, crawl_delay)          # a 10 s gap is a floor
        self.min_run_interval = max(MIN_RUN_INTERVAL_S, min_run_interval)   # at most hourly
        self.http = ReadOnlyTransport(transport or UrllibTransport(follow_redirects=False), SITE_HOSTS)
        self._last: float | None = None
        self._last_run: float | None = None
        self.summary: dict = {}

    def _get(self, url: str) -> tuple[str | None, SourceError | None]:
        if is_proxibid(url):
            raise ProxibidRefused(f"proxibid.com is never fetched (blackmon.proxibid.com robots: Disallow /): {url}")
        if _site_url(url) is None:
            return None, SourceError("config", f"only https://{SITE_HOST}/auctions pages may be fetched: {url}")
        if self._last is not None:
            wait = self.crawl_delay - (self.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
        self._last = self.monotonic()
        try:
            r: HttpResponse = self.http.request("GET", url, {"User-Agent": USER_AGENT, "Accept": "text/html,application/rss+xml"}, None, self.timeout)
        except TransportError as e:
            return None, SourceError("network", f"{SITE_HOST} unreachable (offline status): {e}")
        err = status_error(r, "Blackmon Auctions")
        if err is None and r.status != 200:
            err = SourceError("http", f"HTTP {r.status} from {SITE_HOST}", r.status)
        return (None, err) if err else (r.body.decode("utf-8", "replace"), None)

    def _offline(self, name: str) -> tuple[str | None, SourceError | None]:
        try:
            return (self.pages_dir / name).read_text(encoding="utf-8"), None      # type: ignore[operator]
        except (OSError, TypeError) as e:
            return None, SourceError("config", f"live fetch not enabled (live=True) and archived file {name} unreadable: {e}")

    def _read_feed(self) -> tuple[str | None, SourceError | None]:
        if not self.live:
            return self._offline("auctions.rss")
        now = self.monotonic()
        if self._last_run is not None and now - self._last_run < self.min_run_interval:
            return None, SourceError("config", f"live run skipped: at most one per {int(self.min_run_interval)} s")
        self._last_run = now
        return self._get(FEED_URL)

    def _read_event(self, item: dict) -> tuple[str | None, SourceError | None]:
        return self._get(item["url"]) if self.live else self._offline(f"event-{item['slug']}.html")

    def fetch(self, profile: SearchProfile | None = None) -> FetchResult:
        res = FetchResult(SOURCE)
        before = len(self.http.log)
        now = self.clock()
        feed, err = self._read_feed()
        if err or feed is None:
            res.requests_made = len(self.http.log) - before
            res.error = err
            return res
        today = now.astimezone(_CENTRAL).date()
        items = parse_feed(feed)[:MAX_EVENTS]
        skipped = {"past": 0, "no_page": 0, "no_date": 0}
        for it in items:
            page, perr = self._read_event(it)
            if perr or page is None:
                if self.live and perr and perr.is_block:
                    res.error = perr                                  # a block stops the run; never keep hammering
                    break
                skipped["no_page"] += 1
                continue
            ev = {**it, **parse_event_page(page)}
            end = event_end_day(ev)
            if end is None:
                skipped["no_date"] += 1
            elif end < today:
                skipped["past"] += 1
            else:
                res.records.append(RawRecord(raw_json_bytes(ev), ev, now, ev["url"]))
        res.requests_made = len(self.http.log) - before
        self.summary = {"as_of": iso(now), "live": self.live, "feed_items": len(items), "events": len(res.records),
                        "skipped": skipped, "requests": res.requests_made}
        return res

    def lot(self, p: dict, fetched_at: datetime) -> AuctionLot:
        """The B-23 record for one auction EVENT (lot_id = URL slug). Lot-level fields are UNKNOWN by construction."""
        if not isinstance(p, dict) or not p.get("slug") or not p.get("title"):
            raise NormalizationError("Blackmon event missing slug/title")
        seen, url = iso(fetched_at), p.get("url", FEED_URL)

        def fld(v, basis="FACT"):
            ok = v not in (None, "", [])
            return Field(v if ok else UNKNOWN, url, seen, basis if ok else "UNKNOWN", 0)

        starts = parse_local(p.get("start_date", ""), p.get("start_time", ""))
        ends = parse_local(p.get("end_date", ""), p.get("end_time", ""))
        reasons = {k: "event page states no parseable date+time" for k, v in (("begins_at", starts), ("closes_at", ends)) if not v}
        text = p.get("location_text") or ""
        multi = "multiple locations" in text.lower()
        loc: dict = {}
        am = None if multi else _ADDR.match(text)
        if am:
            loc = {"city": clean_text(am.group(1)), "state": "AR", "zip": am.group(2)}
        c = place_coords(loc) if loc else None
        dist = round(haversine_miles(HOME_BASE, c), 1) if c else None
        loc_reason = ("event page location reads 'Multiple Locations'" if multi else
                      None if loc else "event page location is absent or not a parseable Arkansas address")
        category, _ = classify("flip", match_text(p["title"]), "")
        f = {
            "title": fld(clean_text(p["title"], 300)), "auctioneer": fld("Blackmon Auctions"),
            "sale_type": fld(p.get("sale_type")),
            "begins_at": fld(starts, "INFERENCE"), "closes_at": fld(ends, "INFERENCE"),
            "date_unknown_reason": fld("; ".join(f"{k}: {v}" for k, v in reasons.items()) or None),
            "published_at": fld(p.get("published_at")),               # feed pubDate: when the page was published, NOT the event date
            "buyer_premium_pct": fld(p.get("buyer_premium_pct")), "sales_tax_pct": fld(None), "pickup": fld(None), "preview": fld(None),
            "address": fld(None if multi else text), "location": fld(loc or None), "location_unknown_reason": fld(loc_reason),
            "category_tags": fld([]), "highlights": fld([]),
            "rules_url": fld(p.get("url")), "proxibid_url": fld(p.get("proxibid_url")),
            "category": fld(category, "INFERENCE"),
            "lot_number": Field(UNKNOWN, url, seen, "UNKNOWN", 0), "current_bid": Field(UNKNOWN, url, seen, "UNKNOWN", 0),
            "bid_count": Field(UNKNOWN, url, seen, "UNKNOWN", 0), "lot_image": Field(UNKNOWN, url, seen, "UNKNOWN", 0),
        }
        return AuctionLot(SOURCE, p["slug"], f, dist)

    def normalize(self, payload: dict, fetched_at: datetime) -> Normalized:
        lot = self.lot(payload, fetched_at)
        ends = lot.get("closes_at")
        ends = None if ends == UNKNOWN else datetime.fromisoformat(ends).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        price: dict = {"currency": "USD"}                          # no amount or type is stated on the event page
        loc = lot.get("location") if isinstance(lot.get("location"), dict) else {}
        n: dict = {"title": lot.get("title"), "condition": "unknown", "price": price,
                   "counterparty": {"role": "auction_house", "name": "Blackmon Auctions"},
                   "listing_status": "active", "images": []}
        if ends:
            n["ends_at"] = ends
        if loc:
            n["location"] = {**loc, **({"geo_tier": geo_tier(lot.distance_miles)} if lot.distance_miles is not None else {})}
        category = lot.get("category")
        flags = base_flags(price=price, bid_count=None, ends_at=ends, fetched_at=fetched_at, matched=category != "other_asset",
                           tier=None, texts=(lot.get("title"),))
        n["flags"] = sorted(set(flags) | {"needs_review"})        # event card only: no lot, bid or image data exists
        return Normalized(source_listing_id=lot.lot_id, url=lot.get("rules_url"), type="flip", category=category,
                          opportunity_kind="auction_lot", normalized=n)
