"""Canonical JSON, content hashes and deterministic prefixed-ULID ids.

Canonical form: keys sorted, no whitespace, UTF-8, and every number rendered
from its Decimal value with trailing zeros removed, so 3.2, 3.20 and "3.20"
read via Decimal all hash identically. Booleans and null are JSON literals.

IDs follow ADR-0004 (prefix + 26 Crockford base32 chars, ULID layout). They are
*derived*, not random: the 48-bit time part comes from the caller-supplied
``scored_at`` and the 80-bit tail from sha256 of a seed. Replaying the same
inputs at the same ``scored_at`` reproduces the same ids. The engine never
reads the wall clock.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _norm(obj: Any) -> Any:
    if isinstance(obj, bool) or obj is None or isinstance(obj, str):
        return obj
    if isinstance(obj, (int, float, Decimal)):
        d = Decimal(str(obj)) if not isinstance(obj, Decimal) else obj
        if not d.is_finite():
            raise ValueError("non-finite number")
        if d == 0:
            return _RawNumber("0")
        if d == d.to_integral_value():
            return _RawNumber(str(d.quantize(Decimal(1))))
        return _RawNumber(format(d.normalize(), "f"))
    if isinstance(obj, dict):
        return {str(k): _norm(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_norm(v) for v in obj]
    raise TypeError(f"cannot canonicalize {type(obj).__name__}")


class _RawNumber(str):
    """Marker so the encoder emits the string's text as a bare JSON number."""


def canonical_json(obj: Any) -> str:
    def enc(o: Any) -> str:
        if isinstance(o, _RawNumber):
            return str.__str__(o)
        if isinstance(o, dict):
            return "{" + ",".join(json.dumps(k, ensure_ascii=False) + ":" + enc(o[k]) for k in sorted(o)) + "}"
        if isinstance(o, list):
            return "[" + ",".join(enc(v) for v in o) + "]"
        return json.dumps(o, ensure_ascii=False)

    return enc(_norm(obj))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def content_hash(obj: Any) -> str:
    """``sha256:<hex>`` of the canonical JSON (the contracts' sha256 pattern)."""
    return "sha256:" + sha256_hex(canonical_json(obj))


def parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError(f"timestamp must carry a timezone: {ts!r}")
    return dt.astimezone(timezone.utc)


def derived_ulid(prefix: str, ts: str, seed: str) -> str:
    """Deterministic ULID-shaped id: time part from ``ts``, tail from sha256(seed)."""
    ms = int(parse_ts(ts).timestamp() * 1000)
    if not 0 <= ms < 2**48:
        raise ValueError("timestamp out of ULID range")
    tail = int.from_bytes(hashlib.sha256(seed.encode("utf-8")).digest()[:10], "big")
    n = (ms << 80) | tail
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[n & 31])
        n >>= 5
    return f"{prefix}_" + "".join(reversed(chars))
