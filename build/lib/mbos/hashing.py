"""Canonical JSON and sha256 helpers shared by every lane: MBOS-CJSON-1 (RFC 8785 JCS profile, ADR-0010).

The normative implementation lives with the frozen contracts
(`docs/research/contracts/canonical/mbos_canonical.py`); this module loads it rather than copying it,
so `payload_hash`, `inputs_hash`, `raw_ref` and receipt `row_hash` are computed by one piece of code.
"""

from __future__ import annotations

import hashlib
import importlib.util
from functools import lru_cache
from typing import Any


@lru_cache(maxsize=1)
def reference():
    from mbos.contracts.schemas import contracts_dir

    path = contracts_dir() / "canonical" / "mbos_canonical.py"
    spec = importlib.util.spec_from_file_location("mbos_canonical_reference", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def canonical_json(obj: Any) -> bytes:
    """MBOS-CJSON-1 bytes (UTF-8)."""
    return reference().canonical_bytes(obj)


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_of(obj: Any) -> str:
    """Contract-format hash (`sha256:<64 hex>`) of an object's MBOS-CJSON-1 form."""
    return reference().sha256_of(obj)
