"""Prefixed ULIDs (ADR-0004): ``<prefix>_<26 Crockford base32 chars>``. Same format as mbos.new_id()."""

from __future__ import annotations

import os
import re
import time

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
PREFIXES = ("itm", "areq", "appr", "rcpt", "prov", "outc", "scr", "rec", "lsn", "pol", "bud", "obx")
_ID_RE = re.compile(r"^([a-z]+)_([0-9A-HJKMNP-TV-Z]{26})$")


def ulid(ms: int | None = None) -> str:
    ms = int(time.time() * 1000) if ms is None else ms
    value = (ms & ((1 << 48) - 1)) << 80 | int.from_bytes(os.urandom(10), "big")
    return "".join(ALPHABET[(value >> (5 * i)) & 31] for i in reversed(range(26)))


def new_id(prefix: str) -> str:
    if prefix not in PREFIXES:
        raise ValueError(f"unknown id prefix {prefix!r}")
    return f"{prefix}_{ulid()}"


def is_id(value: str, prefix: str | None = None) -> bool:
    m = _ID_RE.match(value)
    return bool(m) and (prefix is None or m.group(1) == prefix)
