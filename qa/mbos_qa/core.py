"""Shared primitives: canonical JSON, sha256 refs, prefixed ULIDs, injectable clock.

Canonical form (QA lane proposal, pending Agent 04 sign-off — see ACCEPTANCE_REPORT "Findings"):
UTF-8 JSON, keys sorted, separators (",", ":"), no NaN/Infinity, ensure_ascii=False.
"""
from __future__ import annotations

import hashlib
import json
import random
import threading
from datetime import datetime, timedelta, timezone

CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIXES = {"itm", "areq", "appr", "rcpt", "prov", "outc", "scr", "rec"}


def canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def sha256_ref(data: bytes | str | dict | list) -> str:
    if isinstance(data, (dict, list)):
        data = canonical(data)
    elif isinstance(data, str):
        data = data.encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def receipt_row_hash(row: dict) -> str:
    """row_hash = sha256(canonical(row without row_hash) || prev_hash) per receipt.schema.json."""
    body = {k: v for k, v in row.items() if k != "row_hash"}
    prev = row.get("prev_hash") or ""
    return sha256_ref(canonical(body) + prev.encode("utf-8"))


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
