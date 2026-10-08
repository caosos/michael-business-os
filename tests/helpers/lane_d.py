"""Build a database on Agent 04's canonical schema at its PUSHED head (read-only `git archive`; never merged)."""

from __future__ import annotations

import importlib
import io
import os
import subprocess
import sys
import tarfile
from pathlib import Path

from tests.helpers.common import ROOT

REF = os.environ.get("MBOS_STATE04_REF", "origin/research/agent-04-state")


def extract(dest: Path, ref: str = REF) -> str:
    sha = subprocess.run(["git", "rev-parse", "--short", ref], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    tar = subprocess.run(["git", "archive", ref, "state"], cwd=ROOT, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(dest, filter="data")
    return sha


def build(server, src: Path, dbname: str) -> str:
    """roles.sql (idempotent per cluster) + CREATE DATABASE + lane D's own migrator. Returns the URL."""
    server.psql((src / "state/bootstrap/roles.sql").read_text())
    server.psql(f"CREATE DATABASE {dbname} OWNER mbos_owner;")
    url = server.get_uri().replace("/postgres?", f"/{dbname}?")
    # superuser-only bootstrap step from lane D's bootstrap.sh: pgvector in its own schema (D-08)
    import psycopg

    with psycopg.connect(url, autocommit=True) as c:
        c.execute("CREATE SCHEMA IF NOT EXISTS mbos_ext")
        c.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA mbos_ext")
        c.execute("GRANT USAGE ON SCHEMA mbos_ext TO agent_read, agent_write, gateway, approver, policy_admin, mbos_owner")
    sys.path.insert(0, str(src / "state"))
    try:
        importlib.import_module("mbos_state.migrate").migrate(url, log=lambda *_: None)
    finally:
        sys.path.remove(str(src / "state"))
        for m in [m for m in sys.modules if m.startswith("mbos_state")]:
            del sys.modules[m]
    return url


def build_as_worker(server, src: Path, dbname: str, login: str = "mbos_dbos") -> tuple[str, str, str]:
    """A-01 phase 2: provision the DB with 04's `provision()` (the only superuser step) and return (app_url, sys_url, owner_url) for the REAL worker
    login `mbos_dbos` (no approver, D-26a) and the owner login, so the spine and DBOS run with NO superuser, exactly as in production (roles, grants and PUBLIC stripped)."""
    sys.path.insert(0, str(src / "state"))
    try:
        prov = importlib.import_module("mbos_state.provision").provision(server.get_uri(), app_db=dbname, sys_db=f"{dbname}_sys", login=login)
    finally:
        sys.path.remove(str(src / "state"))
        for m in [m for m in sys.modules if m.startswith("mbos_state")]:
            del sys.modules[m]
    return prov.app_url, prov.sys_url, prov.owner_app_url
