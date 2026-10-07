"""Test harness: a throwaway PostgreSQL 16 cluster per test session, migrated once into a template DB,
then one fresh database per test (CREATE DATABASE ... TEMPLATE) so tamper tests cannot leak.

Login roles connect over a private unix socket with trust auth (test cluster only); privilege checks are
therefore real role checks, not SET ROLE simulations.
"""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

import psycopg
import pytest

from mbos_state import migrate
from mbos_state.store import Actor, StateStore

STATE_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_DB = "mbos_tpl"


def _pg_bin() -> Path:
    if os.environ.get("PG_BIN"):
        return Path(os.environ["PG_BIN"])
    if Path("/usr/lib/postgresql/16/bin/pg_ctl").exists():
        return Path("/usr/lib/postgresql/16/bin")
    import pgserver  # wave-one fallback: PostgreSQL 16 binaries from the pgserver wheel

    return Path(pgserver.__file__).parent / "pginstall" / "bin"


@pytest.fixture(scope="session")
def cluster():
    pg_bin = _pg_bin()
    root = Path(tempfile.mkdtemp(prefix="mbos-test-"))
    # unix socket paths are limited to 107 bytes: keep the socket dir short
    sock = Path(tempfile.mkdtemp(prefix="mbos-", dir=os.environ.get("XDG_RUNTIME_DIR") or "/tmp"))
    data = root / "data"
    port = int(os.environ.get("MBOS_TEST_PORT", "55433"))
    subprocess.run([pg_bin / "initdb", "-D", data, "--auth=trust", "--encoding=UTF8", "--locale=C.UTF-8",
                    "--data-checksums", "-U", "postgres"], check=True, capture_output=True)
    subprocess.run([pg_bin / "pg_ctl", "-D", data, "-l", root / "pg.log", "-w", "start", "-o",
                    f"-p {port} -k {sock} -c listen_addresses='' -c timezone=UTC -c max_connections=200"],
                   check=True, capture_output=True)
    base = f"host={sock} port={port}"
    try:
        with psycopg.connect(f"{base} dbname=postgres user=postgres", autocommit=True) as c:
            c.execute((STATE_DIR / "bootstrap" / "roles.sql").read_text())
            c.execute(f"CREATE DATABASE {TEMPLATE_DB} OWNER mbos_owner")
        with psycopg.connect(f"{base} dbname={TEMPLATE_DB} user=postgres", autocommit=True) as c:
            c.execute("CREATE SCHEMA dbos AUTHORIZATION mbos_dbos")   # as bootstrap.sh does
            c.execute("CREATE SCHEMA mbos_ext; CREATE EXTENSION vector WITH SCHEMA mbos_ext; "
                      "GRANT USAGE ON SCHEMA mbos_ext TO agent_read, agent_write, gateway, approver, policy_admin, mbos_owner")
        migrate.migrate(f"{base} dbname={TEMPLATE_DB} user=postgres", log=lambda *_: None)
        yield {"base": base, "pg_bin": pg_bin, "root": root}
    finally:
        subprocess.run([pg_bin / "pg_ctl", "-D", data, "-m", "immediate", "-w", "stop"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(sock, ignore_errors=True)


_counter = itertools.count()


class DB:
    """One fresh migrated database. connect(role) opens a connection as a real login role."""

    LOGIN = {
        "superuser": "postgres", "owner": "mbos_migrator", "reader": "mbos_reader", "agent_write": "mbos_state_mcp",
        "gateway": "mbos_gateway", "approver": "mbos_operator_ui", "policy_admin": "mbos_policy",
        "outbox_relay": "mbos_relay", "dbos": "mbos_dbos",
    }

    def __init__(self, base: str, name: str):
        self.base, self.name = base, name
        self._conns: list[psycopg.Connection] = []

    def dsn(self, role: str = "superuser") -> str:
        return f"{self.base} dbname={self.name} user={self.LOGIN[role]}"

    def connect(self, role: str = "superuser", autocommit: bool = True) -> psycopg.Connection:
        conn = psycopg.connect(self.dsn(role), autocommit=autocommit)
        if role == "owner":
            conn.execute("SET ROLE mbos_owner")
        self._conns.append(conn)
        return conn

    def store(self, role: str = "superuser") -> StateStore:
        return StateStore(self.connect(role))

    def close(self):
        for c in self._conns:
            c.close()


@pytest.fixture
def db(cluster):
    name = f"t_{os.getpid()}_{next(_counter)}"
    with psycopg.connect(f"{cluster['base']} dbname=postgres user=postgres", autocommit=True) as c:
        c.execute(f"CREATE DATABASE {name} TEMPLATE {TEMPLATE_DB} OWNER mbos_owner")
    d = DB(cluster["base"], name)
    yield d
    d.close()
    with psycopg.connect(f"{cluster['base']} dbname=postgres user=postgres", autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------
AGENT = Actor("agent", "agent-02-discovery")
GATEWAY = Actor("system", "action-gateway")
MICHAEL = Actor("human", "michael")
H64 = "sha256:" + "ab" * 32

_keys = itertools.count()


def key(label: str = "k") -> str:
    return f"test:{label}:{os.getpid()}:{next(_keys)}"


def tool_prov(store: StateStore) -> str:
    return store.record_provenance(actor_type="agent", agent_name="agent-02-discovery", basis="FACT",
                                   tool_name="test-tool", tool_version="0.0.1")


def source_prov(store: StateStore) -> str:
    return store.record_provenance(actor_type="external", basis="FACT", source_uri="https://example.test/listing/1",
                                   fetched_at="2026-10-07T12:00:00Z")


def flip_doc(**over) -> dict:
    doc = {
        "type": "flip", "category": "trailer", "subcategory": "utility trailer 6x12",
        "dedup_key": key("dedup"),
        "sources": [{"source": "craigslist", "url": "https://example.test/listing/1", "ingestion_method": "api",
                     "first_seen_at": "2026-10-07T12:00:00Z", "provenance_id": None}],
        "normalized": {"title": "6x12 utility trailer"},
    }
    doc.update(over)
    return doc


def make_item(store: StateStore, state: str = "DISCOVERED") -> tuple[str, str]:
    pid = source_prov(store)
    doc = flip_doc()
    doc["sources"][0]["provenance_id"] = pid
    item_id = store.create_item(doc, AGENT, "ingest listing", [pid], key("create"))
    path = ["NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL"]
    for s in path[: path.index(state) + 1] if state in path else []:
        store.transition_item(item_id, s, AGENT, f"advance to {s}", [pid], key("tr"))
    return item_id, pid


def make_areq(store: StateStore, item_id: str, pid: str, **over) -> str:
    areq = {
        "item_id": item_id, "proposed_by": "agent-06-comms", "capability": "comms.email.send", "category": "email",
        "payload": {"to_ref": "party_1", "template": "seller_question_v1", "body": "Is the trailer still available?"},
        "idempotency_key": key("effect"), "reversibility": "irreversible", "tier": 0,
        "expires_at": "2099-01-01T00:00:00Z", "provenance_ids": [pid],
    }
    areq.update(over)
    return store.propose_action(areq, AGENT, "ask the seller a question", key("propose"))


def payload_hash(store: StateStore, areq_id: str) -> str:
    return store.conn.execute("SELECT payload_hash FROM mbos.action_requests WHERE action_request_id=%s",
                              (areq_id,)).fetchone()[0]


def to_pending(gw: StateStore, areq_id: str, pid: str) -> None:
    gw.set_action_status(areq_id, "classified", "POLICY_DECIDED", GATEWAY, "PDP: tier 0", [pid], key("cls"),
                         extra={"policy_decision_ref": "pol:test"})
    gw.set_action_status(areq_id, "pending_approval", "APPROVAL_REQUESTED", GATEWAY, "ask Michael", [pid], key("req"))
