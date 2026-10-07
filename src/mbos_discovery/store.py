"""Staging store for discovered Items, their provenance, and ledger events.

This is the DISCOVER lane's local working set, not the system of record. Agent 04's
Postgres State MCP is the only durable write path (ADR-0001/0004); `events` is the
hand-off: each one carries a `receipt_intent` (Receipt v1 minus the ledger-owned fields
`receipt_id`, `seq`, `prev_hash`, `row_hash`) that 04 writes in the same transaction as
the Item. Provenance records are append-only here as there.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import AGENT_ID, CONTRACT_VERSION
from .adapter import Normalized, SourceAdapter
from .dedup import SERVICE_WINDOW, content_hash, dedup_key, is_cross_source_duplicate
from .ids import canonical_json, derived_ulid, iso, parse_ts

CREATED, MERGED, UPDATED, SEEN = "CREATED", "MERGED", "UPDATED", "SEEN"


@dataclass(frozen=True)
class Observation:
    event: str
    item_id: str


class ItemStore:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.provenance: dict[str, dict] = {}
        self.events: list[dict] = []
        self._by_listing: dict[str, str] = {}          # "source\x1flisting_id" → item_id
        self._sighting_hash: dict[str, str] = {}       # same key → content hash of last payload
        self._fingerprints: dict[str, str] = {}        # "category\x1ffp" → item_id (service)

    # ---- queries -------------------------------------------------------------------
    def find_by_listing(self, source: str, listing_id: str) -> dict | None:
        iid = self._by_listing.get(_k(source, listing_id))
        return self.items.get(iid) if iid else None

    # ---- the one write path --------------------------------------------------------
    def observe(self, adapter: SourceAdapter, n: Normalized, raw_ref: str, prov: dict,
                fetched_at: datetime) -> Observation:
        key = _k(adapter.source, n.source_listing_id)
        ts = iso(fetched_at)
        chash = content_hash(n.normalized)

        existing_id = self._by_listing.get(key)
        if existing_id:
            item = self.items[existing_id]
            sighting = next(s for s in item["sources"]
                            if s["source"] == adapter.source and s.get("source_listing_id") == n.source_listing_id)
            sighting["last_seen_at"] = ts
            if self._sighting_hash[key] == chash:
                return Observation(SEEN, existing_id)
            # Content changed: point the sighting at the payload that now backs it.
            self._sighting_hash[key] = chash
            sighting["raw_ref"] = raw_ref
            sighting["provenance_id"] = self._add_prov(prov)
            if item["sources"][0] is sighting:
                self._apply_primary(item, n, chash)
            item["provenance_ids"].append(prov["provenance_id"])
            item["updated_at"] = ts
            self._event(UPDATED, item, adapter, n, raw_ref, prov, ts, effect="update")
            return Observation(UPDATED, existing_id)

        dup = self._find_duplicate(n, fetched_at, adapter.source)
        sighting = {
            "source": adapter.source,
            "source_listing_id": n.source_listing_id,
            "url": n.url,
            "ingestion_method": adapter.ingestion_method,
            "tos_risk": adapter.tos_risk,
            "first_seen_at": ts,
            "last_seen_at": ts,
            "raw_ref": raw_ref,
            "provenance_id": self._add_prov(prov),
        }
        self._sighting_hash[key] = chash
        if dup:
            dup["sources"].append(sighting)
            dup["provenance_ids"].append(prov["provenance_id"])
            dup["updated_at"] = ts
            self._by_listing[key] = dup["item_id"]
            self._event(MERGED, dup, adapter, n, raw_ref, prov, ts, effect="update")
            return Observation(MERGED, dup["item_id"])

        item_id = derived_ulid("itm", fetched_at, "item", adapter.source, n.source_listing_id)
        item = {
            "item_id": item_id,
            "schema_version": CONTRACT_VERSION,
            "type": n.type,
            "category": n.category,
            "opportunity_kind": n.opportunity_kind,
            "state": "NORMALIZED",
            "created_at": ts,
            "updated_at": ts,
            "sources": [sighting],
            "dedup_key": "",
            "content_hash": "",
            "normalized": {},
            "provenance_ids": [prov["provenance_id"]],
        }
        self._apply_primary(item, n, chash)
        self.items[item_id] = item
        self._by_listing[key] = item_id
        fp = n.match_hints.get("contact_fp")
        if fp:
            self._fingerprints[_k(n.category, fp)] = item_id
        self._event(CREATED, item, adapter, n, raw_ref, prov, ts, effect="create")
        return Observation(CREATED, item_id)

    # ---- internals -----------------------------------------------------------------
    def _apply_primary(self, item: dict, n: Normalized, chash: str) -> None:
        old_price = (item.get("normalized") or {}).get("price", {}).get("amount")
        new = json.loads(canonical_json(n.normalized))      # deep copy, canonical types
        flags = set(new.get("flags", []))
        if item["normalized"] and old_price is not None and new.get("price", {}).get("amount") != old_price:
            flags.add("price_changed")
        if flags:
            new["flags"] = sorted(flags)
        item["normalized"] = new
        item["category"] = n.category
        if n.subcategory:
            item["subcategory"] = n.subcategory
        item["dedup_key"] = dedup_key(n.type, n.category, new, n.match_hints.get("contact_fp"))
        item["content_hash"] = chash

    def _find_duplicate(self, n: Normalized, fetched_at: datetime, source: str) -> dict | None:
        if n.type == "service":
            fp = n.match_hints.get("contact_fp")
            iid = self._fingerprints.get(_k(n.category, fp)) if fp else None
            if iid:
                item = self.items[iid]
                if abs(fetched_at - parse_ts(item["created_at"])) <= SERVICE_WINDOW:
                    return item
            return None
        for iid in sorted(self.items):                      # sorted → deterministic winner
            cand = self.items[iid]
            if any(s["source"] == source for s in cand["sources"]):
                continue                                    # same source = a different listing
            if is_cross_source_duplicate(cand, n.type, n.category, n.normalized):
                return cand
        return None

    def _add_prov(self, prov: dict) -> str:
        self.provenance.setdefault(prov["provenance_id"], prov)   # append-only
        return prov["provenance_id"]

    def _event(self, kind, item, adapter, n, raw_ref, prov, ts, effect) -> None:
        idem = (f"discovery:{item['item_id']}:normalized" if kind == CREATED
                else f"discovery:{item['item_id']}:{adapter.source}:{n.source_listing_id}:{raw_ref}")
        self.events.append({
            "event": kind,
            "at": ts,
            "item_id": item["item_id"],
            "source": adapter.source,
            "source_listing_id": n.source_listing_id,
            "raw_ref": raw_ref,
            "provenance_id": prov["provenance_id"],
            "receipt_intent": {
                "schema_version": CONTRACT_VERSION,
                "ts": ts,
                "type": "ITEM_STATE_CHANGED",
                "actor": {"type": "agent", "id": AGENT_ID},
                "intent": {
                    CREATED: f"discovered {adapter.source}:{n.source_listing_id}; normalized to Item v1",
                    MERGED: f"cross-source duplicate {adapter.source}:{n.source_listing_id} merged as a sighting",
                    UPDATED: f"{adapter.source}:{n.source_listing_id} changed at source; re-normalized",
                }[kind],
                "item_id": item["item_id"],
                "entity_type": "item",
                "entity_id": item["item_id"],
                "effect": effect,
                "tool_name": f"{adapter.tool_name}@{adapter.adapter_version}",
                "idempotency_key": idem,
                "before_state": {"state": "DISCOVERED"} if kind == CREATED else {"state": item["state"]},
                "after_state": {"state": "NORMALIZED"} if kind == CREATED else {"state": item["state"]},
                "provenance_ids": [prov["provenance_id"]],
                "artifact_hashes": [raw_ref],
            },
        })

    # ---- persistence ---------------------------------------------------------------
    def to_json(self) -> dict:
        return {
            "items": {k: self.items[k] for k in sorted(self.items)},
            "provenance": {k: self.provenance[k] for k in sorted(self.provenance)},
            "events": self.events,
            "index": {
                "by_listing": dict(sorted(self._by_listing.items())),
                "sighting_hash": dict(sorted(self._sighting_hash.items())),
                "fingerprints": dict(sorted(self._fingerprints.items())),
            },
        }

    @classmethod
    def from_json(cls, data: dict) -> "ItemStore":
        s = cls()
        s.items = data.get("items", {})
        s.provenance = data.get("provenance", {})
        s.events = data.get("events", [])
        idx = data.get("index", {})
        s._by_listing = idx.get("by_listing", {})
        s._sighting_hash = idx.get("sighting_hash", {})
        s._fingerprints = idx.get("fingerprints", {})
        return s


def _k(*parts: str) -> str:
    return "\x1f".join(parts)


def load_json(path: Path, default):
    try:
        return json.loads(Path(path).read_text())
    except FileNotFoundError:
        return default


def save_json_atomic(path: Path, data) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
    with os.fdopen(fd, "w") as fh:
        json.dump(data, fh, indent=1, sort_keys=False, ensure_ascii=False)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
