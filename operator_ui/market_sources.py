"""F-145 (B-12 sub-step): the source seam for /market. `load_source` returns the SAME card shape as `market_search.load_gsa` from lane 02's
`EmailAlertAdapter` records over a read-only `EmlDirReader` (never IMAP here, no network, no login). An `.eml` fixture directory is
parser-backed but NOT a live read: it is served only on the isolated-staging flag and always labelled FIXTURE / not live. A source without a
real read stays NOT CONNECTED. Pure functions; everything is DRY-RUN."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from mbos_discovery.adapter import NormalizationError, SearchProfile
from mbos_discovery.adapters.email_alerts import EmailAlertAdapter, EmlDirReader, ORIGINS, parse_alert
from mbos_discovery.auctions import place_coords
from mbos_discovery.dedup import title_similarity
from mbos_discovery.normalize import haversine_miles

from . import gazetteer, market_search as ms

ALERT_SOURCES = {"govdeals": ("govdeals_email", "GovDeals"), "publicsurplus": ("publicsurplus_email", "Public Surplus")}
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


def dedupe(cards: list[dict]) -> list[dict]:
    """Merge across sources: the same source link, or near-identical title in the same place, is one listing (first source wins).
    lane 02's pinned install has no Deduper class; this uses its `dedup.title_similarity`."""
    out: list[dict] = []
    for c in cards:
        if not any((c["url"] and c["url"] == k["url"]) or (title_similarity(c["title"], k["title"]) >= 0.9 and c.get("city") == k.get("city")) for k in out):
            out.append(c)
    return out


def coverage(parts: list[dict]) -> list[dict]:
    return [{k: d.get(k) for k in ("name", "status", "as_of", "age_h", "stale", "in_scope", "message")} for d in parts]


def load_source(source: str, gsa_path: str | None, now: datetime, origin=None, directory: str | None = None) -> dict:
    """Dispatch on the `source` filter: gsa | govdeals | publicsurplus | all. Other sources (eBay, Craigslist, Facebook Marketplace) are NOT CONNECTED."""
    directory = directory if directory is not None else fixture_dir()
    if source == "gsa":
        return ms.load_gsa(gsa_path, now, origin)
    if source in ALERT_SOURCES:
        d = load_alerts(source, directory, now, origin)
        return {**d, "coverage": coverage([d])}
    if source != "all":
        return not_connected(source)
    gsa = ms.load_gsa(gsa_path, now, origin)
    alerts = [load_alerts(s, directory, now, origin) for s in ALERT_SOURCES]
    cards = dedupe(gsa["cards"] + [c for a in alerts for c in a["cards"]])
    live = gsa["status"] == "connected"
    status = "connected" if live else "fixture" if any(a["cards"] for a in alerts) else "offline"
    return {**gsa, "status": status, "cards": cards, "in_scope": len(cards), "fixture": any(a["fixture"] for a in alerts),
            "message": gsa["message"] if status == "offline" else "", "coverage": coverage([{**gsa, "name": "GSA Auctions"}] + alerts)}
