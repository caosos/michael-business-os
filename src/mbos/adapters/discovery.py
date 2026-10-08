"""Lane B (Agent 02) card enrichment behind `Enricher` (A-20, ADR-0011).

Agent 02's `mbos_discovery.enrichment.attach_enrichment(conn, spine, item_id, raw_store, as_of, history=None)` builds the
`listing_activity` and `seller` blocks from facts in the retained raw payloads (`sources[].raw_ref`), records lane B's
provenance first, and calls `spine.record_enrichment(..., agent="agent-02-opportunity")`. It omits any key the source
does not expose, so the card prints UNKNOWN. Idempotent. Install lane B's package from its branch (RUNBOOK §6).
"""

from __future__ import annotations

from typing import Any, Optional


class LaneBEnricher:
    def __init__(self, raw_store: Any, history: Optional[Any] = None):
        self.raw_store, self.history = raw_store, history

    def enrich(self, conn, spine, item_id: str) -> int:
        from mbos_discovery.enrichment import attach_enrichment

        item = spine.read_item(conn, item_id)
        if item["state"] in ("ARCHIVED", "FAILED"):
            return 0
        as_of = item["created_at"]  # stable: re-running attaches nothing new
        if isinstance(as_of, str):  # lane D returns ISO text; lane B compares datetimes (found by the A-38 real-environment run)
            from datetime import datetime, timezone

            as_of = datetime.fromisoformat(as_of.replace("Z", "+00:00"))
            as_of = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
        out = attach_enrichment(conn, spine, item_id, self.raw_store, as_of, history=self.history)
        return int(out if isinstance(out, int) else len(out or []))
