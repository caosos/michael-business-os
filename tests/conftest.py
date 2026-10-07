"""Test infrastructure. Postgres 16 comes from `pgserver` (project-local, no system install);
production uses Podman Postgres 16 per ADR-0001 — the SQL is the same."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from mbos.config import Settings, configure
from mbos.db.engine import engine_for
from mbos.db.migrate import migrate
from tests.helpers.common import create_database


@pytest.fixture(scope="session")
def pg(tmp_path_factory):
    import pgserver

    server = pgserver.get_server(str(tmp_path_factory.mktemp("pgdata")), cleanup_mode="stop")
    yield server
    server.cleanup()


@pytest.fixture()
def ledger_db(pg) -> sa.Engine:
    """A fresh, migrated app database (no DBOS) for ledger-level tests."""
    url = create_database(pg, "ledger")
    configure(Settings(database_url=url, system_database_url=url))
    engine = engine_for(url)
    migrate(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def rt(pg, tmp_path_factory):
    """One launched DBOS runtime over a fresh app DB + system DB, shared by workflow tests."""
    from mbos.runtime import Components, init_runtime, shutdown

    s = Settings(database_url=create_database(pg, "app"), system_database_url=create_database(pg, "sys"),
                 approval_poll_seconds=0.5)
    runtime = init_runtime(s, Components())
    runtime.fixture_dir = tmp_path_factory.mktemp("fixtures")
    yield runtime
    # Test-only teardown: workflows still parked at the approval gate would keep polling after the
    # test Postgres stops. (In production they stay PENDING and resume on the next launch.)
    import time

    from dbos import DBOS

    pending = [w.workflow_id for w in DBOS.list_workflows(status="PENDING", load_input=False, load_output=False)]
    if pending:
        DBOS.cancel_workflows(pending)
        time.sleep(1.0)
    shutdown()


@pytest.fixture()
def run_discovery(rt):
    """Discover a fixture variant through the real DBOS workflow; returns {source_listing_id: item_id}."""
    import uuid

    from dbos import DBOS, SetWorkflowID

    from mbos import workflows
    from mbos.reference.fixture_adapter import FixtureSourceAdapter
    from mbos.runtime import components
    from tests.helpers.common import fixture_variant

    def _run(*ids: str) -> dict[str, str]:
        tag = uuid.uuid4().hex[:8]
        name = f"fixture-{tag}"
        configure(rt.settings)  # ledger_db tests may have re-pointed settings
        components().adapters[name] = FixtureSourceAdapter(fixture_variant(rt.fixture_dir, tag, ids), name=name)
        with SetWorkflowID(f"discover:{name}"):
            results = DBOS.start_workflow(workflows.discover, name).get_result()
        base = {f"{i}-{tag}": i for i in ids}
        out = {}
        with rt.engine.connect() as c:
            for r in results:
                if r["item_id"]:
                    for s in c.execute(sa.text("SELECT body->'sources' FROM mbos.items WHERE item_id = :i"),
                                       {"i": r["item_id"]}).scalar_one():
                        if s.get("source_listing_id") in base:
                            out[base[s["source_listing_id"]]] = r["item_id"]
        return out

    return _run
