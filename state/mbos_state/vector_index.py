"""Rebuildable pgvector similarity index over Items (D-08, acceptance D3).

The index is a projection: `refresh` upserts rows whose source text changed, `rebuild` drops everything for a
model and regenerates it from mbos.items, and `verify` reports missing / stale / orphan rows. Query results
are identical before and after a rebuild because the embedding is a pure function of the item's text.

`HashEmbedder` (mbos-hash-embed v1) is deterministic, local and free: feature-hashed word unigrams and
bigrams, signed, L2-normalised. It makes D3 testable offline and is a usable dry-run fallback. A model
embedder (via LiteLLM, lane E caps) implements the same `Embedder` shape; switching model means a new
(model_id, model_version) and a rebuild, with the old rows untouched until dropped.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Protocol

import psycopg

from . import mbos_canonical

DIM = 256


class Embedder(Protocol):
    model_id: str
    model_version: str

    def embed(self, text: str) -> list[float]: ...


@dataclass(frozen=True)
class HashEmbedder:
    model_id: str = "mbos-hash-embed"
    model_version: str = "1"
    dim: int = DIM

    def embed(self, text: str) -> list[float]:
        words = re.findall(r"[a-z0-9]+", text.lower())
        feats = words + [f"{a} {b}" for a, b in zip(words, words[1:])]
        v = [0.0] * self.dim
        for f in feats:
            h = hashlib.sha256(f.encode("utf-8")).digest()
            v[int.from_bytes(h[:4], "big") % self.dim] += 1.0 if h[4] & 1 else -1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [round(x / n, 6) for x in v]


def item_text(doc: dict) -> dict:
    """The exact, canonical input that is embedded (and hashed into content_hash)."""
    norm = doc.get("normalized") or {}
    return {"type": doc.get("type"), "category": doc.get("category"), "subcategory": doc.get("subcategory"),
            "title": norm.get("title"), "description": norm.get("description")}


def _as_text(t: dict) -> str:
    return " ".join(str(v) for v in t.values() if v)


def _vec(v: list[float]) -> str:
    return "[" + ",".join(repr(x) for x in v) + "]"


def refresh(conn: psycopg.Connection, embedder: Embedder) -> int:
    """Embed every item whose row is missing or whose content_hash changed. Returns rows written."""
    current = dict(conn.execute("SELECT item_id, content_hash FROM mbos.item_embeddings WHERE model_id=%s "
                                "AND model_version=%s", (embedder.model_id, embedder.model_version)).fetchall())
    n = 0
    for item_id, doc in conn.execute("SELECT item_id, doc FROM mbos.items ORDER BY item_id").fetchall():
        t = item_text(doc)
        h = mbos_canonical.sha256_of(t)
        if current.get(item_id) == h:
            continue
        conn.execute(
            """INSERT INTO mbos.item_embeddings (item_id, model_id, model_version, content_hash, embedding)
               VALUES (%s,%s,%s,%s,%s::mbos_ext.vector)
               ON CONFLICT (item_id, model_id, model_version)
               DO UPDATE SET content_hash = EXCLUDED.content_hash, embedding = EXCLUDED.embedding, embedded_at = now()""",
            (item_id, embedder.model_id, embedder.model_version, h, _vec(embedder.embed(_as_text(t)))))
        n += 1
    return n


def rebuild(conn: psycopg.Connection, embedder: Embedder) -> int:
    """Drop the index and every row for this model, then regenerate both, atomically (owner maintenance)."""
    with conn.transaction():
        conn.execute("DROP INDEX IF EXISTS mbos.item_embeddings_hnsw")
        conn.execute("DELETE FROM mbos.item_embeddings WHERE model_id=%s AND model_version=%s",
                     (embedder.model_id, embedder.model_version))
        n = refresh(conn, embedder)
        conn.execute("CREATE INDEX item_embeddings_hnsw ON mbos.item_embeddings "
                     "USING hnsw (embedding mbos_ext.vector_cosine_ops)")
    return n


def verify(conn: psycopg.Connection, embedder: Embedder) -> list[str]:
    """Drift between the index and its source. Empty = in sync."""
    problems = []
    rows = dict(conn.execute("SELECT item_id, content_hash FROM mbos.item_embeddings WHERE model_id=%s "
                             "AND model_version=%s", (embedder.model_id, embedder.model_version)).fetchall())
    items = dict(conn.execute("SELECT item_id, doc FROM mbos.items").fetchall())
    for item_id, doc in items.items():
        if item_id not in rows:
            problems.append(f"missing {item_id}")
        elif rows[item_id] != mbos_canonical.sha256_of(item_text(doc)):
            problems.append(f"stale {item_id}")
    problems += [f"orphan {i}" for i in rows if i not in items]
    return problems


def search(conn: psycopg.Connection, embedder: Embedder, text: str, k: int = 10, exact: bool = False) -> list[tuple[str, float]]:
    """Nearest items. exact=True forces a sequential scan (ground truth); otherwise the HNSW index is used."""
    with conn.transaction():
        if exact:
            conn.execute("SET LOCAL enable_indexscan = off")
            conn.execute("SET LOCAL enable_bitmapscan = off")
        else:
            conn.execute("SET LOCAL hnsw.ef_search = 200")
        return [(r[0], round(r[1], 9)) for r in conn.execute(
            "SELECT item_id, distance FROM mbos.similar_items(%s::mbos_ext.vector, %s, %s, %s)",
            (_vec(embedder.embed(text)), embedder.model_id, embedder.model_version, k))]
