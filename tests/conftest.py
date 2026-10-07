from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import EbayBrowseAdapter, ServiceIntakeAdapter
from mbos_discovery.health import HealthBook
from mbos_discovery.pipeline import run_discovery
from mbos_discovery.rawstore import MemoryRawStore
from mbos_discovery.store import ItemStore

FIX = Path(__file__).parent / "fixtures"
T0 = datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)

FLIP = SearchProfile("flip-test", "flip", ("utility trailer", "generator"), max_price=5000, limit=2)
SERVICE = SearchProfile("service-test", "service")


class Clock:
    def __init__(self, t: datetime = T0) -> None:
        self.t = t

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw) -> None:
        self.t += timedelta(**kw)


class World:
    """One discovery deployment: store + raw store + health, runnable repeatedly."""

    def __init__(self, intake_root: Path | None = None) -> None:
        self.clock = Clock()
        self.store = ItemStore()
        self.raw = MemoryRawStore()
        self.health = HealthBook()
        self.intake_root = intake_root or FIX / "intake"

    def jobs(self):
        return [
            (EbayBrowseAdapter.from_fixture(FIX / "ebay", self.clock), FLIP),
            (ServiceIntakeAdapter("website_lead", self.intake_root / "website_form", self.clock), SERVICE),
            (ServiceIntakeAdapter("referral", self.intake_root / "referral", self.clock), SERVICE),
        ]

    def run(self, jobs=None, enabled=frozenset(), panic=None):
        return run_discovery(jobs if jobs is not None else self.jobs(), self.store, self.raw,
                             self.health, self.clock(), enabled, panic=panic)

    def dump(self) -> str:
        return json.dumps(self.store.to_json(), sort_keys=True)


@pytest.fixture
def world() -> World:
    return World()


@pytest.fixture
def intake_copy(tmp_path) -> Path:
    import shutil
    dst = tmp_path / "intake"
    shutil.copytree(FIX / "intake", dst)
    return dst


# ---- a minimal programmable adapter for dedup / failure tests ---------------------------
from mbos_discovery.adapter import FetchResult, Normalized, RawRecord, SourceAdapter, SourceError  # noqa: E402
from mbos_discovery.ids import canonical_json  # noqa: E402
from mbos_discovery.normalize import classify  # noqa: E402


class StaticAdapter(SourceAdapter):
    """Serves fixed simple records, or a scripted failure. `behaviour` items are consumed one
    per fetch: a list of dicts (records), a SourceError, or an Exception to raise."""
    ingestion_method = "json"
    tos_risk = "med"
    access_tier = 3
    lanes = frozenset({"flip"})
    adapter_version = "test"

    def __init__(self, source, behaviours, clock):
        self.source, self.behaviours, self.clock, self.fetch_calls = source, list(behaviours), clock, 0

    def fetch(self, profile):
        self.fetch_calls += 1
        b = self.behaviours.pop(0) if len(self.behaviours) > 1 else self.behaviours[0]
        if isinstance(b, Exception):
            raise b
        if isinstance(b, SourceError):
            return FetchResult(self.source, error=b, requests_made=1)
        return FetchResult(self.source, [RawRecord(canonical_json(r), r, self.clock(), f"https://example.invalid/{self.source}")
                                         for r in b], requests_made=1)

    def normalize(self, r, fetched_at):
        if "boom" in r:
            raise ValueError("cannot normalize this record")
        cat, matched = classify("flip", r["title"].lower())
        norm = {"title": r["title"], "condition": "used",
                "price": {"amount": float(r["price"]), "currency": "USD", "type": "fixed"},
                "location": {k: r[k] for k in ("city", "state", "zip") if k in r},
                "listing_status": "active"}
        if not matched:
            norm["flags"] = ["needs_review"]
        return Normalized(str(r["id"]), f"https://example.invalid/{self.source}/{r['id']}", "flip", cat,
                          "buy_item", norm)
