"""Deterministic prefixed ULIDs, canonical JSON and sha256 refs.

IDs are *derived*, not random: the 48-bit time part is the first-seen time and the
80-bit tail is taken from sha256 of the identifying parts. The same source sighting
therefore always yields the same item_id / provenance_id, which is what makes repeated
discovery idempotent and normalization replayable.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def canonical_json(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def sha256_ref(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def iso(ts: datetime) -> str:
    """UTC, second precision, `Z` suffix — the single timestamp format we emit."""
    if ts.tzinfo is None:
        raise ValueError("naive datetime; all discovery timestamps must be timezone-aware")
    return ts.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def derived_ulid(prefix: str, ts: datetime, *parts: str) -> str:
    ms = int(ts.timestamp() * 1000) & ((1 << 48) - 1)
    tail = int.from_bytes(hashlib.sha256("\x1f".join(parts).encode("utf-8")).digest()[:10], "big")
    n = (ms << 80) | tail
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[n & 31])
        n >>= 5
    return f"{prefix}_{''.join(reversed(chars))}"
