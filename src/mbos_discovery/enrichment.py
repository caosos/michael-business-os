"""Deal Sniffer enrichment blocks `listing_activity` and `seller` — READY_QUEUE B-15 (ADR-0011, P0).

THE RULE (Agent 01 / ADR-0011 §2): only where the source actually exposes it. A key that a source does not expose is
OMITTED, and the card prints UNKNOWN. Nothing here infers seller reputation, and no date is invented:

* Dates and seller facts come ONLY from `exposed_facts(source, payload)`, a per-source whitelist read from the
  retained raw payload (`sources[].raw_ref`), so every block is replayable from stored bytes. Unknown source → {}.
* Free text is never mined. A listing that says "trusted seller, 5 stars" produces nothing.
* "First seen by this system" is a statement about OUR observation, never a listing age. `age_days` exists only when
  the source gave a post date (and never for a date in the future).
* `suspected_relist` is True (INFERENCE) only with evidence: the Item carries ≥ 2 sightings from one source under
  different listing ids (the relist rule merged them). Otherwise the key is omitted; "not a relist" is never
  asserted, because the system cannot see before its first sighting.
* `stale_risk` (INFERENCE, with the reason) needs a real post date; omitted for auctions, which end by design.

Each datum is {"value", "basis", "provenance_id"[, "note"]}. Source-exposed facts cite the SIGHTING's provenance
(source URI + fetched_at); derived values cite this lane's own provenance, recorded first.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from . import AGENT_ID, __version__
from .ids import iso, parse_ts
from .normalize import clean_text

TOOL_NAME = "mbos_discovery.enrichment"
STALE_MEDIUM_DAYS, STALE_HIGH_DAYS = 14, 45          # INFERENCE thresholds, shown in every stale_risk note
LEVELS = ("low", "medium", "high")


# ---------------------------------------------------------------- per-source whitelists (what each source exposes)
def _ts(value) -> Optional[str]:
    if not value:
        return None
    try:
        dt = parse_ts(str(value))
    except ValueError:
        return None
    return iso(dt)


def _num(value) -> Optional[float]:
    try:
        x = float(str(value).strip())
    except (TypeError, ValueError):
        return None
    return x if x == x and x >= 0 else None


def _ebay(p: dict) -> dict:
    out: dict[str, Any] = {}
    if _ts(p.get("itemCreationDate")):
        out["posted_at"] = _ts(p["itemCreationDate"])                 # ItemSummary.itemCreationDate (listing created)
    s = p.get("seller") if isinstance(p.get("seller"), dict) else {}
    pct, score = _num(s.get("feedbackPercentage")), s.get("feedbackScore")
    rating = {}
    if pct is not None and pct <= 100:
        rating["feedback_percent"] = pct
    if isinstance(score, int) and not isinstance(score, bool) and score >= 0:
        rating["feedback_score"] = score
    if rating:
        out["rating"] = rating
    return out


def _gsa(p: dict) -> dict:
    d = str(p.get("AucStartDt") or "")[:10]                      # auction start date (ISO 8601 date, UTC)
    at = _ts(f"{d}T00:00:00Z") if len(d) == 10 else None
    return {"posted_at": at} if at else {}


def _trashnothing(p: dict) -> dict:
    out: dict[str, Any] = {}
    raw = str(p.get("date") or "")
    at = _ts(raw if raw.endswith("Z") or "+" in raw[10:] else f"{raw}Z") if raw else None   # naive = UTC per spec
    if at:
        out["posted_at"] = at
    rc = p.get("repost_count")
    if isinstance(rc, int) and not isinstance(rc, bool) and rc > 0:
        out["repost_count"] = rc
    return out


EXPOSED: dict[str, Callable[[dict], dict]] = {"ebay": _ebay, "gsa_auctions": _gsa, "trashnothing": _trashnothing}


def exposed_facts(source: str, payload: Any) -> dict:
    """Facts a source's payload actually exposes, whitelisted per source. Anything else → {}."""
    fn = EXPOSED.get(source)
    if fn is None or not isinstance(payload, dict):
        return {}
    try:
        return fn(payload)
    except Exception:  # noqa: BLE001 — a malformed payload exposes nothing
        return {}


# ---------------------------------------------------------------- block construction (pure)
def _datum(value: Any, basis: str, prov: str, note: str | None = None) -> dict:
    d = {"value": value, "basis": basis, "provenance_id": prov}
    if note:
        d["note"] = note
    return d


def _days_ago(at: str, as_of: datetime) -> int:
    return max(0, (as_of - parse_ts(at)).days)


def _ago(days: int) -> str:
    return "today" if days == 0 else "1 day ago" if days == 1 else f"{days} days ago"


def build_blocks(item: dict, facts_by_listing: dict[str, dict], as_of: datetime, own_prov: str,
                 history: list[dict] | None = None) -> dict[str, dict]:
    """Pure. `facts_by_listing`: "source|listing_id" → exposed_facts() for each sighting. `history`: optional
    observed price points [{source, listing_id, at, price}] (this system's own observations).
    Returns {"listing_activity": {...}, "seller": {...}} containing only keys with evidence (blocks may be empty)."""
    sightings = item.get("sources", [])
    la: dict[str, Any] = {}
    seller: dict[str, Any] = {}
    activity: list[str] = []

    # posted_at: the earliest source-exposed post date among sightings, citing that sighting's provenance
    best: tuple[str, dict] | None = None
    for s in sightings:
        f = facts_by_listing.get(f"{s['source']}|{s.get('source_listing_id')}", {})
        at = f.get("posted_at")
        if at and parse_ts(at) <= as_of and (best is None or at < best[0]):
            best = (at, s)
    age = None
    if best:
        at, s = best
        la["posted_at"] = _datum(at, "FACT", s["provenance_id"], f"as reported by {s['source']}")
        age = _days_ago(at, as_of)
        la["age_days"] = _datum(age, "FACT", own_prov, "computed from the source-reported post date")
        activity.append(f"Listed {_ago(age)} ({s['source']})")

    for s in sightings:
        f = facts_by_listing.get(f"{s['source']}|{s.get('source_listing_id')}", {})
        if f.get("repost_count"):
            activity.append(f"Source reports {f['repost_count']} repost(s) of this listing ({s['source']})")
        first = s.get("first_seen_at")
        if first and parse_ts(first) <= as_of:
            activity.append(f"First seen by this system {_ago(_days_ago(first, as_of))} ({s['source']})")

    # price movement we observed ourselves
    pts = sorted((h for h in (history or []) if h.get("price") is not None and parse_ts(h["at"]) <= as_of),
                 key=lambda h: (h["at"], str(h.get("listing_id"))))
    for a, b in zip(pts, pts[1:]):
        if a.get("listing_id") == b.get("listing_id") and b["price"] != a["price"]:
            verb = "dropped" if b["price"] < a["price"] else "rose"
            activity.append(f"Price {verb} {a['price']:g} → {b['price']:g} (observed {_ago(_days_ago(b['at'], as_of))})")

    # suspected relist: needs two listing ids from ONE source on this Item
    by_src: dict[str, list[dict]] = {}
    for s in sightings:
        by_src.setdefault(s["source"], []).append(s)
    relist_src = next((src for src, ss in sorted(by_src.items())
                       if len({x.get("source_listing_id") for x in ss}) >= 2), None)
    if relist_src:
        ids = sorted({x.get("source_listing_id") for x in by_src[relist_src]})
        la["suspected_relist"] = _datum(True, "INFERENCE", own_prov,
                                        f"same seller re-posted under a new {relist_src} listing id (ids: {', '.join(map(str, ids))})")
        activity.append(f"Looks like a re-post: {len(ids)} {relist_src} listing ids merged into this Item")

    # stale_risk: only from a real post date, not for auctions
    if age is not None and item.get("opportunity_kind") != "auction_lot":
        level = 0 if age < STALE_MEDIUM_DAYS else 1 if age < STALE_HIGH_DAYS else 2
        reason = f"listed {age} days ago (medium ≥ {STALE_MEDIUM_DAYS} d, high ≥ {STALE_HIGH_DAYS} d)"
        if relist_src and level < 2:
            level += 1
            reason += "; raised one level because the listing appears re-posted"
        la["stale_risk"] = _datum(LEVELS[level], "INFERENCE", own_prov, reason)
    la["recent_activity"] = activity

    # seller: source-exposed facts only. Rating is the one seller dimension any current source exposes (eBay).
    dims = 0
    for s in sightings:
        f = facts_by_listing.get(f"{s['source']}|{s.get('source_listing_id')}", {})
        if f.get("rating") and "rating" not in seller:
            r = f["rating"]
            seller["rating"] = _datum(r, "FACT", s["provenance_id"],
                                      f"marketplace feedback as reported by {s['source']}; not independently verified")
            dims += 1
    if seller:
        # confidence = how many independent dimensions the source exposed: ≥3 high, 2 medium, 1 low
        seller["confidence"] = "high" if dims >= 3 else "medium" if dims == 2 else "low"
    return {"listing_activity": la if (la.get("recent_activity") or len(la) > 1) else {}, "seller": seller}


# ---------------------------------------------------------------- attach to the spine
def attach_enrichment(conn, spine, item_id: str, raw_store, as_of: datetime,
                      history: list[dict] | None = None, agent: str = AGENT_ID) -> dict[str, Any]:
    """Build both blocks for one Item and attach them with `spine.record_enrichment`. `spine` is `mbos.spine`
    (reference DDL) or `mbos.spine_d` (lane D). Records this lane's provenance FIRST. Idempotent: a block whose
    content key is already recorded in the Item's research is not attached again (and no provenance is written)."""
    from mbos.hashing import canonical_json, sha256_bytes
    item = spine.read_item(conn, item_id)
    facts = {}
    for s in item.get("sources", []):
        try:
            payload = json.loads(raw_store.get(s["raw_ref"]))
        except Exception:  # noqa: BLE001 — unreadable raw → that sighting exposes nothing
            continue
        facts[f"{s['source']}|{s.get('source_listing_id')}"] = exposed_facts(s["source"], payload)
    # Idempotency key = hash of each block built with a PLACEHOLDER provenance, so a fresh provenance id on a re-run
    # does not look like new content; the key is recorded in the research entry's finding.
    placeholder = "prov_" + "0" * 26
    draft = build_blocks(item, facts, as_of, placeholder, history)
    keys = {n: sha256_bytes(canonical_json(d))[7:23] for n, d in draft.items() if d}
    todo = [n for n in keys if f"key={keys[n]}" not in " ".join(
        r.get("finding", "") for r in item.get("research") or [] if r.get("field") == f"card.{n}")]
    skipped = [n for n in ("listing_activity", "seller") if n not in todo]
    if not todo:
        return {"provenance_id": None, "attached": [], "skipped": skipped}
    ledger = getattr(spine, "L", None)
    if ledger is None:
        import mbos.ledger as ledger
    inputs = [{"ref": s["url"], "hash": s["raw_ref"]} for s in item.get("sources", []) if s.get("raw_ref")]
    prov = ledger.record_provenance(conn, actor_type="agent", agent_name=agent, basis="INFERENCE",
                                    tool_name=TOOL_NAME, tool_version=__version__, inputs_used=inputs,
                                    source_uri=item["sources"][0]["url"], fetched_at=iso(as_of))
    blocks = build_blocks(item, facts, as_of, prov, history)          # the real blocks cite this provenance
    attached = []
    for name in todo:
        data = blocks[name]
        spine.record_enrichment(conn, item_id, name, data, prov, agent=agent,
                                basis="FACT" if name == "seller" else "INFERENCE",
                                summary=f"{name}: " + ", ".join(sorted(k for k in data if k != "confidence"))
                                        + f" [key={keys[name]}]")
        attached.append(name)
    return {"provenance_id": prov, "attached": attached, "skipped": skipped}
