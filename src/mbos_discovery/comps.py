"""Sold-comps sources — lane B side of READY_QUEUE C-04 (Agent 03 leads; hand-off agreed 2026-10-07).

Division of labour (Agent 03 confirmation):
* **02 (here):** comp sources, raw retention, comp dedup, one Provenance record per comp, and a deterministic
  `candidate_comps()` pre-filter.
* **03:** selection policy, bundle assembly and estimation (`mbos_economics.comps_feed.build_comps_bundle`,
  `research_step`).

Hand-off record (`SoldComp.to_record()`), one per comp:
    {comp_id, kind:"sold", price, currency, sold_date (YYYY-MM-DD), source, source_comp_id, url, category,
     title, condition, location{city,state,zip}, fetched_at, raw_ref, provenance_id[, dom_days]}
Only `price` (never `sold_price`). `condition: parts` comps are routed by 03 to `as_is_comps`.

Comps are EVIDENCE, never opportunities: they live in `CompsStore`, never become Items, and nothing here
contacts anyone. Provenance: API comps `actor_type: external` (a third party reported the sale), manual comps
`actor_type: human` (who entered it); both `basis: FACT` meaning "the source reported this sale".
"""

from __future__ import annotations

import hashlib
import json
from abc import abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from . import AGENT_ID, NORMALIZER_VERSION
from .adapter import FetchResult, NormalizationError, RawRecord, SearchProfile, SourceAdapter, SourceError
from .canonical import CanonicalError, raw_json_bytes
from .contract import check_provenance
from .dedup import title_similarity
from .health import HealthBook
from .ids import derived_ulid, iso, parse_ts
from .normalize import classify, clean_text, match_text, money
from .rawstore import RawStore

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
CONDITIONS = frozenset({"new", "used", "parts", "unknown"})
FLIP_CATEGORIES = frozenset({"trailer", "mower", "generator", "welder", "compressor", "tool", "commercial_equipment",
                             "mechanical_equipment", "project_vehicle", "other_asset"})


@dataclass(frozen=True)
class SoldComp:
    comp_id: str
    price: float
    currency: str
    sold_date: str
    source: str
    source_comp_id: str
    url: str
    category: str
    title: str
    condition: str
    fetched_at: str
    raw_ref: str
    provenance_id: str
    location: dict = field(default_factory=dict)
    dom_days: Optional[int] = None
    kind: str = "sold"
    for_item_id: Optional[str] = None          # F-108: a comp a human entered FOR this exact Item

    def to_record(self) -> dict:
        d = asdict(self)
        if d["for_item_id"] is None:
            del d["for_item_id"]
        if d["dom_days"] is None:
            del d["dom_days"]
        if not d["location"]:
            del d["location"]
        return d


@dataclass(frozen=True)
class CompDraft:
    """What a comp adapter's pure `normalize` returns; ids/provenance are added by `collect_comps`."""
    source_comp_id: str
    price: float
    currency: str
    sold_date: str
    url: str
    category: str
    title: str
    condition: str
    location: dict = field(default_factory=dict)
    dom_days: Optional[int] = None
    human_actor: Optional[str] = None          # set → provenance actor_type human
    for_item_id: Optional[str] = None


class CompSourceAdapter(SourceAdapter):
    """Same read-only contract as SourceAdapter, but `normalize` yields a CompDraft, not an Item."""
    lanes = frozenset({"flip"})

    @abstractmethod
    def normalize(self, payload: Any, fetched_at: datetime) -> CompDraft: ...


def _sold_date(value, fetched_at: datetime) -> str:
    s = str(value or "").strip()
    try:
        d = date.fromisoformat(s[:10])
    except ValueError:
        raise NormalizationError(f"sold_date {value!r} is not an ISO date") from None
    if d > fetched_at.date():
        raise NormalizationError(f"sold_date {d} is in the future relative to fetch time")
    return d.isoformat()


def _condition(value) -> str:
    c = str(value or "").strip().lower()
    if c in CONDITIONS:
        return c
    if "part" in c or "not working" in c:
        return "parts"
    if c.startswith("new"):
        return "new"
    return "used" if c else "unknown"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- source 1: manual entry (works today)
class ManualCompsAdapter(CompSourceAdapter):
    """Sold comps recorded by a human (Michael, or the Operator UI on his behalf) as JSON files in an inbox:
        {"comp_id", "category", "title", "sold_price", "sold_date", "where_sold", "url", "condition",
         "city", "state", "zip", "entered_by", "dom_days"?}
    Read-only: files are never moved or deleted. `where_sold` is free text (e.g. "facebook marketplace, observed
    manually"); reading what a human saw is not automating that site."""
    source = "manual"                  # name agreed with Agent 03 comps_sources registry
    ingestion_method = "manual"
    tos_risk = "low"
    access_tier = 5
    adapter_version = "1.0.0"

    def __init__(self, inbox: str | Path, clock: Callable[[], datetime] = _utcnow) -> None:
        self.inbox, self.clock = Path(inbox), clock

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        if not self.inbox.is_dir():
            res.error = SourceError("config", f"comps inbox not found: {self.inbox}")
            return res
        now = self.clock()
        for p in sorted(x for x in self.inbox.iterdir() if x.suffix == ".json" and x.is_file()):
            raw = p.read_bytes()[:256 * 1024]
            res.requests_made += 1
            try:
                payload = json.loads(raw)
                raw = raw_json_bytes(payload)
            except (ValueError, CanonicalError):
                payload = None
            res.records.append(RawRecord(raw, payload, now, f"intake://comps/{p.name}"))
        return res

    def normalize(self, e: dict, fetched_at: datetime) -> CompDraft:
        if not isinstance(e, dict):
            raise NormalizationError("comp entry is not an object")
        cid, who = clean_text(e.get("comp_id"), 100), clean_text(e.get("entered_by"), 60)
        price = money(e.get("sold_price"))
        if not cid or not who or not price:
            raise NormalizationError("comp_id, entered_by and a positive sold_price are required")
        cat = clean_text(e.get("category"))
        title = clean_text(e.get("title"), 300)
        if cat not in FLIP_CATEGORIES:
            cat, _ = classify("flip", match_text(title))
        loc = {k: v for k, v in {"city": clean_text(e.get("city")) or None, "state": clean_text(e.get("state")).upper() or None,
                                 "zip": clean_text(e.get("zip"))[:5] or None}.items() if v}
        dom = e.get("dom_days")
        return CompDraft(source_comp_id=cid, price=price, currency="USD", sold_date=_sold_date(e.get("sold_date"), fetched_at),
                         url=clean_text(e.get("url")) or f"intake://comps/{cid}", category=cat, title=title,
                         condition=_condition(e.get("condition")), location=loc,
                         dom_days=int(dom) if str(dom).isdigit() else None, human_actor=who,
                         for_item_id=clean_text(e.get("for_item_id"), 100) or None)


# ---------------------------------------------------------------- collection
@dataclass
class CompsStore:
    comps: dict[str, dict] = field(default_factory=dict)          # comp_id -> SoldComp record
    provenance: dict[str, dict] = field(default_factory=dict)

    def records(self) -> list[dict]:
        return [self.comps[k] for k in sorted(self.comps)]

    def provenance_records(self, comp_records: list[dict]) -> list[dict]:
        return [self.provenance[c["provenance_id"]] for c in comp_records]

    def to_json(self) -> dict:
        return {"comps": dict(sorted(self.comps.items())), "provenance": dict(sorted(self.provenance.items()))}

    @classmethod
    def from_json(cls, d: dict) -> "CompsStore":
        return cls(dict(d.get("comps", {})), dict(d.get("provenance", {})))


@dataclass
class CompsReport:
    sources: list[dict] = field(default_factory=list)
    freeze_requests: list[dict] = field(default_factory=list)
    quarantine: list[dict] = field(default_factory=list)


def _provenance(adapter: CompSourceAdapter, d: CompDraft, raw_ref: str, fetched_at: datetime, request_uri: str) -> dict:
    prov = {
        "provenance_id": derived_ulid("prov", fetched_at, "comp", adapter.source, d.source_comp_id, raw_ref),
        "created_at": iso(fetched_at),
        "actor_type": "human" if d.human_actor else "external",
        "basis": "FACT",
        "source_uri": d.url or request_uri,
        "fetched_at": iso(fetched_at),
        "tool_name": adapter.tool_name,
        "tool_version": adapter.adapter_version,
        "config_version": f"normalizer-{NORMALIZER_VERSION}",
        "inputs_used": [{"ref": request_uri, "hash": raw_ref}],
        "agent_name": AGENT_ID,                 # the collector; the reporter is actor_type above
    }
    if d.human_actor:
        prov["human_actor"] = d.human_actor
    check_provenance(prov)
    return prov


def collect_comps(jobs: list[tuple[CompSourceAdapter, SearchProfile]], store: CompsStore, raw: RawStore,
                  health: HealthBook, now: datetime, enabled_sources: frozenset[str] = frozenset(),
                  panic=None) -> CompsReport:
    """Same gate and failure isolation as `run_discovery`. A comp is identified by (source, source_comp_id):
    re-reading never duplicates; a changed payload is a new observation and replaces the record."""
    from .pipeline import gate
    rep = CompsReport()
    for adapter, profile in jobs:
        row = {"source": adapter.source, "profile_id": profile.profile_id, "status": "ok", "added": 0, "updated": 0,
               "seen": 0, "quarantined": 0}
        rep.sources.append(row)
        why = gate(adapter, profile, health, enabled_sources, panic)
        if why:
            row.update(status="skipped", reason=why)
            continue
        try:
            res = adapter.fetch(profile)
        except Exception as e:  # noqa: BLE001
            res = FetchResult(adapter.source, error=SourceError("crash", f"{type(e).__name__}: {e}"))
        if not res.ok:
            row.update(status="error", error={"kind": res.error.kind, "status": res.error.status,
                                              "message": res.error.message[:300]})
            fr = health.record_failure(adapter.source, now, res.error)
            if fr:
                rep.freeze_requests.append(fr)
            continue
        for rec in res.records:
            raw_ref = raw.put(rec.raw_bytes)
            try:
                if rec.payload is None:
                    raise NormalizationError("payload unparseable")
                d = adapter.normalize(rec.payload, rec.fetched_at)
                prov = _provenance(adapter, d, raw_ref, rec.fetched_at, rec.request_uri)
            except Exception as e:  # noqa: BLE001
                row["quarantined"] += 1
                rep.quarantine.append({"source": adapter.source, "raw_ref": raw_ref, "error": f"{type(e).__name__}: {e}"[:300]})
                continue
            comp_id = derived_ulid("comp", _EPOCH, adapter.source, d.source_comp_id)   # identity only; no date
            old = store.comps.get(comp_id)
            if old and old["raw_ref"] == raw_ref:
                row["seen"] += 1
                continue
            store.provenance.setdefault(prov["provenance_id"], prov)
            store.comps[comp_id] = SoldComp(
                comp_id=comp_id, price=d.price, currency=d.currency, sold_date=d.sold_date, source=adapter.source,
                source_comp_id=d.source_comp_id, url=d.url, category=d.category, title=d.title, condition=d.condition,
                fetched_at=iso(rec.fetched_at), raw_ref=raw_ref, provenance_id=prov["provenance_id"],
                location=d.location, dom_days=d.dom_days, for_item_id=d.for_item_id).to_record()
            row["updated" if old else "added"] += 1
        health.record_success(adapter.source, now, len(res.records))
    return rep


# ---------------------------------------------------------------- retrieval (pre-filter; 03 owns selection)
def candidate_comps(item: dict, comps: list[dict], as_of: datetime, *, window_days: int = 365,
                    min_similarity: float = 0.5, limit: int = 25, unmatched: Optional[list] = None) -> list[dict]:
    """Deterministic candidates for one flip Item (sold or asking comps; never the subject's own listing): same
    category, sold/observed in (as_of - window, as_of], title
    similarity ≥ min_similarity; ordered by similarity desc, sold_date desc, comp_id. Agent 03's
    `build_comps_bundle` applies the real selection policy (90-day window, vocabulary agreement, FACT check).

    F-108: a comp whose `for_item_id` equals this Item's `item_id` was entered by a human FOR this Item, so it skips
    the category/window/similarity cuts and sorts first. A comp paired to a different Item is not a candidate. Pass a
    list as `unmatched` to receive `{"comp_id", "title", "reason"}` for every comp that was dropped (see
    `unmatched_gap_text`); nothing is dropped silently."""
    if item.get("type") != "flip":
        return []
    own = {s.get("url") for s in item.get("sources", [])} | {
        s.get("source_listing_id") for s in item.get("sources", []) if s.get("source_listing_id")}
    title = item.get("normalized", {}).get("title", "")
    lo = (as_of - timedelta(days=window_days)).date().isoformat()
    hi = as_of.date().isoformat()
    scored = []

    def drop(c, why):
        if unmatched is not None:
            unmatched.append({"comp_id": c.get("comp_id"), "title": c.get("title", ""), "reason": why})

    for c in comps:
        if c.get("url") in own or c.get("source_comp_id") in own:
            drop(c, "it is the subject's own listing")  # its ask is not a comp
            continue
        paired = c.get("for_item_id")
        if paired:
            if paired == item.get("item_id"):
                scored.append((-2.0, 0, c["comp_id"], c))
            else:
                drop(c, f"entered for a different item ({paired})")
            continue
        when = c.get("sold_date") or c.get("observed_date") or ""
        if c["category"] != item.get("category"):
            drop(c, f"category {c['category']} differs from {item.get('category')}")
            continue
        if not (lo < when <= hi):
            drop(c, f"date {when or 'missing'} is outside the {window_days}-day window")
            continue
        sim = title_similarity(title, c["title"])
        if sim >= min_similarity:
            scored.append((-round(sim, 6), _neg_date(when), c["comp_id"], c))
        else:
            drop(c, f"title similarity {sim:.2f} is below {min_similarity}; not entered for this item")
    return [c for *_, c in sorted(scored, key=lambda t: t[:3])[:limit]]


def unmatched_gap_text(unmatched: list[dict], limit: int = 5) -> str:
    """Plain-text gap line for the card/UI: which comps were not used and why."""
    if not unmatched:
        return ""
    parts = [f"'{u['title']}' ({u['reason']})" for u in unmatched[:limit]]
    more = f"; +{len(unmatched) - limit} more" if len(unmatched) > limit else ""
    return f"{len(unmatched)} comp(s) not used: " + "; ".join(parts) + more


def _neg_date(d: str) -> int:
    return -int(d.replace("-", ""))


def comp_digest(records: list[dict]) -> str:
    """Stable digest of a candidate set (for receipts/tests)."""
    return "sha256:" + hashlib.sha256(raw_json_bytes(records)).hexdigest()


# ---------------------------------------------------------------- ASKING comps from eBay Browse (READY_QUEUE B-08)
ASKING_SOURCE = "ebay_browse"          # name in Agent 03's comps_sources registry (kind "asking" only)


def asking_comps_from_items(items: list[dict], *, item_source: str = "ebay",
                            tool_version: str = "1.0.0") -> tuple[list[dict], list[dict]]:
    """ASKING comps derived from listings discovery already retained (no extra API calls).

    Each eligible eBay sighting becomes one record labelled `kind: "asking"` with an `observed_date` — never a
    `sold_date`. An ask is what a seller wants, not what a buyer paid. Eligible: active, fixed price (`fixed`)
    with a positive amount. Auctions (a current bid is not an ask) and free items are excluded. Provenance is FACT
    in the narrow sense "the source listed this asking price at fetched_at", actor `external`, with the sighting's
    `raw_ref` as input. Returns (records, provenance_records), both sorted by comp_id."""
    recs: dict[str, dict] = {}
    provs: dict[str, dict] = {}
    for it in items:
        if it.get("type") != "flip":
            continue
        n = it.get("normalized") or {}
        price = n.get("price") or {}
        if n.get("listing_status", "active") != "active" or price.get("type") != "fixed" or not price.get("amount"):
            continue
        for s in it.get("sources", []):
            if s.get("source") != item_source or not s.get("raw_ref"):
                continue
            seen_at = parse_ts(s.get("last_seen_at") or s["first_seen_at"])
            comp_id = derived_ulid("comp", _EPOCH, ASKING_SOURCE, s["source_listing_id"])
            prov = {
                "provenance_id": derived_ulid("prov", seen_at, "asking", s["source_listing_id"], s["raw_ref"]),
                "created_at": iso(seen_at), "actor_type": "external", "basis": "FACT", "agent_name": AGENT_ID,
                "source_uri": s["url"], "fetched_at": iso(seen_at), "tool_name": "mbos_discovery.comps.asking",
                "tool_version": tool_version, "config_version": f"normalizer-{NORMALIZER_VERSION}",
                "inputs_used": [{"ref": s["url"], "hash": s["raw_ref"]}],
            }
            check_provenance(prov)
            provs[prov["provenance_id"]] = prov
            rec = {"comp_id": comp_id, "kind": "asking", "price": float(price["amount"]),
                   "currency": price.get("currency", "USD"), "observed_date": seen_at.date().isoformat(),
                   "source": ASKING_SOURCE, "source_comp_id": s["source_listing_id"], "url": s["url"],
                   "category": it["category"], "title": n.get("title", ""), "condition": n.get("condition", "unknown"),
                   "fetched_at": iso(seen_at), "raw_ref": s["raw_ref"], "provenance_id": prov["provenance_id"]}
            if n.get("location"):
                rec["location"] = {k: v for k, v in n["location"].items() if k in ("city", "state", "zip")}
            recs[comp_id] = rec
    return [recs[k] for k in sorted(recs)], [provs[k] for k in sorted(provs)]
