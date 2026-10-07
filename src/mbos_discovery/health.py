"""Per-source health and the block freeze (acceptance F3).

States: HEALTHY → DEGRADED (any failure) → FROZEN (repeated 403/429, or any CAPTCHA).
A FROZEN source is skipped on every subsequent run until a human clears it — we never
retry through a block, rotate identity, or solve a CAPTCHA (ADR-02-0202). Each freeze
emits a `freeze_request` for Agent 05's L2 capability freeze
(`discovery.source.<name>.read`); this module is the local enforcement until that exists.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from .adapter import SourceError
from .ids import iso

BLOCK_FREEZE_THRESHOLD = 2   # consecutive 403/429 responses
HEALTHY, DEGRADED, FROZEN = "HEALTHY", "DEGRADED", "FROZEN"


@dataclass
class SourceHealth:
    source: str
    status: str = HEALTHY
    consecutive_failures: int = 0
    consecutive_blocks: int = 0
    total_runs: int = 0
    total_failures: int = 0
    last_run_at: str | None = None
    last_success_at: str | None = None
    last_error: dict | None = None
    last_items_seen: int = 0
    frozen_at: str | None = None
    freeze_reason: str | None = None


@dataclass
class HealthBook:
    sources: dict[str, SourceHealth] = field(default_factory=dict)

    def get(self, source: str) -> SourceHealth:
        return self.sources.setdefault(source, SourceHealth(source))

    def is_frozen(self, source: str) -> bool:
        return self.get(source).status == FROZEN

    def record_success(self, source: str, at: datetime, items_seen: int) -> None:
        h = self.get(source)
        h.total_runs += 1
        h.last_run_at = h.last_success_at = iso(at)
        h.consecutive_failures = h.consecutive_blocks = 0
        h.last_items_seen = items_seen
        h.status = HEALTHY

    def record_failure(self, source: str, at: datetime, err: SourceError) -> dict | None:
        """Returns a freeze_request dict if this failure froze the source."""
        h = self.get(source)
        h.total_runs += 1
        h.total_failures += 1
        h.consecutive_failures += 1
        h.consecutive_blocks = h.consecutive_blocks + 1 if err.is_block else 0
        h.last_run_at = iso(at)
        h.last_error = {"kind": err.kind, "status": err.status, "message": err.message[:500], "at": iso(at)}
        h.status = DEGRADED
        if err.kind == "captcha" or h.consecutive_blocks >= BLOCK_FREEZE_THRESHOLD:
            h.status = FROZEN
            h.frozen_at = iso(at)
            h.freeze_reason = (f"{err.kind} (status {err.status}) x{h.consecutive_blocks}"
                               " — stop; no evasion; human must clear")
            return {
                "level": "L2",
                "capability": f"discovery.source.{source}.read",
                "source": source,
                "reason": h.freeze_reason,
                "requested_at": iso(at),
                "requested_by": "agent-02-discovery",
            }
        return None

    def clear_freeze(self, source: str, cleared_by: str, at: datetime) -> None:
        """Human-only action (the CLI requires --by). Resets to DEGRADED, not HEALTHY:
        the next successful fetch is what proves the source is healthy again."""
        h = self.get(source)
        h.status = DEGRADED
        h.consecutive_blocks = 0
        h.freeze_reason = f"cleared by {cleared_by} at {iso(at)} (was: {h.freeze_reason})"
        h.frozen_at = None

    def to_json(self) -> dict:
        return {name: asdict(h) for name, h in sorted(self.sources.items())}

    @classmethod
    def from_json(cls, data: dict) -> "HealthBook":
        return cls({name: SourceHealth(**h) for name, h in data.items()})
