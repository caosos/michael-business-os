"""Canonical JSON and sha256 helpers shared by every lane.

`payload_hash`, `inputs_hash` and `raw_ref` all use the same canonical form, so
any lane can recompute any hash.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    """Sorted keys, no whitespace, UTF-8. The one canonical form for hashing."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_of(obj: Any) -> str:
    """Contract-format hash (`sha256:<64 hex>`) of an object's canonical JSON."""
    return sha256_bytes(canonical_json(obj))
