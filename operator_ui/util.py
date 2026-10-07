"""IDs, canonical hashing and time helpers shared by the Operator UI."""

import hashlib
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_ULID_RE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$")


def ulid(ts_ms=None):
    """26-char Crockford base32 ULID: 48-bit ms timestamp + 80 random bits."""
    ts_ms = int(time.time() * 1000) if ts_ms is None else ts_ms
    n = (ts_ms << 80) | int.from_bytes(os.urandom(10), "big")
    out = []
    for _ in range(26):
        out.append(_CROCKFORD[n & 31])
        n >>= 5
    return "".join(reversed(out))


def new_id(prefix):
    """Prefixed public ID per ADR-0004 ruling 2 (itm_, areq_, appr_, rcpt_, prov_ ...)."""
    return f"{prefix}_{ulid()}"


def canonical_json(obj):
    """Canonical serialization used for every hash: sorted keys, no whitespace, UTF-8.

    INFERENCE: the frozen examples' hashes are illustrative and do not pin a
    canonicalization; this is the RFC 8785-compatible subset for our data
    (no floats with exponent forms). Lane D must adopt the same function.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(obj):
    data = obj if isinstance(obj, (bytes, bytearray)) else canonical_json(obj).encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


_DURATION_RE = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?)?$")


def parse_duration(s):
    """Parse the ISO-8601 durations the HOLD presets use (PnD, PTnH, PTnM, PnDTnH)."""
    m = _DURATION_RE.match(s or "")
    if not m or not any(m.groups()):
        raise ValueError(f"unsupported ISO-8601 duration: {s!r}")
    d, h, mi = (int(g or 0) for g in m.groups())
    return timedelta(days=d, hours=h, minutes=mi)


class Clock:
    """Injectable clock so HOLD/expiry behaviour is testable without sleeping."""

    def __init__(self, fixed=None):
        self._fixed = fixed

    def now(self):
        return self._fixed or datetime.now(timezone.utc)

    def set(self, dt):
        self._fixed = dt

    def advance(self, delta):
        self._fixed = self.now() + delta
