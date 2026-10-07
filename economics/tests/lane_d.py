"""Throwaway lane-D database harness (test/dev only; mirrors Agent 04's own test conftest).

Starts a private PostgreSQL 16 cluster from the ``pgserver`` wheel, creates 04's roles, migrates 04's
schema from a read-only archive of ``research/agent-04-state``, yields a DSN, and destroys everything on
exit. Nothing shared is touched. Needs: psycopg, pgserver, and Agent 04's ``mbos_state`` importable;
``MBOS_LANE_D_STATE_DIR`` points at the archived ``state/`` directory.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def available() -> str | None:
    """None if the harness can run, else the reason it cannot."""
    state = os.environ.get("MBOS_LANE_D_STATE_DIR")
    if not state or not (Path(state) / "migrations").is_dir():
        return "MBOS_LANE_D_STATE_DIR not set to Agent 04's state/ directory"
    for mod in ("psycopg", "pgserver", "mbos_state"):
        try:
            __import__(mod)
        except ImportError:
            return f"{mod} not installed"
    return None


@contextlib.contextmanager
def cluster(state_dir: Path | None = None, port: int | None = None):
    import pgserver
    import psycopg
    from mbos_state import migrate

    state_dir = Path(state_dir or os.environ["MBOS_LANE_D_STATE_DIR"])
    b = Path(pgserver.__file__).parent / "pginstall" / "bin"
    root = Path(tempfile.mkdtemp(prefix="c03-"))
    sock = Path(tempfile.mkdtemp(prefix="c03-", dir=os.environ.get("XDG_RUNTIME_DIR") or "/tmp"))  # <107-byte path
    data, port = root / "data", port or int(os.environ.get("C03_PG_PORT", "55471"))
    subprocess.run([b / "initdb", "-D", data, "--auth=trust", "--encoding=UTF8", "--locale=C.UTF-8", "-U", "postgres"],
                   check=True, capture_output=True)
    subprocess.run([b / "pg_ctl", "-D", data, "-l", root / "pg.log", "-w", "start", "-o",
                    f"-p {port} -k {sock} -c listen_addresses='' -c timezone=UTC"], check=True, capture_output=True)
    base = f"host={sock} port={port}"
    try:
        with psycopg.connect(f"{base} dbname=postgres user=postgres", autocommit=True) as c:
            c.execute((state_dir / "bootstrap" / "roles.sql").read_text())
            c.execute("CREATE DATABASE mbos OWNER mbos_owner")
        with psycopg.connect(f"{base} dbname=mbos user=postgres", autocommit=True) as c:
            c.execute("CREATE SCHEMA dbos AUTHORIZATION mbos_dbos")
            c.execute("CREATE SCHEMA mbos_ext; CREATE EXTENSION vector WITH SCHEMA mbos_ext; "
                      "GRANT USAGE ON SCHEMA mbos_ext TO agent_read, agent_write, gateway, approver, policy_admin, mbos_owner")
        migrate.migrate(f"{base} dbname=mbos user=postgres", state_dir / "migrations", log=lambda *_: None)
        yield f"{base} dbname=mbos user=postgres"
    finally:
        subprocess.run([b / "pg_ctl", "-D", data, "-m", "immediate", "-w", "stop"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(sock, ignore_errors=True)


def write_scored(dsn: str, rows) -> None:
    """Write (item with scores+recommendation, score provenance, receipt drafts) through 04's StateStore:
    create NORMALIZED -> RESEARCHING -> SCORE_RECORDED -> RECOMMENDATION_RECORDED -> SCORED -> RECOMMENDED."""
    import psycopg
    from mbos_state.store import Actor, StateStore

    actor = Actor("agent", "agent-03-economics")
    with psycopg.connect(dsn, autocommit=False) as conn:
        st = StateStore(conn)
        for item, prov, drafts in rows:
            iid = item["item_id"]
            with st.transaction():
                pid = st.record_provenance(**{k: v for k, v in prov.items() if k != "derived_from"})
                base = {k: v for k, v in item.items() if k not in ("scores", "recommendation", "state")}
                base["state"] = "NORMALIZED"
                st.create_item(base, actor, "create", [pid], f"c03:create:{iid}")
                st.transition_item(iid, "RESEARCHING", actor, "research", [pid], f"c03:researching:{iid}")
                sd = next(d for d in drafts if d["type"] == "SCORE_RECORDED")
                st.update_item_doc(iid, {"scores": item["scores"]}, "SCORE_RECORDED", actor, "score", [pid],
                                   sd["idempotency_key"], extra={"inputs_hash": sd["inputs_hash"],
                                                                 "payload_hash": sd["payload_hash"],
                                                                 "tool_name": sd["tool_name"]})
                rd = next(d for d in drafts if d["type"] == "RECOMMENDATION_RECORDED")
                st.update_item_doc(iid, {"recommendation": item["recommendation"]}, "RECOMMENDATION_RECORDED", actor,
                                   "recommend", [pid], rd["idempotency_key"])
                st.transition_item(iid, "SCORED", actor, "scored", [pid], f"c03:scored:{iid}")
                st.transition_item(iid, "RECOMMENDED", actor, "recommended", [pid], f"c03:recommended:{iid}")
