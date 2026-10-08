"""Operator UI tests run against Agent 01's REAL spine (mbos @ bed7609, installed, not merged):
Postgres 16 from `pgserver` (project-local) + a launched DBOS runtime with the reference lanes."""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest
import sqlalchemy as sa

# DBOS is a per-process singleton, so the reference-backend suite and the lane D suite (F-04) cannot share a process.
#   .venv/bin/python -m pytest -q tests                      → reference backend (tests/test_*.py)
#   MBOS_UI_LANE_D=1 .venv/bin/python -m pytest -q tests     → lane D + lane E (tests/lane_d/)
# tools/run_tests.sh runs both.
if os.environ.get("MBOS_UI_LANE_D"):
    collect_ignore_glob = ["test_*.py"]
else:
    collect_ignore = ["lane_d"]

FIXTURE = Path(__file__).parent / "fixtures" / "illustrative.json"
# Contracts for mbos's schema validator (a non-editable install cannot find them): this branch's vendored copy,
# which includes card.schema.json (ADR-0011) byte-identical to the coordinator's.
os.environ.setdefault("MBOS_CONTRACTS_DIR", str(Path(__file__).resolve().parent.parent / "docs" / "research" / "contracts"))
# Lane A's operator profile, from the pinned mbos checkout (a non-editable install cannot find it; see backend.py).
os.environ.setdefault("MBOS_OPERATOR_PROFILE", str(Path(__file__).resolve().parent.parent / ".tools" / "mbos-e20d6af" / "config" / "operator_profile.v1.json"))
PIN = "4321"


def _create_db(server, prefix: str) -> str:
    name = f"{prefix}_{uuid.uuid4().hex[:10]}"
    server.psql(f"CREATE DATABASE {name};")
    return server.get_uri().replace("/postgres?", f"/{name}?")


@pytest.fixture(scope="session")
def pg(tmp_path_factory):
    import pgserver

    server = pgserver.get_server(str(tmp_path_factory.mktemp("pg")), cleanup_mode="stop")
    yield server
    server.cleanup()


@pytest.fixture(scope="session")
def rt(pg, tmp_path_factory):
    from dbos import DBOS

    from mbos.config import Settings
    from mbos.runtime import Components, init_runtime, shutdown

    s = Settings(database_url=_create_db(pg, "app"), system_database_url=_create_db(pg, "sys"),
                 approval_poll_seconds=0.5)
    runtime = init_runtime(s, Components())
    runtime.fixture_dir = tmp_path_factory.mktemp("fixtures")
    yield runtime
    pending = [w.workflow_id for w in DBOS.list_workflows(status="PENDING", load_input=False, load_output=False)]
    if pending:
        DBOS.cancel_workflows(pending)
        time.sleep(1.0)
    shutdown()


@pytest.fixture()
def discover(rt):
    """Discover fixture listings through the real DBOS workflow → {listing_id: item_id}."""
    from dbos import DBOS, SetWorkflowID

    from mbos import workflows
    from mbos.reference.fixture_adapter import FixtureSourceAdapter
    from mbos.runtime import components

    def _run(*ids: str, titles: dict | None = None) -> dict[str, str]:
        tag = uuid.uuid4().hex[:8]
        data = json.loads(FIXTURE.read_text())
        out = []
        for rec in data["listings"]:
            if rec["source_listing_id"] in ids:
                if titles and rec["source_listing_id"] in titles:  # hostile-text tests
                    rec["record"]["normalized"]["title"] = titles[rec["source_listing_id"]]
                rec["source_listing_id"] = f"{rec['source_listing_id']}-{tag}"
                rec["url"] = f"{rec['url']}?t={tag}"
                rec["record"]["dedup_key"] = f"{rec['record']['dedup_key']}|{tag}"
                out.append(rec)
        path = rt.fixture_dir / f"fx-{tag}.json"
        path.write_text(json.dumps({"listings": out}))
        name = f"fixture-{tag}"
        components().adapters[name] = FixtureSourceAdapter(path, name=name)
        with SetWorkflowID(f"discover:{name}"):
            DBOS.start_workflow(workflows.discover, name).get_result()
        res = {}
        with rt.engine.connect() as c:
            for i in ids:
                res[i] = c.execute(sa.text("SELECT item_id FROM mbos.items WHERE body->'sources' @> CAST(:s AS jsonb)"),
                                   {"s": json.dumps([{"source_listing_id": f"{i}-{tag}"}])}).scalar_one()
        return res

    return _run


@pytest.fixture()
def ui(rt):
    """The real HTTP server over the spine backend, on an ephemeral loopback port."""
    from operator_ui.backend import SpineBackend
    from operator_ui.server import App, make_handler

    app = App(SpineBackend(rt.engine), operator_pin=PIN)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()
