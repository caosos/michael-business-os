"""IDs, canonical JSON, hashing and time helpers shared by the governance layer.

Canonical JSON (used for payload_hash, row_hash, policy/panic checksums):
UTF-8, keys sorted, no insignificant whitespace, non-ASCII kept as-is, no NaN/Infinity.
This is the RFC 8785 (JCS) subset that matters for our payloads; floats are rejected
in payloads that are hashed for approval so number formatting can never drift.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from typing import Any

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    """26-char Crockford base32 ULID (48-bit ms timestamp + 80 random bits)."""
    ms = int(time.time() * 1000)
    value = (ms << 80) | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[value & 0x1F])
        value >>= 5
    return "".join(reversed(out))


def new_id(prefix: str) -> str:
    return f"{prefix}_{new_ulid()}"


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def sha256_tagged(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _reject_floats(obj: Any, path: str = "$") -> None:
    if isinstance(obj, float):
        raise ValueError(f"float at {path}: approval payloads must use integers/strings (e.g. cents)")
    if isinstance(obj, dict):
        for k, v in obj.items():
            _reject_floats(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _reject_floats(v, f"{path}[{i}]")


def payload_hash(payload: dict) -> str:
    """The hash Michael approves. Floats are refused so the hash is unambiguous."""
    _reject_floats(payload)
    return sha256_tagged(canonical_json(payload))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def parse_ts(value: str) -> datetime:
    """Parse an RFC 3339 timestamp; naive timestamps are refused (fail closed)."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without timezone: {value!r}")
    return dt


def fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
