"""IDs, canonical JSON, hashing and time helpers shared by the governance layer.

Hashing is ADR-0010 (normative): MBOS-CJSON-1 (RFC 8785 JCS, I-JSON profile; 850.0 == 850) for
payload_hash and every content hash, MBOS-RH-1 for receipt row_hash. The block marked REFERENCE
below is copied VERBATIM from docs/research/contracts/canonical/mbos_canonical.py
(origin/research/agent-01-coordinator @ 99e9ec0). It is inlined, not imported, because
tools/interop_check.py loads this file standalone. tests/test_canonical_adr0010.py proves it
against the pinned vectors.json (10 forms, 6 rejections, receipt chain).
This module must stay stdlib-only with no relative imports.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

# ---------------------------------------------------------------- REFERENCE (verbatim, ADR-0010)
SPEC = "MBOS-CJSON-1"
MAX_SAFE_INT = 2**53 - 1


class CanonicalError(ValueError):
    pass


def _number(x: Any) -> str:
    if isinstance(x, int):
        if abs(x) > MAX_SAFE_INT:
            raise CanonicalError(f"integer {x} outside +/-(2**53-1) (I-JSON)")
        x = float(x)
    if not math.isfinite(x):
        raise CanonicalError("NaN/Infinity are not JSON")
    if x.is_integer() and abs(x) > MAX_SAFE_INT:  # literal form (1e21 vs 1000…) is lost in many parsers, incl. jsonb
        raise CanonicalError(f"integral value {x!r} outside +/-(2**53-1) (I-JSON)")
    if x == 0:
        return "0"
    sign = "-" if x < 0 else ""
    t = Decimal(repr(abs(x))).as_tuple()  # repr == shortest round-trip digits
    digits = "".join(map(str, t.digits)).rstrip("0") or "0"
    n = len("".join(map(str, t.digits))) + t.exponent  # value = 0.<digits> * 10**n
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


def _key(k: Any) -> str:
    if not isinstance(k, str):
        raise CanonicalError(f"object member name must be a string, got {type(k).__name__}")
    if any(ord(c) > 0xFFFF for c in k):
        raise CanonicalError(f"object member name {k!r} contains a non-BMP character")
    return k


def _enc(o: Any) -> str:
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


def canonical_json(obj: Any) -> str:
    """MBOS-CJSON-1 text."""
    return _enc(obj)


def canonical_bytes(obj: Any) -> bytes:
    return canonical_json(obj).encode("utf-8")


def sha256_of(obj: Any) -> str:
    """`sha256:<hex>` of MBOS-CJSON-1: payload_hash, inputs_hash, content hashes."""
    return "sha256:" + hashlib.sha256(canonical_bytes(obj)).hexdigest()


def receipt_hash_document(receipt: dict) -> dict:
    """D for MBOS-RH-1."""
    d = {k: v for k, v in receipt.items() if k != "row_hash" and (v is not None or k == "prev_hash")}
    d.setdefault("prev_hash", None)
    return d


def receipt_row_hash(receipt: dict) -> str:
    return sha256_of(receipt_hash_document(receipt))
# ---------------------------------------------------------------- end REFERENCE

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


def sha256_tagged(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def payload_hash(payload: dict) -> str:
    """The hash Michael approves: MBOS-CJSON-1 sha256 (ADR-0010). Raises CanonicalError
    (a ValueError) on NaN/Infinity, unsafe integers, non-BMP names, U+0000, lone surrogates or
    non-JSON types; callers treat that as a refusal."""
    return sha256_of(payload)


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


def fmt_ts_us(dt: datetime) -> str:
    """Receipt `ts` form required by ADR-0010: UTC, exactly 6 fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
