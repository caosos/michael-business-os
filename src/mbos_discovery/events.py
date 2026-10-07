"""Wake-event producer — READY_QUEUE B-05 (lane-B side of A-08 `mbos.workflows.notify_event`).

Detection (lane B, no spine change): every re-sighting of a listing is compared with the last snapshot of that
same sighting (source, source_listing_id):

* `price_change`   — `normalized.price.amount` differs (summary "price 1200 → 999 USD");
* `new_info`       — anything else in the listing's content changed (status, title, description, bid count, …);
* `auction_ending` — `ends_at` is within ENDING_WINDOW of the fetch and this end time was not announced before.
  A listing first seen already inside the window is not an event (nothing changed) — RECOMMEND handles it.

Events wait in a durable outbox (JSON, atomic writes) until delivered. Delivery (`deliver_wake_events`) needs the
spine: it finds the Item by sighting identity (the same JSONB containment `mbos.spine.ingest` uses), records the
evidence's Provenance FIRST in its own transaction (FACT: the source reported this; source URI + fetched_at +
raw_ref), then calls `notify_event(item_id, event, summary, evidence_provenance_id)`. Undeliverable events (Item
not ingested yet) stay pending. Delivery is at-least-once: the outbox is saved right after each send, so only a
crash in that instant can repeat a notification — harmless, because a wake event never executes anything — that is
the spine's guarantee (A-08) and this module only ever *informs*.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from . import AGENT_ID, __version__
from .dedup import content_hash
from .ids import iso, parse_ts, sha256_ref, canonical_json
from .store import load_json, save_json_atomic

WAKE_EVENTS = ("price_change", "auction_ending", "new_info")
ENDING_WINDOW = timedelta(hours=24)
TOOL_NAME = "mbos_discovery.events"
_FIELDS = ("title", "description", "condition", "price", "ends_at", "bid_count", "location", "listing_status")


def _key(source: str, listing_id: str) -> str:
    return f"{source}\x1f{listing_id}"


@dataclass
class WakeEventDetector:
    """Snapshots + outbox. `path=None` keeps state in memory (tests)."""
    path: Optional[Path] = None
    ending_window: timedelta = ENDING_WINDOW
    snapshots: dict[str, dict] = field(default_factory=dict)
    outbox: list[dict] = field(default_factory=list)      # pending events, oldest first
    delivered: dict[str, str] = field(default_factory=dict)  # event_id -> evidence provenance_id

    @classmethod
    def load(cls, path: str | Path, **kw) -> "WakeEventDetector":
        d = load_json(Path(path), {})
        return cls(Path(path), snapshots=d.get("snapshots", {}), outbox=d.get("outbox", []),
                   delivered=d.get("delivered", {}), **kw)

    def save(self) -> None:
        if self.path:
            save_json_atomic(self.path, {"snapshots": dict(sorted(self.snapshots.items())), "outbox": self.outbox,
                                         "delivered": dict(sorted(self.delivered.items()))})

    # ---- detection (pure given state) -------------------------------------------
    def observe(self, *, source: str, source_listing_id: str, url: str, normalized: dict, fetched_at: datetime,
                raw_ref: str) -> list[dict]:
        k = _key(source, source_listing_id)
        prev = self.snapshots.get(k)
        snap = {"content_hash": content_hash(normalized),
                "price": (normalized.get("price") or {}).get("amount"),
                "currency": (normalized.get("price") or {}).get("currency", "USD"),
                "fields": {f: normalized.get(f) for f in _FIELDS},
                "ends_at": normalized.get("ends_at"),
                "ending_announced": (prev or {}).get("ending_announced")}
        events: list[dict] = []
        ends = normalized.get("ends_at")
        in_window = bool(ends) and timedelta(0) <= parse_ts(ends) - fetched_at <= self.ending_window
        if prev is None:
            if in_window:
                snap["ending_announced"] = ends           # already ending when first seen: not a change
        else:
            if snap["price"] != prev["price"]:
                events.append(("price_change", f"price {prev['price']} → {snap['price']} {snap['currency']}"))
            elif snap["content_hash"] != prev["content_hash"]:
                changed = sorted(f for f in _FIELDS if snap["fields"].get(f) != prev["fields"].get(f))
                events.append(("new_info", "changed: " + ", ".join(changed)))
            if in_window and prev.get("ending_announced") != ends:
                events.append(("auction_ending", f"ends {ends}"))
                snap["ending_announced"] = ends
        self.snapshots[k] = snap
        out = []
        for event, summary in events:
            ev = {"event": event, "summary": summary, "source": source, "source_listing_id": source_listing_id,
                  "url": url, "fetched_at": iso(fetched_at), "raw_ref": raw_ref}
            ev["event_id"] = sha256_ref(canonical_json({k2: ev[k2] for k2 in ("event", "source", "source_listing_id",
                                                                                "raw_ref", "summary")}))
            if ev["event_id"] not in self.delivered and all(e["event_id"] != ev["event_id"] for e in self.outbox):
                self.outbox.append(ev)
                out.append(ev)
        return out


# ---- delivery to the spine (A-08) --------------------------------------------------
def deliver_wake_events(engine, detector: WakeEventDetector, *, notify: Optional[Callable[..., None]] = None,
                        record_provenance: Optional[Callable[..., str]] = None) -> dict[str, Any]:
    """Deliver pending events. Returns {delivered: [...], pending: [...]}. Requires the `mbos` spine."""
    import sqlalchemy as sa
    if notify is None:
        from mbos.workflows import notify_event as notify
    if record_provenance is None:
        from mbos.ledger import record_provenance
    delivered, pending = [], []
    for ev in list(detector.outbox):
        ident = json.dumps([{"source": ev["source"], "source_listing_id": ev["source_listing_id"]}])
        with engine.begin() as c:
            item_id = c.execute(sa.text("SELECT item_id FROM mbos.items WHERE body->'sources' @> CAST(:s AS jsonb) "
                                        "LIMIT 1"), {"s": ident}).scalar_one_or_none()
            if item_id is None:
                pending.append(ev)
                continue
            prov_id = record_provenance(
                c, actor_type="agent", agent_name=AGENT_ID, basis="FACT", source_uri=ev["url"],
                fetched_at=ev["fetched_at"], tool_name=TOOL_NAME, tool_version=__version__,
                inputs_used=[{"ref": ev["url"], "hash": ev["raw_ref"]}])
        notify(item_id, ev["event"], f"{ev['source']}:{ev['source_listing_id']} {ev['summary']}", prov_id)
        detector.delivered[ev["event_id"]] = prov_id
        detector.outbox.remove(ev)
        detector.save()                                 # after each send: a crash can't re-send a delivered event
        delivered.append({**ev, "item_id": item_id, "evidence_provenance_id": prov_id})
    detector.save()
    return {"delivered": delivered, "pending": pending}
