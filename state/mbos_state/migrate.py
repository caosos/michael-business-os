"""Apply state/migrations/*.sql in order, each in one transaction, as role mbos_owner.

Every applied migration is itself receipted: schema_migrations row + provenance + CONFIG_VERSION_BUMPED
receipt (+ outbox) commit together. Already-applied files are checksum-verified; an edited migration is
refused (write a new one instead).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import psycopg

from . import __version__

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
LOCK_KEY = 7340004002

BOOTSTRAP_META = """
CREATE SCHEMA IF NOT EXISTS mbos_meta;
CREATE TABLE IF NOT EXISTS mbos_meta.schema_migrations (
    version    text PRIMARY KEY,
    filename   text NOT NULL,
    sha256     text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now(),
    receipt_id text
);
"""


class MigrationDrift(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sha256: str

    @property
    def sql(self) -> str:
        return self.path.read_text(encoding="utf-8")


def discover(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    out = []
    for p in sorted(directory.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        digest = "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()
        out.append(Migration(version=p.name.split("_", 1)[0], path=p, sha256=digest))
    return out


def _receipt_for_migration(cur: psycopg.Cursor, m: Migration) -> str:
    cur.execute(
        "SELECT mbos.new_id('prov')",
    )
    prov_id = cur.fetchone()[0]
    cur.execute(
        """INSERT INTO mbos.provenance (provenance_id, actor_type, agent_name, basis, tool_name, tool_version,
                                        config_version, inputs_used)
           VALUES (%s, 'system', 'agent-04-state', 'FACT', 'mbos_state.migrate', %s, %s, %s::jsonb)""",
        (prov_id, __version__, m.version, json.dumps([{"ref": f"state/migrations/{m.path.name}", "hash": m.sha256}])),
    )
    cur.execute(
        """INSERT INTO mbos.receipts (type, actor, intent, entity_type, entity_id, effect, tool_name,
                                      inputs_hash, idempotency_key, provenance_ids, after_state)
           VALUES ('CONFIG_VERSION_BUMPED', '{"type":"system","id":"mbos-migrate"}', %s, 'schema_migration', %s,
                   'update', %s, %s, %s, ARRAY[%s], %s::jsonb)
           RETURNING receipt_id""",
        (
            f"apply schema migration {m.path.name}",
            m.version,
            f"mbos_state.migrate {__version__}",
            m.sha256,
            f"schema_migration:{m.version}:{m.sha256}",
            prov_id,
            json.dumps({"schema_version": m.version, "file": m.path.name}),
        ),
    )
    return cur.fetchone()[0]


def migrate(dsn: str, directory: Path = MIGRATIONS_DIR, *, log=print) -> list[str]:
    """Apply pending migrations. Returns the versions applied."""
    applied_now: list[str] = []
    migrations = discover(directory)
    by_version = {m.version: m for m in migrations}
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
        try:
            with conn.transaction():
                conn.execute("SET LOCAL ROLE mbos_owner")
                conn.execute(BOOTSTRAP_META)
            done = {v: s for v, s in conn.execute("SELECT version, sha256 FROM mbos_meta.schema_migrations")}
            for m in migrations:
                if m.version in done:
                    if done[m.version] != m.sha256:
                        raise MigrationDrift(
                            f"migration {m.path.name} changed after it was applied "
                            f"(db {done[m.version]}, file {m.sha256}); add a new migration instead"
                        )
                    continue
                with conn.transaction(), conn.cursor() as cur:
                    cur.execute("SET LOCAL ROLE mbos_owner")
                    cur.execute("SET LOCAL lock_timeout = '30s'")
                    cur.execute(m.sql)
                    cur.execute(
                        "INSERT INTO mbos_meta.schema_migrations (version, filename, sha256) VALUES (%s,%s,%s)",
                        (m.version, m.path.name, m.sha256),
                    )
                    # Receipt every migration not yet receipted, in order, once the ledger exists
                    # (0000 installs the ADR-0010 functions before 0001 creates the ledger).
                    receipt_id = None
                    if cur.execute("SELECT to_regclass('mbos.receipts')").fetchone()[0] is not None:
                        pending = cur.execute("SELECT version FROM mbos_meta.schema_migrations "
                                              "WHERE receipt_id IS NULL ORDER BY version").fetchall()
                        for (version,) in pending:
                            receipt_id = _receipt_for_migration(cur, by_version[version])
                            cur.execute("UPDATE mbos_meta.schema_migrations SET receipt_id = %s WHERE version = %s",
                                        (receipt_id, version))
                applied_now.append(m.version)
                log(f"applied {m.path.name}" + (f" ({receipt_id})" if receipt_id else " (receipt deferred until the ledger exists)"))
            with conn.transaction():
                conn.execute("SET LOCAL ROLE mbos_owner")
                conn.execute("GRANT USAGE ON SCHEMA mbos_meta TO agent_read")
                conn.execute("GRANT SELECT ON mbos_meta.schema_migrations TO agent_read")
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
    return applied_now
