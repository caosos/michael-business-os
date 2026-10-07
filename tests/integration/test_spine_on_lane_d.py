"""A-01 phase 2: the spine's full DBOS lifecycle on Agent 04's canonical store (R1), in its own process
(DBOS is a per-process singleton). Lane D's schema comes from its pushed head via `git archive`."""

from __future__ import annotations

import json

import pytest

from tests.helpers import lane_d
from tests.helpers.common import fixture_variant
from tests.helpers.proc import line, run_runner


@pytest.fixture(scope="module")
def lane_d_urls(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    src = tmp_path_factory.mktemp("lane-d-src")
    lane_d.extract(src)
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pgd")), cleanup_mode="stop")
    app = lane_d.build(server, src, "mbos_e2e")
    server.psql("CREATE DATABASE mbos_e2e_sys;")
    yield app, server.get_uri().replace("/postgres?", "/mbos_e2e_sys?")
    server.cleanup()


def test_full_lifecycle_on_lane_d(lane_d_urls, tmp_path):
    fixture = fixture_variant(tmp_path, "ld", ["FIX-TRAILER-1", "FIX-LEAD-SMARTHOME-1", "FIX-MOWER-1"])
    cp = run_runner(lane_d_urls, "lane_d_e2e", str(fixture), timeout=180)
    assert cp.returncode == 0, cp.stdout[-3000:] + cp.stderr[-4000:]
    r = json.loads(line(cp, "RESULT"))
    assert r["final"]["trailer"] == "AWAITING_APPROVAL" and r["final"]["mower"] == "ARCHIVED"
    assert r["final"]["trailer_after"] == "ACTED", r
    assert r["final"]["smart_after"] == "ARCHIVED"
    assert r["chain"]["ok"], r["chain"]
    assert r["reference_chain"][0], r["reference_chain"]          # ADR-0010: verifiable without trusting the DB
    assert r["effector_calls"] == 1 and r["live_effector_calls"] == 0 and r["executed"] == 1
    assert not r["contract_errors"], r["contract_errors"]
