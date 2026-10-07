"""Lane-B seam for Agent 01's spine (READY_QUEUE B-01; rulings R5, R8; ROUND_TWO_INTEGRATION §3-B).

Implements `mbos.interfaces` SourceAdapter / Normalizer / Deduper on top of this package's adapters:

    from mbos_discovery.spine import discovery_components
    adapters, normalizer, deduper, side = discovery_components(jobs, raw_dir="var/discovery/raw")
    Components(adapters=adapters, normalizer=normalizer, deduper=deduper).with_defaults()

Division of labour with the spine (`mbos.spine.ingest`):
* identity first — the spine treats an equal (source, source_listing_id) as the same sighting (no-op);
* `dedup_key` is a BLOCKING bucket only; equal keys merge only when `SpineDeduper.is_duplicate` says so;
* `raw_ref` is the sha256 of the stored raw bytes in both lanes: JSON payloads are retained here as
  MBOS-CJSON-1 bytes (ADR-0010), which is byte-for-byte what the spine writes to `mbos.artifacts`.

Everything that is not a listing — policy refusals, frozen sources, fetch errors, block freezes,
quarantined records — goes to the `SideChannel` (R5: freeze requests become L2 capability freezes),
never into the DBOS-checkpointed listing stream. `fetch()` never raises for a source problem.

Requires the `mbos` package (Agent 01) at import time; the rest of mbos_discovery does not.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mbos.interfaces import NormalizedListing, RawListing

from .adapter import FetchResult, NormalizationError, SearchProfile, SourceAdapter, SourceError
from .dedup import content_hash, dedup_key, is_cross_source_duplicate
from .health import HealthBook, external_blocks
from .ids import iso, parse_ts
from .policy import SourceRefused, check_allowed
from .rawstore import FileRawStore, RawStore
from .store import load_json, save_json_atomic

# An Item in one of these states is a closed job/listing: a new service lead from the same contact
# is new work, not a duplicate sighting.
TERMINAL_STATES = frozenset({"ARCHIVED", "REJECTED", "ACTED", "OUTCOME_RECORDED", "LEARNED", "FAILED"})


@dataclass
class SideChannel:
    """Out-of-band discovery events. Appends JSONL to `path` when given; always kept in memory."""
    path: Optional[Path] = None
    events: list[dict] = field(default_factory=list)

    def emit(self, kind: str, **data: Any) -> None:
        ev = {"kind": kind, **data}
        self.events.append(ev)
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(ev, sort_keys=True) + "\n")

    def freeze_requests(self) -> list[dict]:
        return [e["freeze_request"] for e in self.events if e["kind"] == "freeze_request"]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SpineSourceAdapter:
    """`mbos.interfaces.SourceAdapter` over one mbos_discovery adapter + search profile."""

    def __init__(self, inner: SourceAdapter, profile: SearchProfile, *, raw_store: RawStore,
                 side: SideChannel, health: Optional[HealthBook] = None, health_path: Optional[Path] = None,
                 enabled_sources: frozenset[str] = frozenset(), name: Optional[str] = None,
                 clock=_now, panic=None) -> None:
        self.inner, self.profile, self.raw, self.side = inner, profile, raw_store, side
        self.panic = panic                              # lane E PanicStore (B-04); None = local health only
        self.health_path = Path(health_path) if health_path else None
        self.health = health or HealthBook.from_json(load_json(self.health_path, {}) if self.health_path else {})
        self.enabled = enabled_sources
        self.clock = clock
        self.name = name or inner.source
        self.ingestion_method = inner.ingestion_method
        self.tos_risk = inner.tos_risk
        self.version = inner.adapter_version            # read by mbos.workflows.discover for provenance

    def fetch(self, since: Optional[str] = None) -> list[RawListing]:
        """`since` is accepted for the protocol; identity-first dedup makes full re-reads idempotent."""
        src, pid, now = self.inner.source, self.profile.profile_id, self.clock()
        try:
            check_allowed(src, self.enabled)
        except SourceRefused as e:
            self.side.emit("skipped", source=src, profile_id=pid, at=iso(now), reason=f"policy: {e}")
            return []
        if self.profile.lane not in self.inner.lanes:
            self.side.emit("skipped", source=src, profile_id=pid, at=iso(now), reason=f"lane {self.profile.lane}")
            return []
        if self.health.is_frozen(src):
            self.side.emit("skipped", source=src, profile_id=pid, at=iso(now), reason="source FROZEN; human must clear")
            return []
        blocked = external_blocks(self.panic, src)
        if blocked:
            self.side.emit("skipped", source=src, profile_id=pid, at=iso(now), reason="PANIC: " + "; ".join(blocked))
            return []

        try:
            result = self.inner.fetch(self.profile)
        except Exception as e:                          # contained: one adapter never breaks the workflow
            result = FetchResult(src, error=SourceError("crash", f"{type(e).__name__}: {e}"))
        if not result.ok:
            err = result.error
            self.side.emit("source_error", source=src, profile_id=pid, at=iso(now),
                           error={"kind": err.kind, "status": err.status, "message": err.message[:500]})
            freeze = self.health.record_failure(src, now, err)
            if freeze:
                self.side.emit("freeze_request", source=src, at=iso(now), freeze_request=freeze)
            self._save_health()
            return []

        out: dict[str, RawListing] = {}
        for rec in result.records:
            raw_ref = self.raw.put(rec.raw_bytes)       # retained before anything else, even if bad
            try:
                if rec.payload is None or not isinstance(rec.payload, dict):
                    raise NormalizationError("payload unparseable or not a JSON object")
                n = self.inner.normalize(rec.payload, rec.fetched_at)
            except Exception as e:
                self.side.emit("quarantine", source=src, profile_id=pid, at=iso(now), raw_ref=raw_ref,
                               error=f"{type(e).__name__}: {str(e)[:300]}")
                continue
            out.setdefault(n.source_listing_id, RawListing(
                source=src, source_listing_id=n.source_listing_id, url=n.url, fetched_at=iso(rec.fetched_at),
                ingestion_method=self.inner.ingestion_method, tos_risk=self.inner.tos_risk, payload=rec.payload))
        self.health.record_success(src, now, len(result.records))
        self._save_health()
        return [out[k] for k in sorted(out)]           # deterministic order for DBOS checkpoints

    def _save_health(self) -> None:
        if self.health_path:
            save_json_atomic(self.health_path, self.health.to_json())


class SpineNormalizer:
    """`mbos.interfaces.Normalizer`: dispatches on `raw.source` to the adapter's pure `normalize`."""

    def __init__(self, adapters: dict[str, SourceAdapter], side: Optional[SideChannel] = None) -> None:
        self.adapters = adapters                        # keyed by source name, e.g. {"ebay": EbayBrowseAdapter}
        self.side = side or SideChannel()

    def normalize(self, raw: RawListing) -> Optional[NormalizedListing]:
        inner = self.adapters.get(raw.source)
        if inner is None:
            self.side.emit("quarantine", source=raw.source, url=raw.url, error="no lane-B normalizer for source")
            return None
        try:
            n = inner.normalize(raw.payload, parse_ts(raw.fetched_at))
        except Exception as e:
            self.side.emit("quarantine", source=raw.source, url=raw.url, error=f"{type(e).__name__}: {str(e)[:300]}")
            return None
        return NormalizedListing(
            type=n.type, category=n.category,
            dedup_key=dedup_key(n.type, n.category, n.normalized, n.match_hints.get("contact_fp")),
            normalized=n.normalized, subcategory=n.subcategory, opportunity_kind=n.opportunity_kind,
            content_hash=content_hash(n.normalized), economics=None)


class SpineDeduper:
    """`mbos.interfaces.Deduper`. Called only for Items sharing the candidate's blocking key."""

    def is_duplicate(self, existing_item: dict[str, Any], candidate: NormalizedListing) -> bool:
        if existing_item.get("type") != candidate.type or existing_item.get("category") != candidate.category:
            return False
        if candidate.type == "service":
            # Same blocking key here means same category + same contact fingerprint (dedup_key).
            fp_bucket = candidate.dedup_key.split("|")[-1].startswith("fp-")
            return (fp_bucket and existing_item.get("dedup_key") == candidate.dedup_key
                    and existing_item.get("state") not in TERMINAL_STATES)
        return is_cross_source_duplicate(existing_item, candidate.type, candidate.category, candidate.normalized)


def discovery_components(jobs: list[tuple[SourceAdapter, SearchProfile]], *, raw_dir: str | os.PathLike,
                         side_path: Optional[str | os.PathLike] = None,
                         health_path: Optional[str | os.PathLike] = None,
                         enabled_sources: frozenset[str] = frozenset(), clock=_now, panic=None):
    """Build (adapters, normalizer, deduper, side_channel) for `mbos.runtime.Components`.
    Adapter names are `<source>:<profile_id>` so several profiles of one source can coexist."""
    side = SideChannel(Path(side_path) if side_path else None)
    raw = FileRawStore(raw_dir)
    health = HealthBook.from_json(load_json(Path(health_path), {}) if health_path else {})
    adapters, by_source = {}, {}
    for inner, profile in jobs:
        a = SpineSourceAdapter(inner, profile, raw_store=raw, side=side, health=health, health_path=health_path,
                               enabled_sources=enabled_sources, name=f"{inner.source}:{profile.profile_id}",
                               clock=clock, panic=panic)
        adapters[a.name] = a
        by_source.setdefault(inner.source, inner)
    return adapters, SpineNormalizer(by_source, side), SpineDeduper(), side
