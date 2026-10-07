"""Shared primitives: canonical JSON, sha256 refs, prefixed ULIDs, injectable clock.

Hashing is ADR-0010, not a local choice. `canonical`, `sha256_ref` (for JSON values) and `receipt_row_hash`
delegate to the NORMATIVE reference `contracts/canonical/mbos_canonical.py` (MBOS-CJSON-1 / MBOS-RH-1). That
file is pinned byte-identical to Agent 01's copy (PIN.json), so this lane cannot drift from it.
"""
from __future__ import annotations

import hashlib
import importlib.util
import pathlib
import random
import threading
from datetime import datetime, timedelta, timezone

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIXES = {"itm", "areq", "appr", "rcpt", "prov", "outc", "scr", "rec"}

_REF_PATH = pathlib.Path(__file__).resolve().parent.parent / "contracts" / "canonical" / "mbos_canonical.py"
_spec = importlib.util.spec_from_file_location("mbos_canonical", _REF_PATH)
mbos_canonical = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mbos_canonical)
CanonicalError = mbos_canonical.CanonicalError


def canonical(obj) -> bytes:
    """MBOS-CJSON-1 bytes (ADR-0010)."""
    return mbos_canonical.canonical_bytes(obj)


def sha256_ref(data: bytes | str | dict | list) -> str:
    """JSON values → MBOS-CJSON-1 hash. Raw bytes / text (artifacts, rendered packets) → hash of those bytes."""
    if isinstance(data, (dict, list)):
        return mbos_canonical.sha256_of(data)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def receipt_row_hash(row: dict) -> str:
    """MBOS-RH-1: sha256(MBOS-CJSON-1(receipt − row_hash, seq and prev_hash inside, top-level nulls dropped
    except prev_hash)). No separate `|| prev_hash` concatenation."""
    return mbos_canonical.receipt_row_hash(row)


def iso_receipt(dt: datetime) -> str:
    """ADR-0010: receipt `ts` is UTC with exactly 6 fractional digits."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def parse_duration(s: str) -> timedelta:
    """Minimal ISO-8601 duration parser for PnD / PTnH / PTnM / PTnS (HOLD renotify/escalate)."""
    if not s.startswith("P"):
        raise ValueError(f"not an ISO-8601 duration: {s}")
    days = hours = minutes = seconds = 0
    date_part, _, time_part = s[1:].partition("T")
    if date_part:
        if not date_part.endswith("D"):
            raise ValueError(f"unsupported duration: {s}")
        days = int(date_part[:-1])
    num = ""
    for ch in time_part:
        if ch.isdigit():
            num += ch
        elif ch == "H":
            hours, num = int(num), ""
        elif ch == "M":
            minutes, num = int(num), ""
        elif ch == "S":
            seconds, num = int(num), ""
        else:
            raise ValueError(f"unsupported duration: {s}")
    return timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)


class Clock:
    """Injectable clock. Fixed by default so fixture runs are reproducible byte-for-byte."""

    def __init__(self, start: datetime | None = None):
        self._now = start or datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        with self._lock:
            self._now = self._now + delta


class IdGen:
    """Prefixed ULIDs (ADR-0004 rule 2). Seeded for reproducible fixture output."""

    def __init__(self, clock: Clock, seed: int | None = 7):
        self.clock = clock
        self._rng = random.Random(seed)
        self._lock = threading.Lock()

    def new(self, prefix: str) -> str:
        if prefix not in PREFIXES:
            raise ValueError(f"unknown id prefix {prefix}")
        with self._lock:
            ms = int(self.clock.now().timestamp() * 1000)
            n = (ms << 80) | self._rng.getrandbits(80)
        chars = []
        for _ in range(26):
            chars.append(CROCKFORD[n & 31])
            n >>= 5
        return f"{prefix}_{''.join(reversed(chars))}"
