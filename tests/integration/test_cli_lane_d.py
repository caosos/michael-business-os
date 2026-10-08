"""A-37: the `mbos` operator CLI on a lane D database (built by lane D's provisioner, worker + owner logins).
Every command must work against lane D's schema and must apply NO reference migration to it."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict

import pytest
import sqlalchemy as sa

from mbos import cli, config, spine_d
from mbos.config import Settings
from mbos.db.engine import engine_for
from mbos.reference.fixture_adapter import FixtureSourceAdapter
from mbos.runtime import Components
from tests.helpers import lane_d
from tests.helpers.common import FIXTURE


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    src = tmp_path_factory.mktemp("cli-lane-d-src")
    lane_d.extract(src)
    server = pgserver.get_server(str(tmp_path_factory.mktemp("cli-pg")), cleanup_mode="stop")
    try:
        app, sysu, owner = lane_d.build_as_worker(server, src, "mbos_cli")
        yield app, sysu, owner
    finally:
        server.cleanup()


@pytest.fixture(scope="module")
def seeded(db):
    app, sysu, owner = db
    config.configure(Settings(database_url=app, system_database_url=sysu, owner_database_url=owner, state_backend="lane_d"))
    comps = Components().with_defaults("lane_d")
    engine = engine_for(app)
    raw = next(r for r in FixtureSourceAdapter(FIXTURE, name="fixture").fetch() if r.source_listing_id == "FIX-TRAILER-1")
    norm = comps.normalizer.normalize(raw)
    with engine.begin() as c:
        item_id = spine_d.ingest(c, asdict(raw), asdict(norm), "fixture", "0.1.0", comps)["item_id"]
    with engine.begin() as c:
        item = spine_d.read_item(c, item_id)
    with engine.begin() as c:
        spine_d.record_score(c, item_id, asdict(comps.scorer.score(item)))
    with engine.begin() as c:
        areq = spine_d.route_recommendation(c, item_id, comps)["action_request_id"]
    assert areq
    yield {"item_id": item_id, "areq": areq, "engine": engine}
    config._override = None
    config.settings.cache_clear()


def ns(**kw):
    return argparse.Namespace(**kw)


def test_read_commands_work_and_apply_no_reference_migration(seeded, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_wake", lambda *a, **k: None)
    iid, areq = seeded["item_id"], seeded["areq"]
    assert cli.cmd_items(ns(state=None, limit=10)) == 0
    assert iid in capsys.readouterr().out
    assert cli.cmd_queue(ns()) == 0
    q = capsys.readouterr().out
    assert f"item    {iid}" in q and areq in q
    assert cli.cmd_show(ns(item_id=iid)) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["item"]["item_id"] == iid and shown["receipts"]
    assert cli.cmd_card(ns(item_id=iid, json=True)) == 0
    assert json.loads(capsys.readouterr().out)
    assert cli.cmd_audit(ns()) == 0
    audit = json.loads(capsys.readouterr().out)
    assert audit["chain"]["ok"] and audit["conformance"]["counts"]["item"] == 1
    assert cli.cmd_note(ns(action="list")) == 0
    capsys.readouterr()
    with seeded["engine"].connect() as c:
        assert not c.execute(sa.text("SELECT count(*) FROM pg_catalog.pg_tables WHERE tablename = 'mbos_schema_migrations'")).scalar_one()


def test_owner_commands_decide_outcome_panic(seeded, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_wake", lambda *a, **k: None)
    iid, areq = seeded["item_id"], seeded["areq"]
    with seeded["engine"].connect() as c:
        h = c.execute(sa.text("SELECT payload_hash FROM mbos.action_requests WHERE action_request_id = :a"), {"a": areq}).scalar_one()
    assert cli.cmd_panic(ns(key="global_freeze", state="on", reason="a-37 test")) == 0
    assert json.loads(capsys.readouterr().out)["frozen"] is True
    assert cli.cmd_panic(ns(key="global_freeze", state="off", reason="a-37 test release")) == 0
    assert json.loads(capsys.readouterr().out)["frozen"] is False
    assert cli.cmd_decide(ns(areq=areq, decision="NO", seen=h[7:19], reason="not now", step_up=False, change=None,
                             hold_until=None, renotify=None, escalate=None)) == 0
    assert json.loads(capsys.readouterr().out)["approval"]["decision"] == "NO"
    assert cli.cmd_outcome(ns(item_id=iid, kind="flip_passed_missed", revenue=None, cost=None, hours=None, notes="a-37")) == 0
    assert json.loads(capsys.readouterr().out)["item_id"] == iid
    assert cli.cmd_audit(ns()) == 0
    capsys.readouterr()
    with seeded["engine"].connect() as c:
        assert not c.execute(sa.text("SELECT count(*) FROM pg_catalog.pg_tables WHERE tablename = 'mbos_schema_migrations'")).scalar_one()
