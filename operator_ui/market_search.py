"""F-47: Michael's Marketplace, the retrieval half. Reads lane 02's `GsaLiveAdapter` over the cached GSA file (no network: live=False)
and filters the lots. A retrieval view, not the decision queue: every result defaults to WATCH / RESEARCH NEEDED. Saved searches are
Wanted campaigns (wanted_view), not a second store. Pure functions; no write path. Everything is DRY-RUN.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mbos_discovery.adapter import SearchProfile
from mbos_discovery.auctions import UNKNOWN, place_coords
from mbos_discovery.gsa_live import GsaLiveAdapter, _text
from mbos_discovery.normalize import HOME_BASE, haversine_miles

DEFAULT_CACHE = "/home/michaelos/business-os-worktrees/agent-01-coordinator/var/cache/gsa-active-auctions.json"
SOURCES = {"gsa": "GSA Auctions"}
NOT_CONNECTED = ("GovDeals", "Public Surplus", "eBay", "Craigslist", "Facebook Marketplace")
SORTS = ("closing", "bid", "distance", "title")
CONDITIONS = ("", "new", "used", "salvage", "parts", "for parts", "not working", "working", "as is")
STALE_H = 6
EXCLUDE_PREFIX = "exclude:"            # saved inside the campaign's nice_to_have, the only free-text list the frozen schema allows
DEFAULT_BASE = "Conway AR"


def cache_path() -> str:
    return os.environ.get("MBOS_GSA_CACHE") or DEFAULT_CACHE


def _num(v, cap=10**7):
    try:
        x = float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None
    return x if 0 <= x <= cap else None


def _terms(raw) -> list[str]:
    return [w.strip().lower() for w in re.split(r"[,\n]", raw or "") if w.strip()][:12]


def parse_query(qs: dict) -> dict:
    """Query string / saved form -> a clean filter dict. Bad numbers become None (ignored), never an exception."""
    g = lambda k: (qs.get(k) or [""])[0].strip() if isinstance(qs.get(k), list) else str(qs.get(k) or "").strip()  # noqa: E731
    sort = g("sort")
    closing = g("closing_by")
    if closing == "soon":
        closing = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
    return {"keywords": g("keywords")[:120], "base": (g("base") or DEFAULT_BASE)[:60], "radius": _num(g("radius"), 3000),
            "max_price": _num(g("max_price")), "condition": g("condition").lower()[:30], "required": _terms(g("required")),
            "preferred": _terms(g("preferred")), "exclude": _terms(g("exclude")), "source": g("source") or "gsa",
            "kind": g("kind") or "any", "closing_by": closing if re.fullmatch(r"\d{4}-\d{2}-\d{2}", closing) else "",
            "sort": sort if sort in SORTS else "closing"}


def criteria_to_query(doc: dict) -> dict:
    """A saved campaign -> the filter dict it was saved from (exclude terms ride in nice_to_have as `exclude:word`)."""
    c = doc.get("criteria") or {}
    nice = c.get("nice_to_have") or []
    return {"keywords": ", ".join(c.get("keywords") or []), "base": c.get("origin") or DEFAULT_BASE,
            "radius": "" if c.get("radius_miles") is None else f"{c['radius_miles']:g}", "max_price": f"{c['max_price_usd']:g}" if "max_price_usd" in c else "",
            "required": ", ".join(c.get("must_have") or []),
            "preferred": ", ".join(t for t in nice if not t.startswith(EXCLUDE_PREFIX)),
            "exclude": ", ".join(t[len(EXCLUDE_PREFIX):] for t in nice if t.startswith(EXCLUDE_PREFIX))}


def _origin(base: str):
    if base.strip().lower() in ("", "conway", "conway ar", "conway, ar"):
        return HOME_BASE
    return place_coords({"city": re.sub(r"[, ]+(ar|arkansas)$", "", base.strip(), flags=re.I)})


def _short(s: str, n=280) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _card(adapter, rec, now, asof, origin) -> dict:
    lot = adapter.lot(rec.payload, now)
    p = rec.payload
    loc = lot.get("location") if isinstance(lot.get("location"), dict) else {}
    desc = _text(p.get("lotInfo"))
    c = place_coords(loc) if loc else None
    dist = round(haversine_miles(origin, c), 1) if (c and origin) else None      # grounded only: known place AND known base
    bid = lot.get("current_bid")
    return {"id": lot.lot_id, "title": lot.get("title"), "description": _short(desc), "text": f"{lot.get('title')} {desc}".lower(),
            "url": lot.get("rules_url") if lot.get("rules_url") != UNKNOWN else None, "image": p.get("imageURL") or None,
            "bid": bid if isinstance(bid, float) else None, "bidders": lot.get("bid_count"), "closes": str(p.get("aucEndDt") or "")[:10] or None,
            "city": f"{loc.get('city')}, {loc.get('state')}" if loc.get("city") else None, "distance": dist, "category": lot.get("category"),
            "condition": None, "source": "GSA Auctions", "fetched_at": asof, "kind": "auction", "stale": _age_h(asof, now) > STALE_H}


def _age_h(asof, now) -> float:
    try:
        return max(0.0, (now - datetime.fromisoformat(str(asof))).total_seconds() / 3600)
    except (TypeError, ValueError):
        return 10**6


def load_gsa(path: str | None = None, now: datetime | None = None, origin=HOME_BASE) -> dict:
    """-> {status: connected|offline, as_of, age_h, stale, in_file, in_scope, cards, message}. Offline when the cache is missing/unreadable."""
    now = now or datetime.now(timezone.utc)
    path = path or cache_path()
    out = {"status": "offline", "as_of": None, "age_h": None, "stale": False, "in_scope": 0, "cards": [], "message": ""}
    ad = GsaLiveAdapter(path, live=False)
    asof = ad._asof()
    if not Path(path).exists() or asof is None:
        out["message"] = "No cached GSA file with an as-of time is on this machine; nothing is shown rather than guessed."
        return out
    ad.clock = lambda: asof                       # the adapter's 1h refetch rule is for live use; this view never fetches
    res = ad.fetch(SearchProfile("market", "flip"))
    if res.error:
        out["message"] = f"GSA cache could not be read: {res.error.message}"
        return out
    cards = []
    for rec in res.records:
        try:
            cards.append(_card(ad, rec, now, asof.isoformat(), origin))
        except Exception:  # noqa: BLE001  one malformed lot never breaks the page
            continue
    age = _age_h(asof.isoformat(), now)
    return {**out, "status": "connected", "as_of": asof.isoformat(), "age_h": round(age, 1), "stale": age > STALE_H,
            "in_file": ad.summary.get("lots_in_file"), "in_scope": len(cards), "cards": cards}


def tag_terms(card: dict, q: dict) -> dict | None:
    """Required/preferred/exclude terms against the SELLER's text. A hit in the text is seller-stated; a match only on the system's
    own category guess is inferred. -> {"required": [(term, tag)], "preferred": [...]} or None when the lot is excluded."""
    text, cat = card["text"], (card.get("category") or "").lower()
    if any(t in text for t in q["exclude"]):
        return None
    tags = {"required": [], "preferred": []}
    for key in ("required", "preferred"):
        for t in q[key]:
            if t in text:
                tags[key].append((t, "seller-stated"))
            elif t and t in cat.replace("_", " "):
                tags[key].append((t, "inferred"))
            elif key == "required":
                return None
    return tags


def search(lots: list[dict], q: dict) -> tuple[list[dict], dict]:
    """Filter + sort. A lot with no bid keeps its place (bid UNKNOWN); distance unknown is kept and labelled. -> (cards, hidden counts)."""
    hidden = {"price": 0, "radius": 0, "terms": 0, "condition": 0, "closing": 0}
    out = []
    words = [w for w in re.split(r"\s+|,", q["keywords"].lower()) if w]
    for c in lots:
        if any(w not in c["text"] for w in words):
            hidden["terms"] += 1
            continue
        tags = tag_terms(c, q)
        if tags is None:
            hidden["terms"] += 1
        elif q["max_price"] is not None and c["bid"] is not None and c["bid"] > q["max_price"]:
            hidden["price"] += 1
        elif q["radius"] is not None and c["distance"] is not None and c["distance"] > q["radius"]:
            hidden["radius"] += 1
        elif q["condition"] and q["condition"] not in c["text"]:
            hidden["condition"] += 1
        elif q["closing_by"] and c["closes"] and c["closes"] > q["closing_by"]:
            hidden["closing"] += 1
        else:
            out.append({**c, "tags": tags})
    key = {"closing": lambda c: (c["closes"] or "9999", c["title"]), "bid": lambda c: (c["bid"] is None, c["bid"] or 0, c["title"]),
           "distance": lambda c: (c["distance"] is None, c["distance"] or 0, c["title"]), "title": lambda c: c["title"].lower()}[q["sort"]]
    return sorted(out, key=key), hidden


def decision(card: dict, comp: dict | None = None) -> tuple[str, str]:
    """-> (WATCH, why). This view never says BUY: an asking price or a current bid is not sold evidence, so without a grounded sold
    comp the answer is WATCH with RESEARCH NEEDED. Even with one, buying is the decision queue's job, not a search result's."""
    if not comp or comp.get("kind") != "sold" or not comp.get("n"):
        return "WATCH", "RESEARCH NEEDED: no sold-price evidence on file (a current bid or asking price is not a comp)"
    return "WATCH", "A sold comp exists; send it to the decision queue to judge. Search results never say BUY"
