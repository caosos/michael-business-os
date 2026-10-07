"""The SourceAdapter abstraction.

An adapter has exactly two jobs and no others:

* `fetch(profile)`  — read raw records from one source. Must not raise: every failure
  comes back as a `FetchResult` with `error` set, so one broken source never stops a run.
* `normalize(payload, fetched_at)` — a *pure* function from one raw payload to a
  `Normalized` value. No I/O, no clock, no randomness: the same bytes always normalize
  the same way, which is what lets anyone replay an Item from its `raw_ref`.

There is deliberately no method to contact, bid, buy, post or message. Adapters only
receive a `ReadOnlyTransport` (see http.py).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar, Literal

ErrorKind = Literal["config", "auth", "blocked", "rate_limited", "captcha", "http",
                    "network", "parse", "crash", "policy"]

# Kinds that mean "the source is pushing back on us" — these count toward the freeze.
BLOCK_KINDS: frozenset[str] = frozenset({"blocked", "rate_limited", "captcha"})


@dataclass(frozen=True)
class SearchProfile:
    profile_id: str
    lane: Literal["flip", "service"]
    keywords: tuple[str, ...] = ()
    postal_code: str = "72034"          # Conway, AR (home base)
    radius_miles: int = 100             # normal radius, not a hard limit (AGENT_HANDOFF)
    max_price: float | None = None
    limit: int = 50
    max_pages: int = 2


@dataclass(frozen=True)
class SourceError:
    kind: ErrorKind
    message: str
    status: int | None = None

    @property
    def is_block(self) -> bool:
        return self.kind in BLOCK_KINDS


@dataclass(frozen=True)
class RawRecord:
    """One as-discovered record. `raw_bytes` is what gets hashed into `raw_ref`."""
    raw_bytes: bytes
    payload: Any                        # parsed form of raw_bytes (None if unparseable)
    fetched_at: datetime
    request_uri: str


@dataclass
class FetchResult:
    source: str
    records: list[RawRecord] = field(default_factory=list)
    error: SourceError | None = None
    requests_made: int = 0

    @property
    def ok(self) -> bool:
        return self.error is None


@dataclass(frozen=True)
class Normalized:
    """Adapter output for one record; the pipeline wraps it into an Item v1 envelope."""
    source_listing_id: str
    url: str
    type: Literal["flip", "service"]
    category: str
    opportunity_kind: str
    normalized: dict                    # exactly the Item v1 `normalized` object
    subcategory: str | None = None
    # Dedup-only hints; never written into the Item (e.g. hashed contact for service leads).
    match_hints: dict = field(default_factory=dict)


class NormalizationError(Exception):
    pass


class SourceAdapter(ABC):
    source: ClassVar[str]               # Item.sources[].source
    ingestion_method: ClassVar[str]     # Item.sources[].ingestion_method
    tos_risk: ClassVar[str]             # low | med | high
    access_tier: ClassVar[int]          # ADR-02-0202: 1 API · 2 email · 3 internal endpoint · 4 browser · 5 manual
    lanes: ClassVar[frozenset[str]]
    adapter_version: ClassVar[str]

    @abstractmethod
    def fetch(self, profile: SearchProfile) -> FetchResult: ...

    @abstractmethod
    def normalize(self, payload: Any, fetched_at: datetime) -> Normalized: ...

    @property
    def tool_name(self) -> str:
        return f"mbos_discovery.adapters.{self.source}"
