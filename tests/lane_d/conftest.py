"""F-04 fixtures: the Operator UI on Agent 04's canonical store (lane D) with Agent 05's REAL gateway, PDP and
kill switch (lane E), through the real DBOS workflow. Lane D's schema comes from its pushed head via
`git archive` (read-only, never merged); Agent 05's whole policy/ directory likewise (each file fails closed).

Run: MBOS_UI_LANE_D=1 .venv/bin/python -m pytest -q tests  (own process; see tests/conftest.py).
The cluster user is a superuser, so these tests do not exercise lane D's role grants. See the receipt.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import sqlalchemy as sa

from tests.conftest import FIXTURE, PIN, _create_db  # noqa: F401  (PIN re-exported for tests)

ROOT = Path(__file__).resolve().parents[2]
LANE_D_REF = os.environ.get("MBOS_STATE04_REF", "origin/research/agent-04-state")
LANE_E_REF = os.environ.get("MBOS_GOV05_REF", "origin/research/agent-05-governance")


def _archive(ref: str, path: str, dest: Path) -> str:
    sha = subprocess.run(["git", "rev-parse", "--short", ref], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    tar = subprocess.run(["git", "archive", ref, path], cwd=ROOT, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(dest, filter="data")
    return sha


@pytest.fixture(scope="session")
def pg(tmp_path_factory):  # noqa: F811 — own cluster, lane D needs roles.sql
    pgserver = pytest.importorskip("pgserver")
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pgd")), cleanup_mode="stop")
    yield server
    server.cleanup()


@pytest.fixture(scope="session")
def lane_d_src(tmp_path_factory):
    d = tmp_path_factory.mktemp("lane-d-src")
    return d, _archive(LANE_D_REF, "state", d)


@pytest.fixture(scope="session")
def policy_path(tmp_path_factory):
    d = tmp_path_factory.mktemp("lane-e-policy")
    _archive(LANE_E_REF, "policy", d)
    p = d / "policy" / "policy.v1.json"
    assert p.exists() and (d / "policy" / "content_rules.v1.json").exists()
    return str(p)


def _build_lane_d(server, src: Path, dbname: str) -> str:
    import psycopg

    server.psql((src / "state/bootstrap/roles.sql").read_text())
    server.psql(f"CREATE DATABASE {dbname} OWNER mbos_owner;")
    url = server.get_uri().replace("/postgres?", f"/{dbname}?")
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("CREATE SCHEMA IF NOT EXISTS mbos_ext")
        c.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA mbos_ext")
        c.execute("GRANT USAGE ON SCHEMA mbos_ext TO agent_read, agent_write, gateway, approver, policy_admin, mbos_owner")
    sys.path.insert(0, str(src / "state"))
    try:
        import importlib

        importlib.import_module("mbos_state.migrate").migrate(url, log=lambda *_: None)
    finally:
        sys.path.remove(str(src / "state"))
        for m in [m for m in sys.modules if m.startswith("mbos_state")]:
            del sys.modules[m]
    return url


@pytest.fixture(scope="session")
def rtd(pg, lane_d_src, policy_path):
    """One launched DBOS runtime: state_backend=lane_d, gateway_mode=lane_e."""
    import dataclasses

    from dbos import DBOS

    from mbos import spine_d
    from mbos.adapters.governance import lane_e_components
    from mbos.config import Settings
    from mbos.runtime import init_runtime, shutdown

    src, _sha = lane_d_src
    url = _build_lane_d(pg, src, "mbos_ui_" + uuid.uuid4().hex[:8])
    sysurl = _create_db(pg, "sys")
    s = Settings(database_url=url, system_database_url=sysurl, approval_poll_seconds=0.5)
    s = dataclasses.replace(s, state_backend="lane_d", gateway_mode="lane_e")
    comps, gov = lane_e_components(url, policy_path)
    rt = init_runtime(s, comps)
    rt.gov, rt.url = gov, url
    with rt.engine.begin() as c:  # a fresh lane D DB is FROZEN; Michael (owner) releases it, receipted
        spine_d.set_kill_switch(c, "global_freeze", False, reason="UI test bootstrap: release the initial FROZEN state")
    import tempfile

    rt.fixture_dir = Path(tempfile.mkdtemp(prefix="ui-fx-"))
    yield rt
    pending = [w.workflow_id for w in DBOS.list_workflows(status="PENDING", load_input=False, load_output=False)]
    if pending:
        DBOS.cancel_workflows(pending)
        time.sleep(1.0)
    shutdown()


@pytest.fixture()
def discover_d(rtd):
    from dbos import DBOS, SetWorkflowID

    from mbos import workflows
    from mbos.reference.fixture_adapter import FixtureSourceAdapter
    from mbos.runtime import components

    def _run(*ids: str) -> dict[str, str]:
        tag = uuid.uuid4().hex[:8]
        data = json.loads(Path(FIXTURE).read_text())
        out = []
        for rec in data["listings"]:
            if rec["source_listing_id"] in ids:
                rec["source_listing_id"] = f"{rec['source_listing_id']}-{tag}"
                rec["url"] = f"{rec['url']}?t={tag}"
                rec["record"]["dedup_key"] = f"{rec['record']['dedup_key']}|{tag}"
                out.append(rec)
        path = rtd.fixture_dir / f"fx-{tag}.json"
        path.write_text(json.dumps({"listings": out}))
        name = f"fixture-{tag}"
        components().adapters[name] = FixtureSourceAdapter(path, name=name)
        with SetWorkflowID(f"discover:{name}"):
            DBOS.start_workflow(workflows.discover, name).get_result()
        res = {}
        with rtd.engine.connect() as c:
            for i in ids:
                res[i] = c.execute(sa.text("SELECT item_id FROM mbos.v_item_documents WHERE doc->'sources' @> CAST(:s AS jsonb)"),
                                   {"s": json.dumps([{"source_listing_id": f"{i}-{tag}"}])}).scalar_one()
        return res

    return _run


@pytest.fixture()
def ui_d(rtd):
    """The real HTTP server over the lane D backend, with the SAME Components as the worker."""
    from mbos.runtime import components

    from operator_ui.backend import SpineBackend
    from operator_ui.server import App, make_handler

    app = App(SpineBackend(rtd.engine, components(), lane="lane_d"), operator_pin=PIN)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()
