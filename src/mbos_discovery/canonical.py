"""MBOS-CJSON-1 (ADR-0010) for raw retention.

JSON sources are retained as the MBOS-CJSON-1 bytes of the parsed payload. That is exactly what
the spine stores in `mbos.artifacts` (`canonical_json(raw.payload)`), so `raw_ref` — the sha256 of
the stored raw bytes — is identical in both lanes. A payload the profile rejects (e.g. an integer
beyond 2^53-1, U+0000) is retained as received and quarantined, never silently altered.
"""

from __future__ import annotations

from .contracts.canonical.mbos_canonical import CanonicalError, canonical_bytes

__all__ = ["CanonicalError", "raw_json_bytes"]


def raw_json_bytes(payload) -> bytes:
    """MBOS-CJSON-1 bytes of a parsed JSON payload; raises CanonicalError if out of profile."""
    return canonical_bytes(payload)
