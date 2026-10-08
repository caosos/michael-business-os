"""Campaign matcher — READY_QUEUE B-20 (ADR-0013 §5; contract `campaign.schema.json`, A-26).

A campaign is standing demand ("a 5x8 utility trailer within 40 miles, max $600, cosmetics ignored"). This module is
READ-ONLY: it compares normalized Items against a campaign and RECOMMENDS. It contacts nobody, bids on nothing, and
buys nothing; every action still needs an ActionRequest and Michael's approval.

THE GATE (policy, not convenience): only `autonomy.level` WATCH_ONLY or RECOMMEND with `status` ACTIVE may run
(`mbos.campaign.may_run`). ASSISTED_DEAL and BOUNDED_AUTOPILOT are REFUSED before any matching or request, as are
paused / fulfilled / expired / cancelled campaigns and an invalid document. `campaign_profile()` returns None for a
refused campaign, so a runner never builds a search for it.

Matching (every statement in `why` is derived from the Item's own fields; nothing is guessed):
* HARD criteria: category, keywords, must_have, max price, radius, and the listing being active. Unknown ≠ met: an
  Item whose price or distance cannot be established is NOT a match (it is reported as `unknown`).
* SOFT criteria: nice_to_have; they only affect rank. `title` is a known soft term (clean title evidence).
* Cosmetics: with `cosmetics_matter: false` cosmetic wording (paint, dents, scratches, faded, rust spots, …) is ignored
  entirely: it can neither exclude an Item nor change its rank. With `true`, stated cosmetic defects are a soft miss.
* Text is untrusted: a title/description field containing instruction-like text is excluded from matching entirely
  (same rule as category tags), so an injected "5x8 utility trailer" cannot create a match.
* Distance: road miles if RESEARCH set them; else straight-line from lat/lng to the origin; else the geo ring from
  Conway as a bound (ring 0 ⇒ ≤ 35 mi, ring 1 ⇒ 35–100 mi). Only a bound that settles the question counts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from . import AGENT_ID, NORMALIZER_VERSION, __version__
from .adapter import SearchProfile
from .contract import check_provenance
from .ids import derived_ulid, iso, parse_ts, sha256_ref, canonical_json
from .normalize import HOME_BASE, haversine_miles
from .tags import sanitize

TOOL_NAME = "mbos_discovery.campaigns"
RUNNABLE = ("WATCH_ONLY", "RECOMMEND")
RING_BOUNDS = {0: (0.0, 35.0), 1: (35.0, 100.0), 2: (100.0, 160.0), 3: (160.0, 320.0)}
HOME_ORIGINS = {"", "home", "72034", "conway", "conway, ar", "conway ar"}
_COSMETIC = re.compile(
    r"\b(?:faded|chipped|peeling|scratch(?:es|ed)?|scuff(?:s|ed)?|dent(?:s|ed)?|dinged|dings?|surface\s+rust|rust\s+spots?|"
    r"needs?\s+(?:a\s+)?(?:paint|repaint|cleaning|wash|detail)|paint\s+(?:is\s+)?(?:faded|chipped|peeling|worn)|"
    r"cosmetic(?:ally)?(?:\s+(?:flaws?|issues?|damage|wear))?|sun[\s-]?faded|weathered)\b", re.IGNORECASE)
_TITLE_OK = re.compile(r"\b(?:clean|clear|good|valid|free\s+and\s+clear|bill\s+of\s+sale\s+and)\s+title\b|\btitle\s+(?:in\s+hand|in\s+my\s+name|available|ready)\b|"
                       r"\b(?:has|with|have)\s+(?:a\s+)?title\b|\btitled\b", re.IGNORECASE)
_TITLE_BAD = re.compile(r"\b(?:no|without|lost|missing|salvage|rebuilt|junk)\s+title\b|\bbill\s+of\s+sale\s+only\b|\btitle\s+(?:is\s+)?(?:lost|missing|not\s+available)\b", re.IGNORECASE)


# ---------------------------------------------------------------- the gate
def refusal(doc: Any, as_of: datetime) -> Optional[str]:
    """Why this campaign must not run, or None. Checked before anything else; makes no request."""
    from mbos import campaign as C
    errs = C.errors(doc)
    if errs:
        return "invalid campaign: " + "; ".join(errs[:3])
    level, status = doc["autonomy"]["level"], doc["status"]
    if level not in RUNNABLE:
        return f"autonomy {level} is refused in this release (only {', '.join(RUNNABLE)} may run)"
    if not C.may_run(doc):
        return f"status {status} (only ACTIVE campaigns run)"
    exp = (doc.get("stop_conditions") or {}).get("expires_at")
    if exp and parse_ts(exp) <= as_of:
        return f"campaign expired at {exp}"
    return None


def campaign_profile(doc: dict, as_of: datetime) -> Optional[SearchProfile]:
    """Search parameters a runner could hand to adapters, or None if the campaign is refused (then no request is built)."""
    if refusal(doc, as_of):
        return None
    c = doc["criteria"]
    lane = "service" if c["category"] in ("mobile_repair", "equipment_repair", "drywall_repair", "assembly", "handyman",
                                           "smart_home_install", "technical_service", "mechanical_service", "other_service") else "flip"
    kws = tuple(c.get("keywords") or ()) or (c["category"],)
    return SearchProfile(f"campaign-{doc['campaign_id'][-8:].lower()}", lane, (" ".join(kws),),
                         radius_miles=int(c["radius_miles"] or 100), max_price=c["max_price_usd"])


# ---------------------------------------------------------------- text and distance helpers
def _kw_regex(kw: str) -> re.Pattern:
    """Word-bounded, case-insensitive. A size like 5x8 also matches "5 x 8", "5'x8'", "5×8", "5 by 8"."""
    k = kw.strip().lower()
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)", k)
    if m:
        a, b = m.groups()
        return re.compile(rf"(?<![\d.]){re.escape(a)}\s*(?:'|ft|feet|foot|’)?\s*(?:x|×|\*|by)\s*{re.escape(b)}(?![\d.])", re.IGNORECASE)
    return re.compile(r"(?<![a-z0-9])" + re.sub(r"\\ ", r"[\\s\\-]+", re.escape(k)) + r"(?![a-z0-9])", re.IGNORECASE)


def _texts(item: dict) -> tuple[dict[str, str], list[str]]:
    n = item.get("normalized") or {}
    fields, excluded = {}, []
    for f in ("title", "description"):
        t, flagged = sanitize(n.get(f))
        if flagged:
            excluded.append(f)
        elif t:
            fields[f] = t
    return fields, excluded


def _find(rx: re.Pattern, fields: dict[str, str]) -> Optional[str]:
    for f, t in fields.items():
        m = rx.search(t)
        if m:
            return f"{f}: “{t[max(0, m.start() - 10): m.end() + 10].strip()}”"
    return None


def _origin_coords(origin: Optional[str]) -> Optional[tuple[float, float]]:
    return HOME_BASE if (origin or "").strip().lower() in HOME_ORIGINS else None


def distance(item: dict, origin: Optional[str]) -> dict:
    """{"lower", "upper", "basis", "note"}; lower/upper None when nothing settles it."""
    loc = (item.get("normalized") or {}).get("location") or {}
    if loc.get("road_miles_one_way") is not None:
        d = float(loc["road_miles_one_way"])
        return {"lower": d, "upper": d, "basis": "road miles (RESEARCH)", "note": f"{d:g} road miles one way"}
    org = _origin_coords(origin)
    if org is None:
        return {"lower": None, "upper": None, "basis": "unknown",
                "note": f"origin {origin!r} cannot be located (no geocoder); distance unknown"}
    if loc.get("lat") is not None and loc.get("lng") is not None:
        d = round(haversine_miles(org, (loc["lat"], loc["lng"])), 1)
        return {"lower": d, "upper": d, "basis": "straight-line", "note": f"{d:g} miles straight-line from the origin"}
    tier = loc.get("geo_tier")
    if tier in RING_BOUNDS:
        lo, hi = RING_BOUNDS[tier]
        return {"lower": lo, "upper": hi, "basis": "geo ring", "note": f"geo ring {tier}: {lo:g}–{hi:g} miles from Conway"}
    return {"lower": None, "upper": None, "basis": "unknown", "note": "the listing gives no usable location"}


# ---------------------------------------------------------------- evaluation
def evaluate(doc: dict, item: dict) -> dict:
    """One Item against one campaign. Pure."""
    c = doc["criteria"]
    n = item.get("normalized") or {}
    met, missed, unknown, soft_met = [], [], [], []
    fields, excluded = _texts(item)

    if (item.get("category") or "").lower() == c["category"].lower():
        met.append({"criterion": "category", "detail": f"category is {item['category']}"})
    else:
        missed.append({"criterion": "category", "detail": f"category is {item.get('category')!r}, wanted {c['category']!r}"})

    status = n.get("listing_status", "active")
    if status in ("ended", "sold", "gone", "closed"):
        missed.append({"criterion": "listing_active", "detail": f"listing is {status}"})

    if not fields and (c.get("keywords") or c.get("must_have")):
        unknown.append({"criterion": "text", "detail": "no usable listing text"
                        + (f" ({', '.join(excluded)} excluded: instruction-like text)" if excluded else "")})
    else:
        for kind, words in (("keyword", c.get("keywords") or []), ("must_have", c.get("must_have") or [])):
            for w in words:
                hit = _find(_kw_regex(w), fields)
                (met if hit else missed).append({"criterion": f"{kind}:{w}", "detail": hit or f"“{w}” not found in the listing text"})

    price = n.get("price") or {}
    ptype, amount = price.get("type"), price.get("amount")
    if ptype in ("auction_current", "starting_bid"):
        unknown.append({"criterion": "max_price", "detail": f"auction ({ptype}): the final price is not known"})
    elif amount is None:
        unknown.append({"criterion": "max_price", "detail": "the listing states no price"})
    elif amount <= c["max_price_usd"]:
        met.append({"criterion": "max_price", "detail": f"${amount:g} is within the ${c['max_price_usd']:g} maximum"})
    else:
        missed.append({"criterion": "max_price", "detail": f"${amount:g} is above the ${c['max_price_usd']:g} maximum"})

    dist = distance(item, c.get("origin"))
    r = c.get("radius_miles")
    if r is None:
        met.append({"criterion": "radius", "detail": "no radius limit set"})
    elif dist["upper"] is not None and dist["upper"] <= r:
        met.append({"criterion": "radius", "detail": f"{dist['note']}; within {r:g} miles"})
    elif dist["lower"] is not None and dist["lower"] > r:
        missed.append({"criterion": "radius", "detail": f"{dist['note']}; beyond {r:g} miles"})
    else:
        unknown.append({"criterion": "radius", "detail": f"{dist['note']}; cannot confirm within {r:g} miles"})

    for want in c.get("nice_to_have") or []:
        if want.strip().lower() == "title":
            bad, good = _find(_TITLE_BAD, fields), _find(_TITLE_OK, fields)
            if bad:
                soft_met.append({"criterion": "nice:title", "ok": False, "detail": bad})
            elif good:
                soft_met.append({"criterion": "nice:title", "ok": True, "detail": good})
        else:
            hit = _find(_kw_regex(want), fields)
            if hit:
                soft_met.append({"criterion": f"nice:{want}", "ok": True, "detail": hit})

    cosmetics = _find(_COSMETIC, fields)
    soft_cosmetic = bool(c.get("cosmetics_matter")) and cosmetics is not None
    if soft_cosmetic:
        soft_met.append({"criterion": "cosmetics", "ok": False, "detail": cosmetics})

    matched = not missed and not unknown
    score = 0.0
    if matched:
        if amount is not None and c["max_price_usd"] > 0:
            score += 20.0 * (1 - amount / c["max_price_usd"])
        if r and dist["upper"] is not None:
            score += 20.0 * (1 - dist["upper"] / r)
        score += sum(10.0 if s["ok"] else -10.0 for s in soft_met)
    return {"item_id": item["item_id"], "matched": matched, "score": round(score, 2),
            "criteria": {"met": met, "missed": missed, "unknown": unknown, "nice_to_have": soft_met},
            "distance": dist, "price": amount, "excluded_fields": excluded,
            "cosmetics": {"matter": bool(c.get("cosmetics_matter")), "seen": cosmetics, "used_for_decision": soft_cosmetic}}


def _why(doc: dict, e: dict, rank: Optional[int]) -> str:
    c, cr = doc["criteria"], e["criteria"]
    if e["matched"]:
        bits = [f"Matches “{doc['title']}”: " + "; ".join(x["detail"] for x in cr["met"] if x["criterion"] != "category")]
        for s in cr["nice_to_have"]:
            bits.append(("Plus " if s["ok"] else "Minus ") + s["detail"])
        if not c.get("cosmetics_matter") and e["cosmetics"]["seen"]:
            bits.append("Cosmetic wording ignored, as the campaign asks")
        return ". ".join(bits) + f". Rank {rank}. Recommendation only: nothing was contacted or bought."
    parts = [f"Not a match: {x['detail']}" for x in cr["missed"]] + [f"Cannot confirm: {x['detail']}" for x in cr["unknown"]]
    return ". ".join(parts) + "."


def campaign_provenance(doc: dict, items: list[dict], as_of: datetime) -> dict:
    """Provenance record for one matching run (deterministic tool + version over hashed inputs); the caller persists it."""
    inputs = sha256_ref(canonical_json(sorted(i["item_id"] for i in items)))
    prov = {"provenance_id": derived_ulid("prov", as_of, "campaign-match", doc["campaign_id"], inputs),
            "created_at": iso(as_of), "actor_type": "agent", "agent_name": AGENT_ID, "basis": "INFERENCE",
            "tool_name": TOOL_NAME, "tool_version": __version__, "config_version": f"normalizer-{NORMALIZER_VERSION}",
            "inputs_used": [{"ref": doc["campaign_id"], "hash": sha256_ref(canonical_json(doc))},
                            {"ref": f"{len(items)} items", "hash": inputs}]}
    check_provenance(prov)
    return prov


def match_campaign(doc: dict, items: list[dict], as_of: datetime, *, include_non_matches: bool = False) -> dict:
    """{"campaign_id", "refused": reason|None, "matches": [...], "provenance": {...}|None, "evaluated": n}.
    A refused campaign returns immediately: no evaluation, no provenance, nothing else."""
    why = refusal(doc, as_of)
    if why:
        return {"campaign_id": (doc or {}).get("campaign_id") if isinstance(doc, dict) else None, "refused": why,
                "matches": [], "provenance": None, "evaluated": 0}
    prov = campaign_provenance(doc, items, as_of)
    evals = [evaluate(doc, i) for i in items]
    ranked = sorted((e for e in evals if e["matched"]), key=lambda e: (-e["score"], e["price"] if e["price"] is not None else 1e12, e["item_id"]))
    cap = (doc.get("stop_conditions") or {}).get("max_matches")
    if cap:
        ranked = ranked[:cap]
    out = []
    for i, e in enumerate(ranked, 1):
        out.append({"campaign_id": doc["campaign_id"], "item_id": e["item_id"], "matched": True, "rank": i, "score": e["score"],
                    "criteria": e["criteria"], "distance": e["distance"], "price": e["price"], "why": _why(doc, e, i),
                    "provenance_id": prov["provenance_id"], "basis": "INFERENCE", "autonomy": doc["autonomy"]["level"]})
    if include_non_matches:
        keep = {m["item_id"] for m in out}
        for e in evals:
            if e["item_id"] not in keep and not e["matched"]:
                out.append({"campaign_id": doc["campaign_id"], "item_id": e["item_id"], "matched": False, "rank": None,
                            "score": 0.0, "criteria": e["criteria"], "distance": e["distance"], "price": e["price"],
                            "why": _why(doc, e, None), "provenance_id": prov["provenance_id"], "basis": "INFERENCE",
                            "autonomy": doc["autonomy"]["level"]})
    return {"campaign_id": doc["campaign_id"], "refused": None, "matches": out, "provenance": prov, "evaluated": len(items)}
