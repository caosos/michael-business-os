"""F-145 (B-12 sub-step): the source seam for /market. `load_source` returns the SAME card shape as `market_search.load_gsa` from lane 02's
`EmailAlertAdapter` records over a read-only `EmlDirReader` (never IMAP here, no network, no login). An `.eml` fixture directory is
parser-backed but NOT a live read: it is served only on the isolated-staging flag and always labelled FIXTURE / not live. A source without a
real read stays NOT CONNECTED. Pure functions; everything is DRY-RUN."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from mbos_discovery.adapter import NormalizationError, SearchProfile
from mbos_discovery.adapters.wilson_site import WilsonSiteAdapter
from mbos_discovery.adapters.wooley_site import WooleySiteAdapter
from mbos_discovery.auctions import UNKNOWN
from mbos_discovery.adapters.email_alerts import EmailAlertAdapter, EmlDirReader, ORIGINS, parse_alert
from mbos_discovery.auctions import place_coords
from mbos_discovery.dedup import title_similarity
from mbos_discovery.normalize import haversine_miles

from . import gazetteer, market_search as ms

ALERT_SOURCES = {"govdeals": ("govdeals_email", "GovDeals"), "publicsurplus": ("publicsurplus_email", "Public Surplus")}
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
)}                                     # later: blackmon (Proxibid)
ALL_HOUSES = "auctions"
ENV_WOOLEY = AUCTION_SITES["wooley"].env
WOOLEY_NAME = AUCTION_SITES["wooley"].name
EVENT_NAMES = {s.name for s in AUCTION_SITES.values()}
ENV_FLAG, ENV_DIR = "MBOS_STAGING_FIXTURES", "MBOS_MARKET_FIXTURE_MAIL_DIR"


def fixture_dir() -> str | None:
    """The .eml fixture directory, only when BOTH the isolated-staging flag and the directory are set; otherwise None (not connected)."""
    d = os.environ.get(ENV_DIR)
    return d if os.environ.get(ENV_FLAG) == "1" and d and Path(d).is_dir() else None


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


def _card(ad, rec, now, origin, name: str) -> dict | None:
    p = rec.payload
    try:
        n = ad.normalize(p, rec.fetched_at)
        facts, _ = parse_alert(ad.origin, p["email_source"].encode("utf-8"))
    except NormalizationError:
        return None                                   # spoofed / unauthenticated / foreign mail: quarantined, never shown
    d = n.normalized
    loc = d.get("location") or {}
    c = _coords(loc) if loc else None
    dist = haversine_miles(origin, c) if (c and origin) else None          # unrounded, as for GSA
    price = d.get("price") or {}
    amt = price.get("amount")
    bid = float(amt) if price.get("type") == "auction_current" and isinstance(amt, (int, float)) else None
    state = str(loc.get("state") or "").upper()
    desc = ms._short(d.get("description") or "")
    labels = ms.auction_labels({"highBidAmount": bid}, facts["date"])
    if bid is None:
        labels["opening_text"] = (f"Starting price ${amt:,.2f} (from the alert e-mail text; unverified)" if isinstance(amt, (int, float)) else "Price not stated in the alert — check original listing")
    return {"id": f"{ad.source}:{n.source_listing_id}", "title": d["title"], "description": desc, "text": f"{d['title']} {desc}".lower(), "url": n.url, "image": None,
            "bid": bid, "price": float(amt) if isinstance(amt, (int, float)) else None, "price_type": price.get("type"), "bidders": None,
            "closes": str(d.get("ends_at") or "")[:10] or None, "city": f"{loc['city']}, {loc['state']}" if loc.get("city") and loc.get("state") else None,
            "state": state if state in ms.US_STATES else None, "distance": dist, "category": n.category, "condition": None, "labels": labels, "source": name,
            "fetched_at": facts["date"], "kind": "auction", "stale": ms._age_h(facts["date"], now) > ms.STALE_H, "fixture": True}


def load_alerts(source: str, directory: str | None, now: datetime, origin=None) -> dict:
    """-> the `load_gsa` dict with status `fixture` (parser-backed .eml fixtures, not live) or `not_connected`. Never `connected`."""
    key, name = ALERT_SOURCES[source]
    if not directory:
        return not_connected(source)
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
            "url": g("rules_url"), "platform_url": g(site.platform_field), "platform": site.platform, "hibid_url": g("hibid_catalog_url"), "image": None, "bid": None,
            "price": None, "price_type": None, "bidders": None, "closes": day, "closes_at": closes_at, "begins_at": begins_at,
            "closes_local": local_when(closes_at), "left": _left(closes_at, now), "begins_local": local_when(begins_at),
            "city": f"{loc['city']}, {loc['state']}" if loc.get("city") and loc.get("state") else None,
            "state": loc.get("state") if loc.get("state") in ms.US_STATES else None, "distance": dist, "category": g("category"), "condition": None,
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
    """Merge across sources: the same source link, or near-identical title in the same place with the same close date, is one listing (first source wins). Two cards from the SAME source are never merged.
    lane 02's pinned install has no Deduper class; this uses its `dedup.title_similarity`."""
    out: list[dict] = []
    for c in cards:
        if not any(c.get("source") != k.get("source") and ((c["url"] and c["url"] == k["url"]) or (title_similarity(c["title"], k["title"]) >= 0.9 and c.get("city") == k.get("city") and c.get("closes") == k.get("closes"))) for k in out):
            out.append(c)
    return out


def coverage(parts: list[dict]) -> list[dict]:
    return [{k: d.get(k) for k in ("name", "status", "as_of", "age_h", "stale", "in_scope", "message")} for d in parts]


def load_source(source: str, gsa_path: str | None, now: datetime, origin=None, directory: str | None = None) -> dict:
    """Dispatch on the `source` filter: gsa | govdeals | publicsurplus | all. Other sources (eBay, Craigslist, Facebook Marketplace) are NOT CONNECTED."""
    directory = directory if directory is not None else fixture_dir()
    if source == "gsa":
        return ms.load_gsa(gsa_path, now, origin)
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
    cards = dedupe(gsa["cards"] + [c for h in houses for c in h["cards"]] + [c for a in alerts for c in a["cards"]])
    live = "connected" in [gsa["status"]] + [h["status"] for h in houses]
    status = "connected" if live else "fixture" if any(a["cards"] for a in alerts) else "offline"
    return {**gsa, "status": status, "cards": cards, "in_scope": len(cards), "fixture": any(a["fixture"] for a in alerts),
            "message": gsa["message"] if status == "offline" else "", "coverage": coverage([{**gsa, "name": "GSA Auctions"}] + houses + alerts)}
