"""Spine artifact sinks for listing photos — READY_QUEUE B-14.

On the spine path the Item lives in Postgres, so the photos referenced by `normalized.images` must be in the
spine's artifact store, not only in lane B's raw store. A sink uploads the bytes there (content-addressed,
idempotent) and returns the ref; the adapter then references only photos whose upload succeeded and whose
returned ref equals lane B's own sha256 of the bytes. A failed or mismatched upload leaves the photo unreferenced:
it never produces a dangling or lying ref, and never breaks discovery.

* `LaneDArtifactSink(engine)` — Agent 04's canonical store: `SELECT mbos.put_artifact(content, media_type)`
  (granted to agent_write and gateway; the DB checks sha256(content)).
* `ReferenceSpineArtifactSink(engine)` — Agent 01's reference DDL: `INSERT INTO mbos.artifacts … ON CONFLICT DO
  NOTHING` (same CHECK on sha256).
Uploads happen in the fetch step, before ingest, so the refs resolve as soon as the Item is written; content
addressing makes a DBOS retry harmless.
"""

from __future__ import annotations

from typing import Protocol

from .ids import sha256_ref


class ArtifactSink(Protocol):
    def put(self, data: bytes, media_type: str) -> str: ...


def sniff_media_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


class _SqlSink:
    SQL = ""

    def __init__(self, engine) -> None:
        self.engine = engine

    def put(self, data: bytes, media_type: str) -> str:
        import sqlalchemy as sa
        with self.engine.begin() as c:
            ref = c.execute(sa.text(self.SQL), {"c": data, "m": media_type, "h": sha256_ref(data)}).scalar_one()
        return ref


class LaneDArtifactSink(_SqlSink):
    SQL = "SELECT mbos.put_artifact(:c, :m)"


class ReferenceSpineArtifactSink(_SqlSink):
    """Insert-only: ON CONFLICT DO NOTHING, then read back what the store holds for that hash."""

    def put(self, data: bytes, media_type: str) -> str:
        import sqlalchemy as sa
        h = sha256_ref(data)
        with self.engine.begin() as c:
            c.execute(sa.text("INSERT INTO mbos.artifacts (sha256, media_type, content) VALUES (:h, :m, :c) "
                              "ON CONFLICT (sha256) DO NOTHING"), {"h": h, "m": media_type, "c": data})
            return c.execute(sa.text("SELECT sha256 FROM mbos.artifacts WHERE sha256 = :h"), {"h": h}).scalar_one()


def upload(sink: ArtifactSink | None, data: bytes) -> str | None:
    """Upload one photo; return its ref only if the store confirmed exactly lane B's sha256."""
    if sink is None:
        return None
    mt = sniff_media_type(data)
    if mt is None:
        return None
    try:
        ref = sink.put(data, mt)
    except Exception:  # noqa: BLE001 — permission, connection, constraint: the photo stays unreferenced
        return None
    return ref if ref == sha256_ref(data) else None
