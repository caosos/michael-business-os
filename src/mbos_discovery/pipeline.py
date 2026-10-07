"""DISCOVER → NORMALIZE run loop.

Order per record is fixed and is the provenance guarantee:
  1. retain raw bytes        → raw_ref           (nothing is normalized that isn't retained)
  2. normalize (pure)        → Normalized
  3. build provenance        → provenance_id     (source URI + fetched_at + tool@version)
  4. validate a trial Item against the frozen contract
  5. observe into the store  → CREATED / MERGED / UPDATED / SEEN

Failure isolation: a policy refusal, a frozen source, a fetch error or a crashing adapter
affects only that source; a bad record affects only that record (it is quarantined with
its raw_ref kept). Nothing here can raise out of `run_discovery` for a source problem.
"""

from __future__ import annotations

import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime

from . import AGENT_ID, CONTRACT_VERSION, NORMALIZER_VERSION
from .adapter import FetchResult, Normalized, SearchProfile, SourceAdapter, SourceError
from .contract import ContractViolation, check_item, check_provenance
from .health import HealthBook, external_blocks
from .ids import derived_ulid, iso
from .policy import SourceRefused, check_allowed
from .rawstore import RawStore
from .store import ItemStore


@dataclass
class SourceRunStats:
    source: str
    profile_id: str
    status: str = "ok"                   # ok | error | skipped
    skipped_reason: str | None = None
    error: dict | None = None
    fetched: int = 0
    created: int = 0
    merged: int = 0
    updated: int = 0
    seen: int = 0
    quarantined: int = 0
    requests_made: int = 0


@dataclass
class RunReport:
    run_id: str
    started_at: str
    finished_at: str | None = None
    sources: list[SourceRunStats] = field(default_factory=list)
    freeze_requests: list[dict] = field(default_factory=list)
    quarantine: list[dict] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


def gate(adapter, profile: SearchProfile, health: HealthBook, enabled_sources: frozenset[str], panic) -> str | None:
    """Why this source must not be fetched right now, or None. One gate for every collector (items and comps):
    ADR-02-0202 policy → lane → local block freeze → lane E PANIC (fail closed)."""
    try:
        check_allowed(adapter.source, enabled_sources)
    except SourceRefused as e:
        return f"policy: {e}"
    if profile.lane not in adapter.lanes:
        return f"adapter does not serve lane {profile.lane}"
    if health.is_frozen(adapter.source):
        return "source FROZEN (block freeze); human must clear"
    blocked = external_blocks(panic, adapter.source)
    if blocked:
        return "PANIC: " + "; ".join(blocked)
    return None


def build_provenance(adapter: SourceAdapter, n: Normalized, raw_ref: str,
                     fetched_at: datetime, request_uri: str) -> dict:
    prov = {
        "provenance_id": derived_ulid("prov", fetched_at, "prov", adapter.source, n.source_listing_id, raw_ref),
        "created_at": iso(fetched_at),
        "actor_type": "agent",
        "agent_name": AGENT_ID,
        "basis": "FACT",                 # FACT = "the source stated this", not "this is true"
        "source_uri": n.url or request_uri,
        "fetched_at": iso(fetched_at),
        "tool_name": adapter.tool_name,
        "tool_version": adapter.adapter_version,
        "config_version": f"normalizer-{NORMALIZER_VERSION}",
        "inputs_used": [{"ref": request_uri, "hash": raw_ref}],
    }
    check_provenance(prov)
    return prov


def _trial_item(adapter: SourceAdapter, n: Normalized, raw_ref: str, prov: dict) -> dict:
    ts = prov["fetched_at"]
    item = {
        "item_id": derived_ulid("itm", datetime.fromisoformat(ts.replace("Z", "+00:00")), "trial"),
        "schema_version": CONTRACT_VERSION, "type": n.type, "category": n.category,
        "opportunity_kind": n.opportunity_kind, "state": "NORMALIZED", "created_at": ts,
        "sources": [{"source": adapter.source, "source_listing_id": n.source_listing_id, "url": n.url,
                     "ingestion_method": adapter.ingestion_method, "tos_risk": adapter.tos_risk,
                     "first_seen_at": ts, "raw_ref": raw_ref, "provenance_id": prov["provenance_id"]}],
        "dedup_key": "trial", "normalized": n.normalized,
    }
    if n.subcategory:
        item["subcategory"] = n.subcategory
    return item


def run_discovery(jobs: list[tuple[SourceAdapter, SearchProfile]], store: ItemStore, raw: RawStore,
                  health: HealthBook, now: datetime,
                  enabled_sources: frozenset[str] = frozenset(), panic=None, events=None) -> RunReport:
    report = RunReport(run_id=derived_ulid("run", now, "run", iso(now)), started_at=iso(now))
    for adapter, profile in jobs:
        stats = SourceRunStats(source=adapter.source, profile_id=profile.profile_id)
        report.sources.append(stats)

        why = gate(adapter, profile, health, enabled_sources, panic)
        if why:
            stats.status, stats.skipped_reason = "skipped", why
            continue

        try:
            result = adapter.fetch(profile)
        except Exception as e:                       # adapters must not raise; contain it anyway
            result = FetchResult(adapter.source, error=SourceError("crash", f"{type(e).__name__}: {e}"))
        stats.requests_made = result.requests_made

        if not result.ok:
            stats.status, stats.error = "error", asdict(result.error)
            freeze = health.record_failure(adapter.source, now, result.error)
            if freeze:
                report.freeze_requests.append(freeze)
            continue

        stats.fetched = len(result.records)
        present = set()                                  # listing ids in THIS fetch (relist detection)
        for rec in result.records:
            try:
                if rec.payload is not None:
                    present.add(adapter.normalize(rec.payload, rec.fetched_at).source_listing_id)
            except Exception:  # noqa: BLE001 — bad records are quarantined below
                pass
        present = frozenset(present)
        for rec in result.records:
            raw_ref = None
            try:
                raw_ref = raw.put(rec.raw_bytes)
                if rec.payload is None:
                    raise ValueError("payload unparseable")
                n = adapter.normalize(rec.payload, rec.fetched_at)
                prov = build_provenance(adapter, n, raw_ref, rec.fetched_at, rec.request_uri)
                check_item(_trial_item(adapter, n, raw_ref, prov))
                obs = store.observe(adapter, n, raw_ref, prov, rec.fetched_at, present_ids=present)
                if events is not None:              # B-05 wake events (outbox; delivered to the spine separately)
                    events.observe(source=adapter.source, source_listing_id=n.source_listing_id, url=n.url,
                                   normalized=n.normalized, fetched_at=rec.fetched_at, raw_ref=raw_ref)
                check_item(store.items[obs.item_id])
            except (ContractViolation, Exception) as e:  # noqa: BLE001 — per-record isolation
                stats.quarantined += 1
                report.quarantine.append({
                    "source": adapter.source, "profile_id": profile.profile_id, "raw_ref": raw_ref,
                    "error": f"{type(e).__name__}: {str(e)[:500]}",
                    "where": traceback.extract_tb(e.__traceback__)[-1].name if e.__traceback__ else None,
                })
                continue
            setattr(stats, obs.event.lower(), getattr(stats, obs.event.lower()) + 1)

        health.record_success(adapter.source, now, stats.fetched)
    if events is not None:
        events.save()
    report.finished_at = iso(now)
    return report
