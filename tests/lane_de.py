"""Test helper (B-09): a throwaway PostgreSQL 16 cluster with lane D's canonical schema (Agent 04 @ 14bd690,
migrations 0000–0007, test-only copy) and lane E's real gateway (Agent 05 @ 1c554cb). Every role connects as its
own login over a private unix socket, so privilege checks are real — mirrors Agent 05's E-02 harness."""

from __future__ import annotations

import itertools
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"
STATE = FIX / "agent04_state_14bd690"
POLICY = FIX / "agent05_policy_1c554cb"
TEMPLATE = "mbos02_tpl"
LOGIN = {"superuser": "postgres", "agent_write": "mbos_state_mcp", "gateway": "mbos_gateway",
         "approver": "mbos_operator_ui", "policy_admin": "mbos_policy", "reader": "mbos_reader"}
_n = itertools.count()


def _pg_bin() -> Path:
    import pgserver
    return Path(pgserver.__file__).parent / "pginstall" / "bin"


class Cluster:
    def __init__(self) -> None:
        import psycopg
        self.root = Path(tempfile.mkdtemp(prefix="mbos02-pg-"))
        self.sock = Path(tempfile.mkdtemp(prefix="m02-", dir=os.environ.get("XDG_RUNTIME_DIR") or "/tmp"))
        self.port = int(os.environ.get("MBOS02_TEST_PORT", "55502"))
        b = _pg_bin()
        subprocess.run([b / "initdb", "-D", self.root / "data", "--auth=trust", "--encoding=UTF8", "--locale=C.UTF-8",
                        "-U", "postgres"], check=True, capture_output=True)
        subprocess.run([b / "pg_ctl", "-D", self.root / "data", "-l", self.root / "pg.log", "-w", "start", "-o",
                        f"-p {self.port} -k {self.sock} -c listen_addresses='' -c timezone=UTC -c fsync=off"],
                       check=True, capture_output=True)
        self.base = f"host={self.sock} port={self.port}"
        with psycopg.connect(f"{self.base} dbname=postgres user=postgres", autocommit=True) as c:
            c.execute((STATE / "bootstrap" / "roles.sql").read_text())
            c.execute(f"CREATE DATABASE {TEMPLATE} OWNER mbos_owner")
        with psycopg.connect(f"{self.base} dbname={TEMPLATE} user=postgres", autocommit=True) as c:
            c.execute("CREATE SCHEMA dbos AUTHORIZATION mbos_dbos")
        sys.path.insert(0, str(STATE))
        try:
            from mbos_state import migrate
            migrate.migrate(f"{self.base} dbname={TEMPLATE} user=postgres", log=lambda *_: None)
        finally:
            sys.path.remove(str(STATE))
            sys.modules.pop("mbos_state.migrate", None)
            sys.modules.pop("mbos_state", None)

    def stop(self) -> None:
        subprocess.run([_pg_bin() / "pg_ctl", "-D", self.root / "data", "-m", "immediate", "-w", "stop"],
                       capture_output=True)
        shutil.rmtree(self.root, ignore_errors=True)
        shutil.rmtree(self.sock, ignore_errors=True)


class LaneE:
    """Fresh database from the template + Agent 05's real ActionGateway / PgPanicStore."""

    def __init__(self, cluster: Cluster, tmp: Path) -> None:
        import psycopg
        from mbos_governance import ActionGateway, PgGovernanceStore, PgPanicStore, PolicyStore
        self.cluster, self.name = cluster, f"b09_{next(_n)}_{os.getpid()}"
        with psycopg.connect(self.dsn("superuser").replace(f"dbname={self.name}", "dbname=postgres"), autocommit=True) as c:
            c.execute(f"CREATE DATABASE {self.name} TEMPLATE {TEMPLATE} OWNER mbos_owner")
        pol = tmp / "policy"
        shutil.copytree(POLICY, pol, ignore=shutil.ignore_patterns("PINNED.txt"))
        now = datetime.now(timezone.utc) + timedelta(days=1)
        self.store = PgGovernanceStore({r: self.dsn(r) for r in ("agent_write", "gateway", "approver", "policy_admin")})
        self.gw = ActionGateway(self.store, PolicyStore(pol / "policy.v1.json"), PgPanicStore(self.dsn("gateway")),
                                clock=lambda: now, journal_path=tmp / "panic.journal.jsonl")
        self.gw.release_panic("L3", None, "michael", "test bootstrap: release initial FROZEN")
        self.reader_panic = PgPanicStore(self.dsn("reader"))       # what discovery uses: a read-only login

    def dsn(self, role: str) -> str:
        return f"{self.cluster.base} dbname={self.name} user={LOGIN[role]}"

    def close(self) -> None:
        self.store.close()
