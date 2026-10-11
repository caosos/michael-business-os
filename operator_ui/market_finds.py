"""F-141: OWNER-ENTERED finds (Facebook Marketplace, Craigslist, OfferUp, other). The owner pastes what they saw; the system NEVER fetches, scrapes,
logs into or automates those sites (their terms forbid it; no credentials). The link is stored as text and is never requested by this code.
Persisted in one owner-local JSON file next to market_prefs.json (MBOS_MARKET_FINDS_FILE overrides); atomic write; soft delete with undo; audit fields.
Cards are shaped like the GSA cards so market_search.partition applies the same strict filters. No network import here. Everything is DRY-RUN."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import gazetteer
from . import market_prefs as mp
from . import market_search as ms
from mbos_discovery.normalize import haversine_miles

SOURCES = {"facebook": "Facebook Marketplace", "craigslist": "Craigslist", "offerup": "OfferUp", "other": "Other site"}
ACTIONS = ("add", "edit", "delete", "undo")
WHO = "owner (Operator UI)"
MAX_PRICE = 10**7
ID_RE = re.compile(r"^own:(facebook|craigslist|offerup|other):[0-9a-f]{12}$")


def path() -> Path:
    return Path(os.environ.get("MBOS_MARKET_FINDS_FILE") or mp.path().parent / "market_finds.json")


def load() -> dict:
    try:
        d = json.loads(path().read_text())
    except (OSError, ValueError):
        return {}
    f = d.get("finds") if isinstance(d, dict) else None
    return {k: v for k, v in f.items() if ID_RE.match(k) and isinstance(v, dict)} if isinstance(f, dict) else {}


def _store(finds: dict) -> None:
    p = path()
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p.parent)
    with os.fdopen(fd, "w") as fh:
        json.dump({"version": 1, "finds": finds}, fh, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, p)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _norm_link(link: str) -> str:
    u = urlsplit(link)
    return f"{u.scheme.lower()}://{(u.hostname or '').lower()}{u.path.rstrip('/')}"      # tracking query/fragment dropped for the duplicate key


def find_id(source: str, link: str, title: str, loc: str) -> str:
    key = _norm_link(link) if link else " ".join(f"{title}|{loc}".lower().split())
    return f"own:{source}:{hashlib.sha256(key.encode()).hexdigest()[:12]}"


def validate(f: dict) -> tuple[dict, list[str]]:
    """-> (clean fields, errors). The link is checked as TEXT (http/https shape only); nothing is ever requested."""
    g = lambda k: " ".join(str(f.get(k) or "").split())  # noqa: E731
    errs, link = [], str(f.get("link") or "").strip()
    if link and (len(link) > 500 or re.search(r"\s", link) or urlsplit(link).scheme not in ("http", "https") or not urlsplit(link).hostname):
        errs.append("Link must be one http(s) address with no spaces (up to 500 characters). It is saved as text only and never opened by this system.")
    title = g("title")[:120]
    if not title:
        errs.append("Title is required.")
    source = g("source").lower()
    if source not in SOURCES:
        errs.append("Choose a source: facebook, craigslist, offerup or other.")
    price = None
    if g("price"):
        price = ms._num(g("price"), MAX_PRICE)
        if price is None:
            errs.append(f"Price '{g('price')[:20]}' is not a usable number (0 or more, digits only); leave it empty if unknown.")
    cond = g("condition").lower()
    if cond not in ms.CONDITIONS:
        errs.append("Condition is not one of the listed choices.")
    loc = g("location")[:60]
    if not loc:
        errs.append("Location (City, ST or ZIP) is required. One our small local gazetteer does not know is accepted and shows as unknown.")
    return {"link": link, "title": title, "source": source, "price": price, "condition": cond, "location": loc, "notes": str(f.get("notes") or "").strip()[:600]}, errs


def act(action: str, f: dict) -> str:
    if action not in ACTIONS:
        raise ValueError("unknown find action")
    finds, now = load(), _now()
    if action in ("delete", "undo"):
        fid = str(f.get("find") or "")
        if fid not in finds:
            raise ValueError("That find does not exist.")
        r = finds[fid]
        if action == "delete":
            finds[fid] = {**r, "deleted": True, "deleted_by": WHO, "deleted_at": now}
        else:
            finds[fid] = {**r, "deleted": False, "undeleted_by": WHO, "undeleted_at": now}
        _store(finds)
        return "Find deleted. Undo it from 'Deleted finds' below." if action == "delete" else "Find restored."
    clean, errs = validate(f)
    if errs:
        raise ValueError(" ".join(errs))
    fid = find_id(clean["source"], clean["link"], clean["title"], clean["location"])
    if action == "add":
        if fid in finds:
            raise ValueError("Already in your finds" + (" (deleted: undo it from 'Deleted finds')." if finds[fid].get("deleted") else ". Edit it instead; no duplicate was added."))
        finds[fid] = {**clean, "id": fid, "created_by": WHO, "created_at": now, "updated_by": WHO, "updated_at": now, "deleted": False}
        msg = "Find added (owner-entered, not fetched, unverified)."
    else:
        old_id = str(f.get("find") or "")
        if old_id not in finds:
            raise ValueError("That find does not exist.")
        if fid != old_id and fid in finds:
            raise ValueError("Those details match another find already in your list; no change was made.")
        r = finds.pop(old_id)       # the id follows the link/title/place; the record keeps the earlier id
        finds[fid] = {**r, **clean, "id": fid, "former_id": old_id if fid != old_id else r.get("former_id"), "updated_by": WHO, "updated_at": now}
        msg = "Find updated." + (" It now has a new id, so earlier Save/Hide choices on the old id no longer apply." if fid != old_id else "")
    _store(finds)
    return msg


def state_of(loc: str) -> str | None:
    m = re.search(r"[, ]\s*([A-Za-z]{2})$", loc.strip())
    code = m.group(1).upper() if m else None
    return code if code in ms.US_STATES else None


def card(r: dict, origin) -> dict:
    """A find shaped like a GSA card so `ms.partition` filters it identically. A location that does not resolve -> distance None (unknown, never counted as local)."""
    pt = gazetteer.locate(r.get("location"))
    text = " ".join(str(r.get(k) or "") for k in ("title", "notes", "condition", "location")).lower()
    return {"id": r["id"], "title": r["title"], "description": r.get("notes") or "", "text": text, "url": r.get("link") or None, "image": None, "bid": r.get("price"),
            "bidders": None, "closes": None, "city": r.get("location"), "state": state_of(r.get("location", "")), "distance": haversine_miles(origin, pt) if (pt and origin) else None,
            "category": None, "condition": r.get("condition") or None, "labels": ms.auction_labels({}), "source": SOURCES[r["source"]], "source_key": r["source"],
            "fetched_at": r.get("created_at"), "kind": "owner-entered", "stale": False, "find": r}


def cards(q: dict, prefs: dict) -> tuple[list[dict], list[dict], list[dict], int, int]:
    """-> (checked results, unchecked, deleted records, hidden-by-you count, hidden-by-filters count). Same hard filters as GSA via ms.partition; Hide/Save through the prefs ids."""
    finds = load()
    live = [card(r, ms._origin(q["base"])) for r in finds.values() if not r.get("deleted")]
    gone = sorted((r for r in finds.values() if r.get("deleted")), key=lambda r: r.get("deleted_at", ""), reverse=True)
    res, unch, byf = ms.partition(live, q)
    res, g1 = mp.hide(res, prefs)
    unch, g2 = mp.hide(unch, prefs)
    if prefs.get("enabled"):
        res, _ = mp.rank(res, prefs, lambda c: (c["title"],), False)
    return res, unch, gone, g1 + g2, sum(byf.values())
