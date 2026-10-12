"""Seed loader for the ADR-0015 source registry (D-37): validate config/sources.v1.json against its JSON schema, then upsert."""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import psycopg

CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def load_config(path: Path | None = None, schema_path: Path | None = None) -> list[dict]:
    doc = json.loads((path or CONFIG_DIR / "sources.v1.json").read_text())
    jsonschema.validate(doc, json.loads((schema_path or CONFIG_DIR / "sources.schema.json").read_text()))
    ids = [s["source_id"] for s in doc["sources"]]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate source_id in registry")
    return doc["sources"]


def load_sources(conn: psycopg.Connection, path: Path | None = None) -> int:
    """Upsert every validated row via mbos.upsert_source (the connection must be an owner_channel session). Returns the row count."""
    rows = load_config(path)
    for row in rows:
        conn.execute("SELECT mbos.upsert_source(%s)", (json.dumps(row),))
    return len(rows)
