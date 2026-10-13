"""F-47: Michael's Marketplace, the retrieval half. Reads lane 02's `GsaLiveAdapter` over the cached GSA file (no network: live=False)
and filters the lots. A retrieval view, not the decision queue: every result defaults to WATCH / RESEARCH NEEDED. Saved searches are
Wanted campaigns (wanted_view), not a second store. Pure functions; no write path. Everything is DRY-RUN.
"""

from __future__ import annotations

import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import landing_fix
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.auctions import UNKNOWN, place_coords
from . import gazetteer
from mbos_discovery.gsa_live import GsaLiveAdapter, _text
from mbos_discovery.normalize import haversine_miles

DEFAULT_CACHE = "/home/michaelos/business-os-worktrees/agent-01-coordinator/var/cache/gsa-active-auctions.json"
SOURCES = {"gsa": "GSA Auctions"}
NOT_CONNECTED = ("eBay", "Facebook Marketplace")
SORTS = ("closing", "new", "bid", "price_desc", "distance", "title", "suggested")      # F-159: closing = Ending soonest, new = Newest, bid = Price low to high
# F-52 (B): gallery row categories. Matched against the seller's text and the system's category guess; a row name is a label, not a claim.
ROW_CATS = {"trailers": ("trailer",), "equipment": ("equipment", "tractor", "mower", "loader", "generator", "compressor", "forklift", "backhoe"),
            "vehicles": ("truck", "pickup", "van", "suv", "sedan", "vehicle", "car"), "electronics": ("computer", "laptop", "monitor", "electronic", "phone", "radio", "camera", "printer", "server"),
            "tools": ("tool", "welder", "saw", "drill", "grinder", "wrench"),
            "lawn_garden": ("lawn", "garden", "tiller", "trimmer", "chainsaw", "blower", "mulcher", "sprayer"),
            "machinery": ("machinery", "excavator", "bulldozer", "dozer", "skid steer", "lathe", "crane", "grader", "paver", "roller", "hoist"),
            "pallets_wholesale": ("pallet", "wholesale", "bulk", "truckload", "liquidation"),
            "food_grocery": ("beef", "ground beef", "steak", "pork", "chicken", "meat", "butcher", "grocery", "produce", "food"),
            "restaurants": ("pizza", "restaurant", "meal", "lunch", "dinner", "breakfast", "takeout"),
            "fuel_auto": ("gas", "gasoline", "diesel", "fuel", "oil change", "tire rotation", "automotive service"),
            "entertainment": ("movie", "ticket", "cinema", "bowling", "museum", "admission", "event pass"),
            "retail_services": ("retail", "coupon", "service", "discount", "special", "membership", "day pass"),
            "land_real_estate": ("land", "acre", "real estate", "real property", "parcel", "house", "home", "residence", "residential", "cabin", "building lot", "commercial building")}
# F-157: owner-facing category controls. `other` = matches none of the named categories; `all` = every category incl. land. Land / Real Estate is off by default.
CAT_LABELS = {"tools": "Tools", "equipment": "Equipment", "trailers": "Trailers", "vehicles": "Vehicles", "lawn_garden": "Lawn & Garden", "machinery": "Machinery",
              "pallets_wholesale": "Pallets/Wholesale", "food_grocery": "Meat & Groceries", "restaurants": "Restaurants & Prepared Food",
              "fuel_auto": "Fuel & Automotive", "entertainment": "Entertainment & Tickets", "retail_services": "Retail & Local Services",
              "land_real_estate": "Land/Real Estate", "other": "Other/Unknown", "electronics": "Electronics"}
CONTROL_CATS = ("tools", "equipment", "trailers", "vehicles", "lawn_garden", "machinery", "pallets_wholesale", "food_grocery", "restaurants", "fuel_auto", "entertainment", "retail_services", "land_real_estate", "other")
# Michael's existing default stays resale-focused. Other users can select broader
# categories, and All categories genuinely includes every supported deal class.
DEFAULT_CATS = ("tools", "equipment", "trailers", "vehicles", "lawn_garden", "machinery", "pallets_wholesale", "other")
DEFAULT_ROWS = ("trailers", "equipment", "vehicles", "")
CONDITIONS = ("", "new", "used", "salvage", "parts", "for parts", "not working", "working", "as is")
STALE_H = 6
LTYPES = ("auction", "fixed", "event")      # F-159: Auction / Buy now or fixed price / Auction event
QUICK = ("new", "today", "soon", "saved")
PAGE_SIZE = 12
META = ("min:", "cat:", "rows:", "broad:", "cond:", "any:", "locmode:", "states:", "alsorad:")   # F-54: other saved-search criteria ride in nice_to_have the same way (the frozen schema has no field)
EXCLUDE_PREFIX = "exclude:"            # saved inside the campaign's nice_to_have, the only free-text list the frozen schema allows
# F-136: state names for the By State picker (50 states + DC). A lot's state is the 2-letter code the GSA cache gives; anything else stays unknown.
US_STATES = {"AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
             "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
             "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
             "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
             "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
             "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming"}
DEFAULT_RADIUS = 30.0                  # owner default around Conway; editable per user, not a budget
DEFAULT_ANY = "trailer, equipment"     # the default view: trailers/equipment; "broad" mode (explicit, off by default) drops this focus


def working_capital() -> float:
    """The documented working-capital planning setting (owner capital model: $500 protected principal). A setting, not verified cash."""
    v = _num(os.environ.get("MBOS_WORKING_CAPITAL_USD"))
    return 500.0 if v is None else v


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


def validate(g) -> list[str]:
    """F-52/F-53 (A), F-143: validate the typed numeric values (the price sliders are gone; obsolete min_r/max_r/prev_* query fields are ignored):
    a value that is present but not a usable number gets a visible message, and min above max is refused. Equal min and max is allowed."""
    errs, val = [], {}
    raw = g("radius")
    if raw != "" and _num(raw, landing_fix.MAX_RADIUS) is None:
        errs.append(f"Radius (miles) '{raw[:20]}' is not a usable number (0 to {landing_fix.MAX_RADIUS:,} miles, digits only); no search was run with it.")
    for k, box, label in (("min", "min_price", "Min price"), ("max", "max_price", "Max price")):
        raw = g(box)
        val[k] = _num(raw) if raw != "" else None
        if raw != "" and val[k] is None:
            errs.append(f"{label} '{raw[:20]}' is not a usable number (use 0 or more, digits only); no search was run with it.")
    if val["min"] is not None and val["max"] is not None and val["min"] > val["max"]:
        errs.append(f"Min price ${val['min']:,.0f} is higher than max price ${val['max']:,.0f}; nothing can match.")
    return errs


def _states(qs: dict) -> tuple[list[str], list[str]]:
    """-> (valid 2-letter codes in order, rejected tokens). Accepts repeated `state` values or one comma-joined value (saved forms)."""
    raw = qs.get("state")
    raw = raw if isinstance(raw, list) else [raw] if raw else []
    toks = [t.strip().upper() for r in raw for t in str(r).split(",") if t.strip()]
    good = list(dict.fromkeys(t for t in toks if t in US_STATES))
    return good, [t[:12] for t in dict.fromkeys(toks) if t not in US_STATES]


def _source_values(qs: dict) -> str:
    """Repeated source checkboxes -> canonical comma list; All wins and means every available source."""
    raw = qs.get("source")
    raw = raw if isinstance(raw, list) else [raw] if raw else []
    vals = [v.strip().lower() for item in raw for v in str(item).split(",") if re.fullmatch(r"[a-z0-9_]+", v.strip().lower())]
    vals = list(dict.fromkeys(vals))
    return "all" if not vals or "all" in vals else ",".join(vals)


def parse_query(qs: dict) -> dict:
    """Query string / saved form -> a clean filter dict. A bad number is None AND recorded in `errors` so the page says so."""
    g = lambda k: (qs.get(k) or [""])[0].strip() if isinstance(qs.get(k), list) else str(qs.get(k) or "").strip()  # noqa: E731
    sort = g("sort")
    closing = g("closing_by")
    if closing == "soon":
        closing = (datetime.now(timezone.utc) + timedelta(days=7)).strftime("%Y-%m-%d")
    raw = [x.strip() for c in (qs.get("cat") if isinstance(qs.get("cat"), list) else [qs.get("cat")] if qs.get("cat") else []) for x in str(c).split(",")]
    cat_all = "all" in raw
    cats = list(CONTROL_CATS) if cat_all else [c for c in dict.fromkeys(raw) if c in ROW_CATS or c == "other"]
    cat_default = not cats
    cats = cats or list(DEFAULT_CATS)
    rows = [g(f"row{i}") if g(f"row{i}") in ROW_CATS else "" for i in range(1, 5)] if any(f"row{i}" in qs for i in range(1, 5)) else list(DEFAULT_ROWS)
    fresh = not any(k in qs for k in ("keywords", "base", "radius", "max_price", "min_price", "any", "run", "edit", "cat", "state", "loc_mode"))
    states, bad_states = _states(qs)
    sources = _source_values(qs)
    mode = "state" if g("loc_mode") == "state" else "distance"
    radius_used = (mode == "distance" or g("also_radius") == "1") and g("radius") != ""
    errs = validate(g) + (["Enter your ZIP or city (the origin the radius is measured from); no search was run without it."] if radius_used and not g("base") else []) + [f"'{t}' is not a US state code; it was ignored and no search was run with it." for t in bad_states] \
        + (["By State is selected but no state is ticked; pick at least one state (or switch to By Distance). No search was run."] if mode == "state" and not states and not bad_states else [])
    return {"loc_mode": mode, "states": states, "also_radius": g("also_radius") == "1", "state_find": g("state_find")[:30], "cat_find": g("cat_find")[:30], "keywords": g("keywords")[:120], "base": g("base")[:60],
            "radius": (DEFAULT_RADIUS if g("base") else None) if fresh else _num(g("radius"), landing_fix.MAX_RADIUS),
            "min_price": _num(g("min_price")), "max_price": _num(g("max_price")), "errors": errs, "cats": cats, "cat_all": cat_all, "cat_default": cat_default, "rows": rows,
            "view": "list" if g("view") == "list" else "gallery",
            "any": _terms(DEFAULT_ANY if ("any" not in qs and not g("broad")) else g("any")), "broad": g("broad") == "1", "condition": g("condition").lower()[:30], "required": _terms(g("required")),
            "preferred": _terms(g("preferred")), "exclude": _terms(g("exclude")), "source": sources,
            "ltype": g("ltype") if g("ltype") in LTYPES else "", "quick": g("quick") if g("quick") in QUICK else "", "page": max(1, int(g("page"))) if g("page").isdigit() and int(g("page")) < 10**6 else 1,
            "kind": g("kind") or "any", "closing_by": closing if re.fullmatch(r"\d{4}-\d{2}-\d{2}", closing) else "",
            "sort": sort if sort in SORTS else "closing"}


def criteria_to_query(doc: dict) -> dict:
    """A saved campaign -> the filter dict it was saved from (exclude terms ride in nice_to_have as `exclude:word`)."""
    c = doc.get("criteria") or {}
    nice = c.get("nice_to_have") or []
    meta = {t[: t.index(":") + 1]: t[t.index(":") + 1:] for t in nice if t.startswith(META)}
    out = {"keywords": ", ".join(c.get("keywords") or []), "base": c.get("origin") or "",
           "radius": "" if c.get("radius_miles") is None else f"{c['radius_miles']:g}", "any": ", ".join(t for t in meta.get("any:", "").split(">") if t),   # F-59: always present, so an empty focus stays empty (never falls back to the default focus)
           "max_price": f"{c['max_price_usd']:g}" if "max_price_usd" in c else "",
           "required": ", ".join(c.get("must_have") or []),
           "preferred": ", ".join(t for t in nice if not t.startswith(EXCLUDE_PREFIX) and not t.startswith(META)),
           "exclude": ", ".join(t[len(EXCLUDE_PREFIX):] for t in nice if t.startswith(EXCLUDE_PREFIX))}
    if "min:" in meta:
        out["min_price"] = meta["min:"]
    if meta.get("cat:"):
        out["cat"] = meta["cat:"].split(">")
    if meta.get("rows:"):
        out.update({f"row{i}": r for i, r in enumerate(meta["rows:"].split(">"), 1) if i <= 4})
    if meta.get("broad:") == "1":
        out["broad"] = "1"
    if meta.get("cond:"):
        out["condition"] = meta["cond:"]
    if meta.get("states:"):
        out["state"] = meta["states:"].split(">")
    if meta.get("locmode:") == "state":
        out["loc_mode"] = "state"
    if meta.get("alsorad:") == "1":
        out["also_radius"] = "1"
    return out


def _origin(base: str):
    if not base.strip():
        return None                                   # F-143: no hidden fallback origin; the user's own origin is required
    return landing_fix.parse_origin(base) or place_coords({"city": re.sub(r"[, ]+(ar|arkansas)$", "", base.strip(), flags=re.I)})


def _short(s: str, n=280) -> str:
    s = " ".join((s or "").split())
    return s if len(s) <= n else s[: n - 1].rstrip() + "…"


def _amt(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v >= 0 else None


OPENING_MIN_FIELDS = ("openingBidAmount", "minBidAmount", "startingBidAmount")     # A-62: explicit source fields only; none is known to exist in the GSA cache today


def auction_labels(p: dict, asof=None) -> dict:
    """F-61/F-137: current bid, ESTIMATED next bid and reserve, only from GSA fields in the cache (`highBidAmount`, `aucIncrement`, `reserve`).
    Estimated next bid = cached current bid + cached `aucIncrement`, only when both are finite (as of the cache time; the live minimum is unverified and
    is never stated as the minimum). No bid: UNKNOWN, the opening minimum is not in the cache. Reserve is Yes / No / Unknown; Yes reads 'reserve amount undisclosed'.
    Never a floor from retail price or the estimate."""
    bid, inc, r = _amt(p.get("highBidAmount")), _amt(p.get("aucIncrement")), p.get("reserve")
    r = r.strip().lower() if isinstance(r, str) else r
    reserve = "Yes" if r is True or r in ("yes", "true", "y") else "No" if r is False or r in ("no", "false", "n") else "Unknown"
    nxt = _amt(bid + inc) if bid is not None and inc is not None else None
    when = f"as of cached {asof}" if asof else "as of the cache time (unstamped)"
    if nxt is not None:
        nxt_txt = f"ESTIMATED ${nxt:,.2f} (cached current bid + ${inc:,.2f} increment, {when}; live minimum unverified)"
    elif bid is None:
        nxt_txt = "UNKNOWN (no bid yet; the opening minimum is not in the GSA cache; live minimum unverified" + (f"; cached bid increment ${inc:,.2f}" if inc is not None else "") + ")"
    else:
        nxt_txt = "UNKNOWN (the GSA cache has no usable bid increment for this lot: field aucIncrement; live minimum unverified)"
    res_txt = {"Yes": "Yes, reserve amount undisclosed (the GSA cache has no reserve amount field)", "No": "No",
               "Unknown": "UNKNOWN (the GSA cache has no usable reserve field for this lot: field reserve)"}[reserve]
    opening, ofield = None, None
    if bid is None:                  # A-62: never 0, aucIncrement, retail, reserve or a guess; only an explicit positive source field
        for f in OPENING_MIN_FIELDS:
            v = _amt(p.get(f))
            if v is not None and v > 0:
                opening, ofield = v, f
                break
    open_txt = (f"Opening/minimum bid ${opening:,.2f} (source field {ofield}, {when}; live rules unverified)" if opening is not None
                else "Opening/minimum bid unknown \u2014 check original listing" if bid is None else "")
    return {"current_bid": bid, "est_next_bid": nxt, "next_min_text": nxt_txt, "reserve": reserve, "reserve_text": res_txt, "asof": asof,
            "opening_min": opening, "opening_field": ofield, "opening_text": open_txt}


def _card(adapter, rec, now, asof, origin) -> dict:
    lot = adapter.lot(rec.payload, now)
    p = rec.payload
    loc = lot.get("location") if isinstance(lot.get("location"), dict) else {}
    desc = _text(p.get("lotInfo"))
    c = place_coords(loc) if loc else None
    if c is None and loc:                                              # F-150: lane 02's table is small; fall back to the Census gazetteer (ZIP first, then 'City, ST')
        c = gazetteer.locate(loc.get("zip")) or (gazetteer.locate(f"{loc.get('city')}, {loc.get('state')}") if loc.get("city") and loc.get("state") else None)
    dist = haversine_miles(origin, c) if (c and origin) else None      # grounded only; UNROUNDED: the radius test uses it, only the display rounds (F-54)
    bid = lot.get("current_bid")
    return {"id": lot.lot_id, "title": lot.get("title"), "description": _short(desc), "text": f"{lot.get('title')} {desc}".lower(),
            "url": lot.get("rules_url") if lot.get("rules_url") != UNKNOWN else None, "image": p.get("imageURL") or None,
            "bid": bid if isinstance(bid, float) else None, "bidders": lot.get("bid_count"), "closes": str(p.get("aucEndDt") or "")[:10] or None,
            "city": f"{loc.get('city')}, {loc.get('state')}" if loc.get("city") else None,
            "state": str(loc.get("state")).strip().upper() if str(loc.get("state") or "").strip().upper() in US_STATES else None,   # F-136: only a real 2-letter code from the cache; else unknown
            "zip": re.sub(r"\D", "", str(loc.get("zip") or ""))[:5] or None, "posted": str(p.get("aucStartDt") or "")[:10] or None,      # F-159: ZIP for the card, listing start date for Newest / New today
             "distance": dist, "category": lot.get("category"),
            "condition": None, "labels": auction_labels(p, asof), "source": "GSA Auctions", "fetched_at": asof, "kind": "auction", "stale": _age_h(asof, now) > STALE_H}


def _age_h(asof, now) -> float:
    try:
        return max(0.0, (now - datetime.fromisoformat(str(asof))).total_seconds() / 3600)
    except (TypeError, ValueError):
        return 10**6


def load_gsa(path: str | None = None, now: datetime | None = None, origin=None) -> dict:
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


def load_source(source: str, now: datetime | None = None, origin=None, path: str | None = None, directory: str | None = None,
                query: dict | None = None) -> dict:
    """Source-agnostic card loader, including the Bright Data Facebook cache, in the common marketplace card shape."""
    from . import market_sources
    return market_sources.load_source(source, path, now or datetime.now(timezone.utc), origin, directory, query)


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


def _price_ok(c: dict, q: dict):
    """True / False against the min/max range, or None when the lot has no bid yet (price unknown: cannot be tested)."""
    if q.get("min_price") is None and q.get("max_price") is None:
        return True
    if c.get("event"):
        return False           # F-146 rule: an auction EVENT has no price at all, so any min/max price filter excludes it (counted under 'hidden by price')
    amt = c["bid"] if c["bid"] is not None else c.get("price") if c.get("price_type") == "fixed" else None     # F-161: a stated asking price is testable
    if amt is None:
        return None
    return (q.get("min_price") is None or amt >= q["min_price"]) and (q["max_price"] is None or amt <= q["max_price"])


def search(lots: list[dict], q: dict) -> tuple[list[dict], dict]:
    """The checked results and the hidden counts (see `partition` for the lots that could not be checked)."""
    res, _, hidden = partition(lots, q)
    return res, hidden


def partition(lots: list[dict], q: dict) -> tuple[list[dict], list[dict], dict]:
    """Filter + sort -> (checked results, unchecked, hidden counts). A lot whose distance (radius set) or price (price range set) is
    unknown cannot be tested, so it goes to `unchecked` with its reasons and is never counted as local or in range."""
    hidden = {"price": 0, "radius": 0, "terms": 0, "condition": 0, "closing": 0, "rentals": 0}
    by_state = q.get("loc_mode") == "state"
    radius_on = q["radius"] is not None and (not by_state or q.get("also_radius"))      # F-136: By State does not apply the radius unless the owner also ticks it (shown on the page)
    if by_state:
        hidden["state"] = 0
    out, unchecked = [], []
    words = [w for w in re.split(r"\s+|,", q["keywords"].lower()) if w]
    wants_rentals = any(w in {"rent", "rental", "rentals"} for w in words)
    for c in lots:
        title = c.get("title") or ""
        rental = bool(re.search(r"\b(?:for\s+rent|rentals?|rent\s+me|daily\s+rent|weekly\s+rent)\b|\$\s*\d+(?:\.\d+)?\s*/\s*(?:day|week)", title, re.I))
        if rental and not wants_rentals:
            hidden["rentals"] += 1
            continue
        if any(w not in c["text"] for w in words):
            hidden["terms"] += 1
            continue
        tags = tag_terms(c, q)
        if q.get("cat_all"):
            focus = False
        elif q.get("cats") and not (q.get("any") and q["any"] != _terms(DEFAULT_ANY) and not q.get("broad")):
            focus = not cat_ok(c, q["cats"])          # F-157: the ticked categories control the feed; pure land is hidden when Land/Real Estate is off, mixed lots stay
        else:
            focus = q.get("any") and not q.get("broad") and not any(t in c["text"] or t in (c.get("category") or "").lower().replace("_", " ") for t in q["any"])
        pok = _price_ok(c, q)
        if tags is None or focus:
            hidden["terms"] += 1
        elif pok is False:
            hidden["price"] += 1
        elif by_state and c.get("state") is not None and c["state"] not in q["states"]:
            hidden["state"] += 1
        elif radius_on and c["distance"] is not None and c["distance"] > q["radius"]:
            hidden["radius"] += 1
        elif q["condition"] and q["condition"] not in c["text"]:
            hidden["condition"] += 1
        elif q["closing_by"] and c["closes"] and c["closes"] > q["closing_by"]:
            hidden["closing"] += 1
        else:
            why = (["state not known (not in the cache)"] if by_state and c.get("state") is None else []) + (["location not found (distance unknown)"] if radius_on and c["distance"] is None else []) + (["no bid yet (price unknown)"] if pok is None else [])
            (unchecked if why else out).append({**c, "tags": tags, "unchecked": why})
    key = {"closing": lambda c: (c["closes"] or "9999", c["title"]), "bid": lambda c: (c["bid"] is None, c["bid"] or 0, c["title"]),
           "distance": lambda c: (c["distance"] is None, c["distance"] or 0, c["title"]), "title": lambda c: c["title"].lower(), "suggested": lambda c: (c["closes"] or "9999", c["title"]), "new": None, "price_desc": None}[q["sort"]]
    return order(out, q["sort"], key), order(unchecked, q["sort"], key), hidden


def order(rows: list[dict], sort: str, key) -> list[dict]:
    """F-159: Newest (listing start date, unknown last) and Price high to low (no bid last) need a descending key; the rest use the ascending key."""
    if sort == "new":
        base = sorted(rows, key=lambda c: c["title"].lower())
        return sorted([c for c in base if c.get("posted")], key=lambda c: c["posted"], reverse=True) + [c for c in base if not c.get("posted")]
    if sort == "price_desc":
        base = sorted(rows, key=lambda c: c["title"].lower())
        return sorted([c for c in base if c["bid"] is not None], key=lambda c: c["bid"], reverse=True) + [c for c in base if c["bid"] is None]
    return sorted(rows, key=key)


def decision(card: dict, comp: dict | None = None) -> tuple[str, str]:
    """-> (WATCH, why). This view never says BUY: an asking price or a current bid is not sold evidence, so without a grounded sold
    comp the answer is WATCH with RESEARCH NEEDED. Even with one, buying is the decision queue's job, not a search result's."""
    if not comp or comp.get("kind") != "sold" or not comp.get("n"):
        return "WATCH", "RESEARCH NEEDED: no sold-price evidence on file (a current bid or asking price is not a comp)"
    return "WATCH", "A sold comp exists; send it to the decision queue to judge. Search results never say BUY"


def card_cats(c: dict) -> set[str]:
    """F-157: every category a lot matches (title + category guess); `other` is added when it matches no control category."""
    got = {k for k in ROW_CATS if in_cat(c, k)}
    if "land_real_estate" in got and in_cat(c, "land_real_estate", title_only=True):      # F-158: a land/real-estate TITLE is the seller's word; the system guess (e.g. commercial_equipment) must not keep it
        got = {k for k in ROW_CATS if in_cat(c, k, title_only=True)}
    return got if got & set(CONTROL_CATS) else got | {"other"}


def cat_ok(c: dict, selected) -> bool:
    return bool(card_cats(c) & set(selected))


def in_cat(c: dict, cat: str, title_only: bool = False) -> bool:
    if cat == "other":
        return "other" in card_cats(c)
    text = (c["title"] if title_only else f"{c['title']} {c.get('category') or ''}").lower().replace("_", " ")          # title + category guess: the long description is boilerplate
    if cat == "land_real_estate":
        text = re.sub(r"\bland rover\b|\bhome depot\b|\bhomemade\b", " ", text)
    if cat == "land_real_estate" and re.search(r"\bbuilding\b", text) and re.search(r"\bauction\b", text):       # F-158: 'commercial building' / 'building ... auction' titles are property
        return True
    return any(re.search(rf"\b{re.escape(t)}s?\b", text) for t in ROW_CATS[cat])


def gallery_rows(cards: list[dict], q: dict) -> list[tuple[str, list[dict]]]:
    """F-52 (B): the owner's chosen rows (checked categories first, else row slots) then 'other'. A lot sits in the first row it matches.
    An empty chosen row is kept, so the page can say 'no matching known inventory' instead of hiding the row."""
    chosen = [] if q.get("cat_all") or q.get("cat_default") else list(q.get("cats", []))
    names = [n for n in dict.fromkeys(chosen or [r for r in q.get("rows", DEFAULT_ROWS) if r])]
    events = [c for c in cards if c.get("event")]                    # F-149: auction events never sit in a guessed lot row
    cards = [c for c in cards if not c.get("event")]
    seen, out = set(), []
    for n in names:
        row = [c for c in cards if c["id"] not in seen and in_cat(c, n)]
        seen |= {c["id"] for c in row}
        out.append((n, row))
    rest = [c for c in cards if c["id"] not in seen]
    return out + ([("auction events", events)] if events else []) + ([("other", rest)] if rest else [])
