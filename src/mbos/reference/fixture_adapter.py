"""REFERENCE discovery stubs — owner: Lane B Discovery (Agent 02). Replace, don't extend.

`FixtureSourceAdapter` reads a local JSON file of ILLUSTRATIVE listings. It makes no network
calls, so it can never touch a real source (ADR-02-0202 do-not-automate list is moot).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from mbos.clock import now_iso
from mbos.hashing import sha256_of
from mbos.interfaces import NormalizedListing, RawListing


class FixtureSourceAdapter:
    ingestion_method = "manual"
    tos_risk = "low"

    def __init__(self, path: str | Path, name: Optional[str] = None):
        self.path = Path(path)
        self.name = name or f"fixture:{self.path.stem}"

    def fetch(self, since: Optional[str] = None) -> list[RawListing]:
        fetched_at = now_iso()
        out = []
        for rec in json.loads(self.path.read_text())["listings"]:
            out.append(RawListing(
                source=rec["source"], source_listing_id=rec.get("source_listing_id"), url=rec["url"],
                fetched_at=fetched_at, ingestion_method=rec.get("ingestion_method", self.ingestion_method),
                tos_risk=rec.get("tos_risk", self.tos_risk), payload=rec["record"],
            ))
        return out


def default_dedup_key(rec: dict[str, Any]) -> str:
    n = rec["normalized"]
    price = (n.get("price") or {}).get("amount")
    bucket = "na" if price is None else f"{int(price // 250) * 250}"
    loc = n.get("location") or {}
    return f"{rec['category']}|{bucket}|{(loc.get('city') or '').lower()}|{n['title'].lower()[:40]}"


class FixtureNormalizer:
    """Fixture records are already shaped like Item v1 fields; this maps them 1:1."""

    def normalize(self, raw: RawListing) -> Optional[NormalizedListing]:
        rec = raw.payload
        if rec.get("not_an_opportunity"):
            return None
        return NormalizedListing(
            type=rec["type"], category=rec["category"], subcategory=rec.get("subcategory"),
            opportunity_kind=rec.get("opportunity_kind"), normalized=rec["normalized"],
            economics=rec.get("economics"), dedup_key=rec.get("dedup_key") or default_dedup_key(rec),
            content_hash=sha256_of(rec["normalized"]),
        )
