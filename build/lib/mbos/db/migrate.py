"""Minimal forward-only SQL migrator. Applied files are recorded with their sha256;
editing an applied migration is refused (write a new numbered file instead)."""

from __future__ import annotations

import hashlib
from importlib import resources

import sqlalchemy as sa


def _migrations() -> list[tuple[str, str]]:
    root = resources.files("mbos.db") / "migrations"
    files = sorted(p for p in root.iterdir() if p.name.endswith(".sql"))
    return [(p.name, p.read_text()) for p in files]


def migrate(engine: sa.Engine) -> list[str]:
    applied_now: list[str] = []
    with engine.begin() as conn:
        conn.execute(sa.text("SELECT pg_advisory_xact_lock(hashtext('mbos.migrate'))"))
        conn.execute(sa.text(
            "CREATE TABLE IF NOT EXISTS public.mbos_schema_migrations ("
            " filename text PRIMARY KEY, sha256 text NOT NULL, applied_at timestamptz NOT NULL DEFAULT now())"))
        done = dict(conn.execute(sa.text("SELECT filename, sha256 FROM public.mbos_schema_migrations")).all())
        for name, sql in _migrations():
            digest = hashlib.sha256(sql.encode()).hexdigest()
            if name in done:
                if done[name] != digest:
                    raise RuntimeError(f"migration {name} was edited after being applied; add a new migration instead")
                continue
            with conn.connection.driver_connection.cursor() as cur:  # no param parsing: SQL uses '%'
                cur.execute(sql)
            conn.execute(sa.text("INSERT INTO public.mbos_schema_migrations (filename, sha256) VALUES (:f, :h)"),
                         {"f": name, "h": digest})
            applied_now.append(name)
    return applied_now
