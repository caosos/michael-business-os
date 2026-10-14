"""F-145 (B-12 sub-step): the source seam for /market. `load_source` returns the SAME card shape as `market_search.load_gsa` from lane 02's
`EmailAlertAdapter` records over a read-only `EmlDirReader` (never IMAP here, no network, no login). An `.eml` fixture directory is
parser-backed but NOT a live read: it is served only on the isolated-staging flag and always labelled FIXTURE / not live. A source without a
real read stays NOT CONNECTED. Pure functions; everything is DRY-RUN."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from functools import lru_cache
from pathlib import Path

from mbos_discovery.adapter import NormalizationError, SearchProfile
from mbos_discovery.adapters.blackmon_site import BlackmonSiteAdapter
from mbos_discovery.adapters.wilson_site import WilsonSiteAdapter
from mbos_discovery.adapters.wooley_site import WooleySiteAdapter
from mbos_discovery.auctions import UNKNOWN
from mbos_discovery.adapters.email_alerts import EmailAlertAdapter, EmlDirReader, ORIGINS, parse_alert
from mbos_discovery.auctions import place_coords
from mbos_discovery.dedup import title_similarity
from mbos_discovery.normalize import haversine_miles

from . import gazetteer, local_deal_sources as lds, market_facebook as mfb, market_search as ms

ALERT_SOURCES = {"govdeals": ("govdeals_email", "GovDeals"), "publicsurplus": ("publicsurplus_email", "Public Surplus"), "craigslist": ("craigslist_email", "Craigslist")}
CACHE_DIR = Path(__file__).resolve().parent.parent / "var" / "cache"


@dataclass(frozen=True)
class AuctionSite:
    """One auctioneer-events source (F-149). `platform_field` is the lane 02 lot field holding the bidding-platform link: a link for the human only, never requested."""
    key: str
    name: str
    env: str
    filename: str
    adapter: type
    platform_field: str
    platform: str
    min_interval_s: float = 0.0       # cross-process floor between live refreshes (the adapter itself only enforces it in-process)


AUCTION_SITES = {s.key: s for s in (
    AuctionSite("wooley", "Wooley Auctioneers", "MBOS_WOOLEY_CACHE", "wooley-events.json", WooleySiteAdapter, "hibid_catalog_url", "HiBid"),
    AuctionSite("wilson", "Wilson Auctioneers", "MBOS_WILSON_CACHE", "wilson-events.json", WilsonSiteAdapter, "bidwrangler_url", "BidWrangler", 3600.0),
    AuctionSite("blackmon", "Blackmon Auctions", "MBOS_BLACKMON_CACHE", "blackmon-events.json", BlackmonSiteAdapter, "proxibid_url", "Proxibid", 3600.0),
)}
ALL_HOUSES = "auctions"
ENV_WOOLEY = AUCTION_SITES["wooley"].env
WOOLEY_NAME = AUCTION_SITES["wooley"].name
EVENT_NAMES = {s.name for s in AUCTION_SITES.values()}
ENV_FLAG, ENV_DIR = "MBOS_STAGING_FIXTURES", "MBOS_MARKET_FIXTURE_MAIL_DIR"
ENV_ALERTS = "MBOS_ALERT_CACHE"                   # F-161: the local file written by tools/refresh_alert_mail.py
WAITING = "CONNECTED, WAITING FOR ALERTS"


def fixture_dir() -> str | None:
    """The .eml fixture directory, only when BOTH the isolated-staging flag and the directory are set; otherwise None (not connected)."""
    d = os.environ.get(ENV_DIR)
    return d if os.environ.get(ENV_FLAG) == "1" and d and Path(d).is_dir() else None


_HOOD = re.compile(r"Neighborhood/location text \(as shown, unverified\):\s*([^\n]{2,60})")
_SLUG_TOWN = re.compile(r"Town in listing link \(unverified\):\s*([^\n]{2,60})")
# Seller-typed Craigslist place text -> a gazetteer name. Only spelling forms; a text that still does not resolve stays UNKNOWN.
_TOWN_FIX = ((r"^(?:n\.?|no\.?)\s+", "north "), (r"^(?:s\.?)\s+", "south "), (r"^(?:w\.?)\s+", "west "), (r"^nlr$", "north little rock"),
             (r"^jax$", "jacksonville"), (r"^(?:west|w)\s+little\s+rock$", "little rock"), (r"^lr$", "little rock"))


def _town(text: str, state: str):
    """'N little rock ar' / 'Warren Arkansas' / 'Jax' -> ('North Little Rock', coords) or None."""
    t = " ".join(re.sub(r"[^A-Za-z .'-]", " ", text or "").split()).strip(" .,-").lower()
    t = re.sub(r"[ ,]+(?:ar|ark|arkansas)$", "", t).strip()
    if not t or t == "unknown":
        return None
    for pat, rep in _TOWN_FIX:
        t = re.sub(pat, rep, t)
    c = gazetteer.locate(f"{t}, {state}")
    return (t.title(), c) if c else None


def _coords(loc: dict):
    for t in (loc.get("zip"), f"{loc.get('city')} {loc.get('state')}" if loc.get("city") else None):
        c = gazetteer.locate(t) if t else None
        if c:
            return c
    return place_coords(loc) if loc.get("city") else None


def _empty(status: str, name: str, message: str) -> dict:
    return {"status": status, "as_of": None, "age_h": None, "stale": False, "in_scope": 0, "in_file": 0, "cards": [], "message": message, "name": name, "fixture": False}


def not_connected(source: str) -> dict:
    name = ALERT_SOURCES[source][1] if source in ALERT_SOURCES else source
    return _empty("not_connected", name, f"{name}: no mailbox read is configured on this host; nothing is shown rather than guessed.")


def _card(ad, rec, now, origin, name: str, fixture: bool = True) -> dict | None:
    p = rec.payload
    try:
        n = ad.normalize(p, rec.fetched_at)
        facts, _ = parse_alert(ad.origin, p["email_source"].encode("utf-8"))
    except NormalizationError:
        return None                                   # spoofed / unauthenticated / foreign mail: quarantined, never shown
    d = n.normalized
    loc = dict(d.get("location") or {})
    c = None
    if not loc.get("city") and loc.get("state"):                           # Craigslist: "(Town)" as shown, else the town in the link (both unverified)
        for m in (_HOOD.search(d.get("description") or ""), _SLUG_TOWN.search(d.get("description") or "")):
            hit = _town(m.group(1), loc["state"]) if m else None
            if hit:
                loc["city"], c = hit
                break
    c = c or (_coords(loc) if loc.get("city") or loc.get("zip") else None)
    dist = haversine_miles(origin, c) if (c and origin) else None          # unrounded, as for GSA; unknown stays None (never local)
    price = d.get("price") or {}
    amt = price.get("amount")
    bid = float(amt) if price.get("type") == "auction_current" and isinstance(amt, (int, float)) else None
    state = str(loc.get("state") or "").upper()
    desc = ms._short(d.get("description") or "")
    labels = ms.auction_labels({"highBidAmount": bid}, facts["date"])
    if bid is None:
        labels["opening_text"] = (f"Asking price ${amt:,.2f} (from the alert e-mail text; unverified)" if isinstance(amt, (int, float)) and price.get("type") == "fixed" else
                                  f"Starting price ${amt:,.2f} (from the alert e-mail text; unverified)" if isinstance(amt, (int, float)) else "Price not stated in the alert — check original listing")
    return {"id": f"{ad.source}:{n.source_listing_id}", "title": d["title"], "description": desc, "text": f"{d['title']} {desc}".lower(), "url": n.url, "image": None,
            "bid": bid, "price": float(amt) if isinstance(amt, (int, float)) else None, "price_type": price.get("type"), "bidders": None,
            "closes": str(d.get("ends_at") or "")[:10] or None, "city": f"{loc['city']}, {loc['state']}" if loc.get("city") and loc.get("state") else None,
            "state": state if state in ms.US_STATES else None, "zip": str(loc.get("zip") or "")[:5] or None, "posted": None, "distance": dist, "category": n.category, "condition": None, "labels": labels, "source": name,
            "fetched_at": facts["date"], "kind": "auction", "stale": ms._age_h(facts["date"], now) > ms.STALE_H, "fixture": fixture}


class _TextReader:
    """Read-only reader over the messages stored in the alert-mail cache (text -> bytes, exactly what the adapter keeps)."""
    def __init__(self, messages: list[str]) -> None:
        self.m = messages

    def messages(self, since):
        return (x.encode("utf-8") for x in self.m)


def alert_cache_path() -> str:
    return os.environ.get(ENV_ALERTS) or str(CACHE_DIR / "alert-mail.json")


def read_alert_cache(path: str | None = None) -> dict | None:
    """-> the cache doc ({as_of, mailbox_read, fixture, messages}) or None when absent/unreadable/malformed (= NOT CONNECTED)."""
    try:
        doc = json.loads(Path(path or alert_cache_path()).read_text(encoding="utf-8"))
        datetime.fromisoformat(str(doc["as_of"]))
        if not isinstance(doc["messages"], list) or not all(isinstance(m, str) for m in doc["messages"]):
            return None
        return doc
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _utc(v: str) -> datetime:
    d = datetime.fromisoformat(v.replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


@lru_cache(maxsize=16)
def _cached_records(path: str, mtime_ns: int, key: str, as_of: str):
    doc = read_alert_cache(path)
    ad = EmailAlertAdapter(key, _TextReader(doc["messages"] if doc else []), clock=lambda: _utc(as_of))
    return ad, tuple(ad.fetch(SearchProfile("market", "flip")).records)


def _from_cache(source: str, doc: dict, path: str, now: datetime, origin) -> dict:
    key, name = ALERT_SOURCES[source]
    as_of = str(doc["as_of"])
    fixture = bool(doc.get("fixture")) or not doc.get("mailbox_read")          # only a flagged real mailbox read is ever live
    ad, recs = _cached_records(path, Path(path).stat().st_mtime_ns, key, as_of)
    cards = [c for c in (_card(ad, r, now, origin, name, fixture) for r in recs if isinstance(r.payload, dict)) if c]
    age = round(ms._age_h(as_of, now), 1)
    base = {**_empty("fixture" if fixture else "connected", name, ""), "as_of": as_of, "age_h": age, "stale": age > ms.STALE_H, "in_file": len(recs), "fixture": fixture}
    if not cards:
        return {**base, "status": "fixture" if fixture else "waiting", "message": f"{name}: connected, waiting for alerts (the mailbox was read {age:g} h ago; no {name} alert has arrived)."}
    return {**base, "in_scope": len(cards), "cards": cards}


def load_alerts(source: str, directory: str | None, now: datetime, origin=None, cache: str | None = None) -> dict:
    """-> the `load_gsa` dict. Status: `fixture` (parser-backed .eml fixtures, never live), `connected` (a REAL mailbox read stored in the alert-mail
    cache returned items for this source), `waiting` (real read ok, no alert from this source yet) or `not_connected` (no usable read)."""
    key, name = ALERT_SOURCES[source]
    if not directory:
        path = cache or alert_cache_path()
        doc = read_alert_cache(path)
        return _from_cache(source, doc, path, now, origin) if doc else not_connected(source)
    ad = EmailAlertAdapter(key, EmlDirReader(directory), clock=lambda: now)
    res = ad.fetch(SearchProfile("market", "flip"))
    if res.error:
        return _empty("offline", name, f"{name}: fixture directory could not be read: {res.error.message}")
    cards = [c for c in (_card(ad, r, now, origin, name) for r in res.records if isinstance(r.payload, dict)) if c]
    newest = max((c["fetched_at"] for c in cards), default=None)
    age = round(ms._age_h(newest, now), 1) if newest else None
    return {**_empty("fixture", name, ""), "as_of": newest, "age_h": age, "stale": bool(age and age > ms.STALE_H), "in_scope": len(cards), "in_file": len(res.records),
            "cards": cards, "fixture": True}


_CT = ZoneInfo("America/Chicago")


def local_when(v) -> str | None:
    """'2026-10-13T18:00:00-05:00' -> 'Tue Oct 13, 6:00 PM CDT' (America/Chicago). A date-only value stays a date; unparseable -> None."""
    if not v:
        return None
    try:
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(str(v)) <= 10:
        return d.strftime("%a %b ") + str(d.day) + " (date only)"
    if d.tzinfo is None:
        d = d.replace(tzinfo=_CT)
    d = d.astimezone(_CT)
    return f"{d.strftime('%a %b')} {d.day}, {d.hour % 12 or 12}:{d:%M} {'AM' if d.hour < 12 else 'PM'} {d.tzname()}"


def _left(v, now) -> str | None:
    """Countdown in the existing style ('2d 4h', '5h 10m'); 'closed' once past. Needs a full timestamp."""
    try:
        sec = int((datetime.fromisoformat(str(v)) - now).total_seconds())
    except (TypeError, ValueError):
        return None
    return "closed" if sec <= 0 else f"{sec // 86400}d {sec % 86400 // 3600}h" if sec >= 86400 else f"{sec // 3600}h {sec % 3600 // 60}m"


def _event_card(site: AuctionSite, ad, payload, as_of: str, now, origin) -> dict:
    """One auction EVENT (not a lot). Lot number / current bid / bid count are UNKNOWN by construction (lane 02; HiBid/BidWrangler ToU)."""
    lot = ad.lot(payload, datetime.fromisoformat(as_of))
    g = lambda k: None if lot.get(k) == UNKNOWN else lot.get(k)  # noqa: E731
    loc = g("location") or {}
    c = _coords(loc) if loc else None
    dist = haversine_miles(origin, c) if (c and origin) else None
    tags = [str(t) for t in (g("category_tags") or [])]
    hl = g("highlights") or []
    hl = [hl] if isinstance(hl, str) else [str(x) for x in hl]
    desc = ms._short(" · ".join(x for x in (g("sale_type"), "; ".join(hl[:6])) if x))
    closes_at, begins_at = g("closes_at"), g("begins_at")
    day = str(closes_at or begins_at or "")[:10] or None
    return {"id": f"{site.key}:{lot.lot_id}", "title": g("title"), "description": desc, "text": f"{g('title')} {desc} {' '.join(hl)} {' '.join(tags)} {g('address') or ''}".lower(),
            "url": g("rules_url"), "platform_url": g(site.platform_field), "platform": site.platform, "hibid_url": g("hibid_catalog_url"),
            "image": g("event_image_url"), "image_kind": "auction event cover" if g("event_image_url") else None, "bid": None,
            "price": None, "price_type": None, "bidders": None, "closes": day, "closes_at": closes_at, "begins_at": begins_at,
            "closes_local": local_when(closes_at), "left": _left(closes_at, now), "begins_local": local_when(begins_at),
            "city": f"{loc['city']}, {loc['state']}" if loc.get("city") and loc.get("state") else None,
            "state": loc.get("state") if loc.get("state") in ms.US_STATES else None, "zip": str(loc.get("zip") or "")[:5] or None, "posted": None, "distance": dist, "category": g("category"), "condition": None,
            "labels": ms.auction_labels({}, as_of), "source": site.name, "fetched_at": as_of, "kind": "auction event", "stale": ms._age_h(as_of, now) > ms.STALE_H,
            "fixture": False, "event": True, "auctioneer": g("auctioneer"), "buyer_premium_pct": g("buyer_premium_pct"), "tags": tags, "event_tags": tags,
            "address": g("address"), "lot_number": None, "current_bid": None, "bid_count": None}


def cache_path(site: AuctionSite) -> str:
    return os.environ.get(site.env) or str(CACHE_DIR / site.filename)


def wooley_path() -> str:
    return cache_path(AUCTION_SITES["wooley"])


def load_events(site: AuctionSite, path: str | None, now: datetime, origin=None) -> dict:
    """-> the `load_gsa` dict from the cache written by `tools/refresh_auction_events.py --live`. REAL source: connected (cached file), never fixture.
    A missing/unreadable/empty-of-time cache is `offline` with an honest message. Never fetches."""
    path = path or cache_path(site)
    off = lambda m: {**_empty("offline", site.name, m), "coverage": None}  # noqa: E731
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
        as_of = str(doc["as_of"])
        datetime.fromisoformat(as_of)
        recs = doc["records"]
        assert isinstance(recs, list)
    except (OSError, ValueError, KeyError, TypeError, AssertionError):
        return off(f"{site.name}: no readable cached event file with an as-of time on this machine; nothing is shown rather than guessed.")
    err = doc.get("error")
    if err and not recs:
        return off(f"{site.name}: the last refresh failed ({(err.get('message') if isinstance(err, dict) else err)}); no events cached.")
    ad = site.adapter()
    cards = []
    for p in recs:
        try:
            cards.append(_event_card(site, ad, p, as_of, now, origin))
        except Exception:  # noqa: BLE001  one malformed event never breaks the page
            continue
    age = round(ms._age_h(as_of, now), 1)
    return {**_empty("connected", site.name, f"last refresh reported: {err.get('message') if isinstance(err, dict) else err}" if err else ""),
            "as_of": as_of, "age_h": age, "stale": age > ms.STALE_H, "in_scope": len(cards), "in_file": len(recs), "cards": cards, "requests": doc.get("requests")}


def load_wooley(path: str | None, now: datetime, origin=None) -> dict:
    return load_events(AUCTION_SITES["wooley"], path, now, origin)


def dedupe(cards: list[dict]) -> list[dict]:
    """Same source: merge only an identical link or card id (never by title). Different sources: identical link, or title similarity >= 0.9 AND same city AND same close date (first source wins).
    lane 02's pinned install has no Deduper class; this uses its `dedup.title_similarity`."""
    def same(c: dict, k: dict) -> bool:
        if c.get("source") == k.get("source"):
            return bool((c["url"] and c["url"] == k["url"]) or (c.get("id") and c.get("id") == k.get("id")))
        return bool((c["url"] and c["url"] == k["url"]) or (title_similarity(c["title"], k["title"]) >= 0.9 and c.get("city") == k.get("city") and c.get("closes") == k.get("closes")))
    out: list[dict] = []
    for c in cards:
        if not any(same(c, k) for k in out):
            out.append(c)
    return out


def coverage(parts: list[dict]) -> list[dict]:
    return [{k: d.get(k) for k in ("name", "status", "as_of", "age_h", "stale", "in_scope", "message", "historical")} for d in parts]


def load_source(source: str, gsa_path: str | None, now: datetime, origin=None, directory: str | None = None, query: dict | None = None) -> dict:
    """Dispatch a source or merge the unified pool; Facebook is the historical Bright Data cache, never refreshed (DS-SOURCE-01: no paid provider)."""
    directory = directory if directory is not None else fixture_dir()
    if source == "gsa":
        return ms.load_gsa(gsa_path, now, origin)
    if source == "facebook":
        d = mfb.load(now, origin)
        return {**d, "coverage": coverage([d])}
    if source == lds.SOURCE_KEY:
        d = lds.load(now, origin)
        return {**d, "coverage": coverage([d])}
    if source in AUCTION_SITES:
        d = load_events(AUCTION_SITES[source], None, now, origin)
        return {**d, "coverage": coverage([d])}
    if source == ALL_HOUSES:
        parts = [load_events(x, None, now, origin) for x in AUCTION_SITES.values()]
        live = [p for p in parts if p["status"] == "connected"]
        cards = dedupe([c for p in parts for c in p["cards"]])
        return {**_empty("connected" if live else "offline", "All auction houses", "" if live else "No auction-house cache is readable; nothing is shown rather than guessed."),
                "cards": cards, "in_scope": len(cards), "as_of": max((p["as_of"] for p in live), default=None), "coverage": coverage(parts)}
    if source in ALERT_SOURCES:
        d = load_alerts(source, directory, now, origin)
        return {**d, "coverage": coverage([d])}
    if source != "all":
        return not_connected(source)
    gsa = ms.load_gsa(gsa_path, now, origin)
    alerts = [load_alerts(s, directory, now, origin) for s in ALERT_SOURCES]
    houses = [load_events(x, None, now, origin) for x in AUCTION_SITES.values()]
    facebook = load_source("facebook", gsa_path, now, origin, directory, query)
    local = lds.load(now, origin)
    cards = dedupe(gsa["cards"] + facebook["cards"] + local["cards"] + [c for h in houses for c in h["cards"]] + [c for a in alerts for c in a["cards"]])
    live = "connected" in [gsa["status"], facebook["status"]] + [h["status"] for h in houses] + [a["status"] for a in alerts]
    status = "connected" if live else "fixture" if any(a["cards"] for a in alerts) else "imported" if local["cards"] else "offline"
    return {**gsa, "status": status, "cards": cards, "in_scope": len(cards), "fixture": any(a["fixture"] and a["cards"] for a in alerts),
            "message": gsa["message"] if status == "offline" else "", "refresh_pending": bool(facebook.get("refresh_pending")),
            "coverage": coverage([{**gsa, "name": "GSA Auctions"}, facebook, local] + houses + alerts)}


# ---- F-156: the source registry (the one place that knows every source; /market's Sources panel only displays it) ----
STATES = ("LIVE CONNECTED", "CONNECTED, WAITING FOR ALERTS", "IMPORTED", "MANUAL", "NOT CONNECTED", "BLOCKED")


@dataclass(frozen=True)
class SourceInfo:
    """`path` is one of: official API / provider API / own site / RSS / e-mail alerts / owner import / none. `probe` says which cache is read for freshness
    (gsa | site:<key> | alerts:<key> | finds[:<source>] | None). `intended` is the state when a read exists; a fixture or a missing cache never reaches LIVE CONNECTED."""
    key: str
    name: str
    cls: str
    geography: str
    path: str
    granularity: str
    bidding: str
    constraint: str
    next_step: str
    probe: str | None
    intended: str
    setup_url: str | None = None
    user_setup: str = ""
    parser: str = "none"
    import_key: str | None = None
    historical_only: bool = False         # DS-SOURCE-01: a readable cache of a route that is switched off; never LIVE CONNECTED


REGISTRY = (
    SourceInfo("gsa", "GSA Auctions", "government surplus", "US-wide (filtered by your distance)", "official API", "item (lot)", "bid on gsaauctions.gov with your own account; nothing is placed here",
               "cached copy; refreshed only by an explicit command", "keep the refresh command scheduled", "gsa", "LIVE CONNECTED",
               "https://gsaauctions.gov/", "No source login is shared with DealSniffer. Open the original lot link to verify and bid in your own account.", "official API"),
    SourceInfo("wooley", "Wooley Auctioneers", "auctioneer", "Arkansas", "own site", "auction event", "bids on HiBid (your account); this page never loads it",
               "events only: HiBid terms forbid scraping, so lot numbers, bids and bid counts need written permission", "ask Wooley/HiBid for written permission before any lot-level read", "site:wooley", "LIVE CONNECTED",
               "https://wooleyauctioneers.com/auctions/", "DealSniffer can show cached Wooley auction events. Open the event's original HiBid link for lots, current bids and bidding.", "event cache", "wooley"),
    SourceInfo("wilson", "Wilson Auctioneers", "auctioneer", "Arkansas", "own site", "auction event", "bids on BidWrangler (your account); this page never loads it",
               "events only; at most one refresh an hour", "none for events; lots need the platform's permission", "site:wilson", "LIVE CONNECTED"),
    SourceInfo("blackmon", "Blackmon Auctions", "auctioneer", "Arkansas", "own site", "auction event", "bids on Proxibid (your account); this page never loads it",
               "events only; at most one refresh an hour", "none for events; lots need the platform's permission", "site:blackmon", "LIVE CONNECTED"),
    SourceInfo("govdeals", "GovDeals", "government surplus", "US-wide", "e-mail alerts", "item (lot)", "bid on govdeals.com with your own account",
               "needs a read-only mailbox connection; test e-mails never count as live", "connect the DealSniffer alert address, then forward genuine saved-search alerts", "alerts:govdeals", "LIVE CONNECTED",
               "https://www.govdeals.com/", "Create the searches you want in your GovDeals account and forward their alert e-mails to your DealSniffer alert address.", "alert parser ready", "govdeals"),
    SourceInfo("publicsurplus", "Public Surplus", "government surplus", "US-wide", "e-mail alerts", "item (lot)", "bid on publicsurplus.com with your own account",
               "needs a read-only mailbox connection; test e-mails never count as live", "connect the DealSniffer alert address, then forward genuine saved-search alerts", "alerts:publicsurplus", "LIVE CONNECTED",
               "https://www.publicsurplus.com/", "Create the searches you want in your Public Surplus account and forward their alert e-mails to your DealSniffer alert address.", "alert parser ready", "publicsurplus"),
    SourceInfo("hibid_email", "HiBid e-mail alerts", "auction platform", "per your saved HiBid searches", "e-mail alerts", "item (lot)", "bid on hibid.com with your own account",
               "HiBid terms forbid scraping: lots need written permission; only alert e-mails you receive may be read", "save searches in HiBid; parser support and a real mailbox receipt are still required", None, "NOT CONNECTED",
               "https://hibid.com/arkansas", "Create your own HiBid searches and alerts. DealSniffer does not log in or scrape HiBid; its alert parser is not implemented yet.", "not implemented", "hibid"),
    SourceInfo("hibid_site", "HiBid website (lot data)", "auction platform", "US-wide", "none", "item (lot)", "bid on hibid.com with your own account",
               "HiBid terms forbid scraping: lots need written permission", "get written permission from HiBid; until then nothing is read", None, "BLOCKED",
               "https://hibid.com/arkansas", "Use the original HiBid page yourself. DealSniffer will not fetch lot pages without written permission.", "blocked"),
    SourceInfo("craigslist", "Craigslist", "classifieds", "local (your saved-search regions)", "e-mail alerts", "item", "none; contact sellers yourself",
               "only saved-search alert e-mails you receive are read (never craigslist.org); a test e-mail never counts as live; owner can still paste finds", "connect the DealSniffer alert address or paste an original listing link", "alerts:craigslist", "LIVE CONNECTED",
               "https://littlerock.craigslist.org/", "Create a Craigslist saved search and forward its alert e-mails, or paste an original listing link into Your finds.", "alert parser ready", "craigslist"),
    SourceInfo("facebook", "Facebook Marketplace", "classifieds", "local (ZIP/city + radius)", "provider API", "item", "none; contact sellers yourself",
               "HISTORICAL CACHE ONLY: the paid Bright Data route is off (owner direction, Oct 13, 2026); earlier results stay readable with their retrieval time",
               "find a permitted free route (source plan S3); no paid provider", "facebook", "LIVE CONNECTED", historical_only=True),
    SourceInfo("local_deals", "Authorized local deals", "local business offers", "city/ZIP + radius selected by the user", "reviewed import", "item offer", "redeem or purchase with the named business; DealSniffer does not transact",
               "only reviewed public offers or authority-attested vendor submissions; expiration is enforced; imports are not a live connection",
               "onboard one authorized Conway-area vendor and import a current, expiring offer with its original source evidence", "local_deals", "IMPORTED",
               None, "A reviewer may import a current public offer or an authority-attested vendor submission. It stays IMPORTED until a receipt-backed feed exists.", "normalized import ready", "local_deals"),
    SourceInfo("offerup", "OfferUp", "classifieds", "local", "owner import", "item", "none; contact sellers yourself",
               "terms forbid automated access: owner pastes finds only", "paste a find on the Finds form", "finds:offerup", "MANUAL",
               "https://offerup.com/", "Copy the original OfferUp listing link and paste it into Your finds. DealSniffer does not log in or fetch the page.", "manual only", "offerup"),
    SourceInfo("ebay", "eBay", "marketplace", "US-wide", "none", "item", "bid on ebay.com with your own account",
               "an official API exists but needs developer credentials; none are configured", "owner decision: apply for eBay API credentials", None, "NOT CONNECTED"),
    SourceInfo("owner_finds", "Owner-entered finds", "owner", "wherever you found it", "owner import", "item", "none",
               "only what you typed; unverified until you check it", "add a find", "finds", "MANUAL",
               None, "Paste the original link and the facts you observed. DealSniffer preserves the link and labels the record owner-entered and unverified.", "manual only", "other"),
    SourceInfo("nahlen", "Nahlen Auctions", "local auctioneer candidate", "Central Arkansas", "owner import", "auction event or item", "use the auctioneer's own bidding path; DealSniffer never bids",
               "an official current feed or alert path has not been verified", "paste a current original event or listing link; verify the source before treating it as active", "finds:nahlen", "MANUAL",
               None, "Paste a current original event or listing link into Your finds. No official feed or alert source is claimed.", "manual only", "nahlen"),
    SourceInfo("auctionzip", "AuctionZip", "auction directory", "ZIP/radius selected by the user", "owner import", "auction event or item", "use the auctioneer or platform account shown on the original page",
               "no automated retrieval is configured; directory entries can lead to a separate bidding platform", "search by ZIP, then paste the original auction or item link", "finds:auctionzip", "MANUAL",
               "https://www.auctionzip.com/", "Search by ZIP and category, then paste the original event or item link into Your finds.", "manual only", "auctionzip"),
    SourceInfo("half_off_wholesale", "Half Off Wholesale — Little Rock", "liquidation / wholesale", "North Little Rock area", "owner import", "pallet, truckload, or store event", "no bidding; purchase remains on the vendor's terms",
               "store/event information is not an item-level live feed; inventory and availability must be verified", "paste a current pallet, truckload, or event link with observed price and location", "finds:half_off_wholesale", "MANUAL",
               "https://halfoffvip.com/lp-little-rock/", "Open the vendor page, then paste a current pallet, truckload, or event link and the observed facts into Your finds.", "manual only", "half_off_wholesale"),
    SourceInfo("northbay", "NorthBay Tool Liquidation Pallets", "liquidation candidate", "Central Arkansas candidate", "owner import", "pallet or store event", "no connected account or bid capability",
               "current business status and an official source URL have not been verified", "verify the business and a current original page before adding an opportunity", "finds:northbay", "MANUAL",
               None, "No verified official page is stored. Add a find only after you have a current original link and have verified the source.", "manual only", "northbay"),
    SourceInfo("bargain_brothers", "Bargain Brothers", "discount / bin-store intelligence", "Central Arkansas candidate", "owner import", "store event or restock", "no bidding; purchase remains at the store",
               "event/store intelligence only; no item-level feed is connected and the current local source must be verified", "paste a current official restock or event link after verification", "finds:bargain_brothers", "MANUAL",
               None, "Paste a verified current restock or event link into Your finds. It remains store/event intelligence, not a live item listing.", "manual only", "bargain_brothers"),
)


def _finds_count(source: str | None = None) -> int:
    from . import market_finds
    return sum(1 for v in market_finds.load().values() if not v.get("deleted") and (source is None or v.get("source") == source))


def probe(info: SourceInfo, now: datetime) -> dict:
    """Light read of the cache behind a source (no card building, no network) -> {status: connected|fixture|offline|manual, as_of, age_h, stale, n}."""
    out = {"status": "offline", "as_of": None, "age_h": None, "stale": False, "n": None}
    if info.probe is None:
        return out
    kind, _, key = info.probe.partition(":")
    try:
        if kind == "finds":
            return {**out, "status": "manual", "n": _finds_count(key or None)}
        if kind == "facebook":
            return mfb.probe(now)
        if kind == "local_deals":
            return lds.probe(now)
        if kind == "alerts":
            if fixture_dir():
                return {**out, "status": "fixture"}
            d = load_alerts(key, None, now)
            return {**out, "status": d["status"] if d["status"] in ("connected", "fixture", "waiting") else "offline", "as_of": d["as_of"], "age_h": d["age_h"], "stale": d["stale"],
                    "n": d["in_scope"]}
        if kind == "gsa":
            asof = ms.GsaLiveAdapter(ms.cache_path(), live=False)._asof()
            as_of = asof.isoformat() if asof else None
        else:
            as_of = str(json.loads(Path(cache_path(AUCTION_SITES[key])).read_text(encoding="utf-8"))["as_of"])
            datetime.fromisoformat(as_of)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return out
    if not as_of:
        return out
    age = round(ms._age_h(as_of, now), 1)
    return {**out, "status": "connected", "as_of": as_of, "age_h": age, "stale": age > ms.STALE_H}


def source_state(info: SourceInfo, pr: dict) -> str:
    """Exactly one of STATES. LIVE CONNECTED only for a real cached read (probe status `connected`); a fixture, a missing cache or a stale-less guess never is."""
    if info.intended == "BLOCKED":
        return "BLOCKED"
    if info.historical_only:
        return "NOT CONNECTED"
    if info.intended == "MANUAL":
        return "MANUAL"
    if info.intended == "IMPORTED":
        return "IMPORTED" if pr["status"] == "imported" else "NOT CONNECTED"
    if pr["status"] == "waiting" and info.intended == "LIVE CONNECTED":
        return WAITING
    return "LIVE CONNECTED" if pr["status"] == "connected" and info.intended == "LIVE CONNECTED" else "NOT CONNECTED"
