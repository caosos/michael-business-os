"""IDs, canonical JSON, hashing and time helpers shared by the governance layer.

Canonical JSON — normative per Agent 01 ruling R3 (ROUND_TWO_INTEGRATION.md, ADR-0009):
  json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False), UTF-8, sha256,
  written "sha256:<hex>". Money values are JSON numbers (Python's deterministic float repr).
Byte-identical to mbos.hashing.canonical_json (01) and operator_ui.util.canonical_json (06)
for every valid JSON value. Two deliberate differences, both REFUSALS rather than divergent
hashes: NaN/Infinity raise (not valid JSON), and non-JSON types raise (01 stringifies them
with default=str). NOTE: 850 and 850.0 hash differently by design of R3 — the gateway always
hashes the exact stored payload, so the proposer must not re-normalise numbers (07 F-14).
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


def payload_hash(payload: dict) -> str:
    """The hash Michael approves (R3 canonical form). Raises ValueError/TypeError on
    NaN/Infinity or non-JSON values, which callers treat as a refusal."""
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
