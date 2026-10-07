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
from .dedup import RELIST_WINDOW, content_hash, dedup_key, is_cross_source_duplicate, is_relist
from .artifacts import upload as upload_artifact
from .images import collect as collect_images, compare as compare_images
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


@dataclass
class FetchLedger:
    """Which listing ids each fetch run of a source contained (B-13). The relist rule needs "the original listing
    is ABSENT from the current fetch"; the spine ingests one record at a time, so the normalizer copies the run's
    id set into `match_hints["present_ids"]` (then DBOS-checkpointed). In-memory: if it is lost (e.g. a recovery
    replays fetch from a checkpoint), present_ids is omitted and the relist rule simply does not fire."""
    runs: dict[str, frozenset[str]] = field(default_factory=dict)
    run_of: dict[str, str] = field(default_factory=dict)          # "source\x1flid\x1ffetched_at" -> run id

    def record(self, source: str, fetched_ats: dict[str, str]) -> None:
        run = f"{source}\x1f{len(self.runs)}"
        self.runs[run] = frozenset(fetched_ats)
        for lid, at in fetched_ats.items():
            self.run_of[f"{source}\x1f{lid}\x1f{at}"] = run

    def present(self, source: str, lid: str, fetched_at: str) -> Optional[list[str]]:
        run = self.run_of.get(f"{source}\x1f{lid}\x1f{fetched_at}")
        return sorted(self.runs[run]) if run else None


@dataclass
class PhashIndex:
    """Per sighting (source, listing id): image pHashes and last time lane B saw it. The spine's Item body does not
    keep lane-B hints, so the Deduper looks EXISTING Items up here. Persisted (JSON) when `path` is given."""
    path: Optional[Path] = None
    rows: dict[str, dict] = field(default_factory=dict)

    @classmethod
    def load(cls, path: str | os.PathLike) -> "PhashIndex":
        return cls(Path(path), load_json(Path(path), {}))

    def note(self, source: str, lid: str, seen_at: str, hashes: list[str], refs: list[str] = ()) -> None:
        r = self.rows.setdefault(f"{source}\x1f{lid}", {"phash": [], "last_seen": seen_at})
        r["last_seen"] = max(r["last_seen"], seen_at)
        r["phash"] += [h for h in hashes if h not in r["phash"]]
        if refs:                                         # B-14: photos confirmed in the SPINE's artifact store
            r.setdefault("refs", [])
            r["refs"] += [x for x in refs if x not in r["refs"]]

    def refs(self, source: str, lid: str) -> list[str]:
        return list(self.rows.get(f"{source}\x1f{lid}", {}).get("refs", []))

    def hashes(self, sightings: list[dict]) -> list[str]:
        out: list[str] = []
        for s in sightings:
            out += [h for h in self.rows.get(f"{s.get('source')}\x1f{s.get('source_listing_id')}", {}).get("phash", [])
                    if h not in out]
        return out

    def last_seen(self, source: str, lid: str) -> Optional[str]:
        return self.rows.get(f"{source}\x1f{lid}", {}).get("last_seen")

    def save(self) -> None:
        if self.path:
            save_json_atomic(self.path, dict(sorted(self.rows.items())))


class SpineSourceAdapter:
    """`mbos.interfaces.SourceAdapter` over one mbos_discovery adapter + search profile."""

    def __init__(self, inner: SourceAdapter, profile: SearchProfile, *, raw_store: RawStore,
                 side: SideChannel, health: Optional[HealthBook] = None, health_path: Optional[Path] = None,
                 enabled_sources: frozenset[str] = frozenset(), name: Optional[str] = None,
                 clock=_now, panic=None, events=None, ledger: Optional[FetchLedger] = None,
                 index: Optional[PhashIndex] = None, images=None, artifact_sink=None) -> None:
        self.inner, self.profile, self.raw, self.side = inner, profile, raw_store, side
        self.panic = panic                              # lane E PanicStore (B-04); None = local health only
        self.events = events                            # WakeEventDetector (B-05); None = no wake events
        self.ledger, self.index, self.images = ledger, index, images   # B-13 dedup context; B-11 photo fetcher
        self.artifact_sink = artifact_sink              # B-14: spine artifact store for photos (None = keep local)
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
            if self.index is not None:
                hashes, uploaded = [], []
                if self.images is not None and n.match_hints.get("image_urls"):
                    def put(data: bytes) -> str:
                        ref = upload_artifact(self.artifact_sink, data)
                        if ref:
                            uploaded.append(ref)
                        return self.raw.put(data)            # always retained in lane B too
                    _, hashes = collect_images(n.match_hints["image_urls"], self.images, put)
                self.index.note(src, n.source_listing_id, iso(rec.fetched_at), hashes, uploaded)
            if self.events is not None:
                self.events.observe(source=src, source_listing_id=n.source_listing_id, url=n.url,
                                    normalized=n.normalized, fetched_at=rec.fetched_at, raw_ref=raw_ref)
            out.setdefault(n.source_listing_id, RawListing(
                source=src, source_listing_id=n.source_listing_id, url=n.url, fetched_at=iso(rec.fetched_at),
                ingestion_method=self.inner.ingestion_method, tos_risk=self.inner.tos_risk, payload=rec.payload))
        if self.ledger is not None:
            self.ledger.record(src, {lid: r.fetched_at for lid, r in out.items()})
        if self.index is not None:
            self.index.save()
        self.health.record_success(src, now, len(result.records))
        self._save_health()
        if self.events is not None:
            self.events.save()
        return [out[k] for k in sorted(out)]           # deterministic order for DBOS checkpoints

    def _save_health(self) -> None:
        if self.health_path:
            save_json_atomic(self.health_path, self.health.to_json())


class SpineNormalizer:
    """`mbos.interfaces.Normalizer`: dispatches on `raw.source` to the adapter's pure `normalize`."""

    def __init__(self, adapters: dict[str, SourceAdapter], side: Optional[SideChannel] = None,
                 ledger: Optional[FetchLedger] = None, index: Optional[PhashIndex] = None) -> None:
        self.adapters = adapters                        # keyed by source name, e.g. {"ebay": EbayBrowseAdapter}
        self.side = side or SideChannel()
        self.ledger, self.index = ledger, index

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
        normalized = n.normalized
        if self.index is not None:                       # B-14: only photos confirmed in the spine's artifact store
            refs = self.index.refs(raw.source, n.source_listing_id)
            if refs:
                normalized = {**normalized, "images": refs}
        hints: dict[str, Any] = {}                       # A-14 / B-13: JSON-only, DBOS-checkpointed with the listing
        if n.match_hints.get("contact_fp"):
            hints["contact_fp"] = n.match_hints["contact_fp"]
        if self.ledger is not None:
            present = self.ledger.present(raw.source, n.source_listing_id, raw.fetched_at)
            if present is not None:
                hints["present_ids"] = present
        if self.index is not None:
            ph = self.index.hashes([{"source": raw.source, "source_listing_id": n.source_listing_id}])
            if ph:
                hints["phash"] = ph
        return NormalizedListing(
            type=n.type, category=n.category,
            dedup_key=dedup_key(n.type, n.category, n.normalized, n.match_hints.get("contact_fp")),
            normalized=normalized, subcategory=n.subcategory, opportunity_kind=n.opportunity_kind,
            content_hash=content_hash(n.normalized), economics=None, match_hints=hints or None)


class SpineDeduper:
    """`mbos.interfaces.Deduper` (A-14 signature). Called only for Items sharing the candidate's blocking key.

    The rules match lane B's standalone store (`ItemStore`):
    * service: same contact-fingerprint bucket, and the existing Item not in a terminal state;
    * flip, existing Item already has a sighting from the candidate's SOURCE → only a **relist** can merge:
      original absent from the current fetch (`present_ids`), last seen ≤ 14 days ago, same seller, title ≥ 0.90,
      price ±15%, and photos not DIFFERENT (B-11). Unknown `present_ids` → never a relist (no false merge);
    * flip, other source → cross-source rule: price + place agree, and title ≥ 0.85 or photo MATCH; DIFFERENT
      photos veto.
    Without `context` (pre-A-14 spine) only the cross-source rule runs, as before."""

    def __init__(self, index: Optional[PhashIndex] = None) -> None:
        self.index = index or PhashIndex()

    def is_duplicate(self, existing_item: dict[str, Any], candidate: NormalizedListing,
                     context: Optional[dict[str, Any]] = None) -> bool:
        if existing_item.get("type") != candidate.type or existing_item.get("category") != candidate.category:
            return False
        if candidate.type == "service":
            fp_bucket = candidate.dedup_key.split("|")[-1].startswith("fp-")
            return (fp_bucket and existing_item.get("dedup_key") == candidate.dedup_key
                    and existing_item.get("state") not in TERMINAL_STATES)
        hints = candidate.match_hints or (context or {}).get("match_hints") or {}
        img = compare_images(self.index.hashes(existing_item.get("sources", [])), hints.get("phash") or [])
        src = (context or {}).get("source")
        same = [s for s in existing_item.get("sources", []) if src and s.get("source") == src]
        if not same:
            return is_cross_source_duplicate(existing_item, candidate.type, candidate.category, candidate.normalized,
                                             image_verdict=img)
        present = hints.get("present_ids")
        if present is None or img == "DIFFERENT":
            return False
        if any(s.get("source_listing_id") in present for s in same):
            return False                                 # the earlier listing is still up: a second unit, not a relist
        at = parse_ts(context["fetched_at"])
        last = max(parse_ts(self.index.last_seen(src, s.get("source_listing_id")) or s["first_seen_at"]) for s in same)
        return at - last <= RELIST_WINDOW and is_relist(existing_item, same[0], candidate.type, candidate.category,
                                                        candidate.normalized)


def discovery_components(jobs: list[tuple[SourceAdapter, SearchProfile]], *, raw_dir: str | os.PathLike,
                         side_path: Optional[str | os.PathLike] = None,
                         health_path: Optional[str | os.PathLike] = None,
                         enabled_sources: frozenset[str] = frozenset(), clock=_now, panic=None, events=None,
                         images=None, index_path: Optional[str | os.PathLike] = None, artifact_sink=None):
    """Build (adapters, normalizer, deduper, side_channel) for `mbos.runtime.Components`.
    Adapter names are `<source>:<profile_id>` so several profiles of one source can coexist."""
    side = SideChannel(Path(side_path) if side_path else None)
    raw = FileRawStore(raw_dir)
    health = HealthBook.from_json(load_json(Path(health_path), {}) if health_path else {})
    adapters, by_source = {}, {}
    ledger = FetchLedger()
    index = PhashIndex.load(index_path) if index_path else PhashIndex()
    for inner, profile in jobs:
        a = SpineSourceAdapter(inner, profile, raw_store=raw, side=side, health=health, health_path=health_path,
                               enabled_sources=enabled_sources, name=f"{inner.source}:{profile.profile_id}",
                               clock=clock, panic=panic, events=events, ledger=ledger, index=index,
                               images=images, artifact_sink=artifact_sink)
        adapters[a.name] = a
        by_source.setdefault(inner.source, inner)
    return adapters, SpineNormalizer(by_source, side, ledger, index), SpineDeduper(index), side
