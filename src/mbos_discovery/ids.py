"""Deterministic prefixed ULIDs, canonical JSON (MBOS-CJSON-1, ADR-0010) and sha256 refs.

`canonical_json` is MBOS-CJSON-1: RFC 8785 JCS with the I-JSON profile (850.0 -> 850, sorted members,
JSON.stringify escaping, |integral| <= 2^53-1, BMP-only member names, no U+0000 / lone surrogates).
This module must stay stdlib-only and import-free of the package: Agent 01's `tools/interop_check.py`
loads it in isolation. The encoder below mirrors the normative reference
`contracts/canonical/mbos_canonical.py` (vendored, hash-pinned); `tests/test_canonical_b02.py` holds
it to the reference and `vectors.json` byte for byte.

IDs are *derived*, not random: the 48-bit time part is the first-seen time and the
80-bit tail is taken from sha256 of the identifying parts. The same source sighting
therefore always yields the same item_id / provenance_id, which is what makes repeated
discovery idempotent and normalization replayable.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from decimal import Decimal

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


MAX_SAFE_INT = 2**53 - 1


class CanonicalError(ValueError):
    """Value outside the MBOS-CJSON-1 profile; never silently coerced."""


def _number(x) -> str:
    if isinstance(x, int):
        if abs(x) > MAX_SAFE_INT:
            raise CanonicalError(f"integer {x} outside +/-(2**53-1) (I-JSON)")
        x = float(x)
    if not math.isfinite(x):
        raise CanonicalError("NaN/Infinity are not JSON")
    if x.is_integer() and abs(x) > MAX_SAFE_INT:
        raise CanonicalError(f"integral value {x!r} outside +/-(2**53-1) (I-JSON)")
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    t = Decimal(repr(abs(x))).as_tuple()              # repr = shortest round-trip digits
    all_digits = "".join(map(str, t.digits))
    digits = all_digits.rstrip("0") or "0"
    n = len(all_digits) + t.exponent                  # value = 0.<digits> * 10**n
    k = len(digits)
    if k <= n <= 21:
        s = digits + "0" * (n - k)
    elif 0 < n <= 21:
        s = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        s = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        s = digits[0] + ("." + digits[1:] if k > 1 else "") + "e" + ("+" if e > 0 else "-") + str(abs(e))
    return sign + s


def _string(s: str) -> str:
    if "\x00" in s or any(0xD800 <= ord(c) <= 0xDFFF for c in s):
        raise CanonicalError("strings must not contain U+0000 or lone surrogates")
    return json.dumps(s, ensure_ascii=False)


def _key(k) -> str:
    if not isinstance(k, str):
        raise CanonicalError(f"object member name must be a string, got {type(k).__name__}")
    if any(ord(c) > 0xFFFF for c in k):
        raise CanonicalError(f"object member name {k!r} contains a non-BMP character")
    return k


def _enc(o) -> str:
    if o is None:
        return "null"
    if o is True:
        return "true"
    if o is False:
        return "false"
    if isinstance(o, (int, float)):
        return _number(o)
    if isinstance(o, Decimal):
        return _number(float(o))
    if isinstance(o, str):
        return _string(o)
    if isinstance(o, dict):
        keys = sorted(_key(k) for k in o)
        if len(keys) != len(o):
            raise CanonicalError("duplicate member names")
        return "{" + ",".join(_string(k) + ":" + _enc(o[k]) for k in keys) + "}"
    if isinstance(o, (list, tuple)):
        return "[" + ",".join(_enc(v) for v in o) + "]"
    raise CanonicalError(f"cannot canonicalise {type(o).__name__}")


def canonical_json(obj) -> bytes:
    """MBOS-CJSON-1 bytes (UTF-8). Raises CanonicalError outside the profile."""
    return _enc(obj).encode("utf-8")


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
