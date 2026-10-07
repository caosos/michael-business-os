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
    assert not r["card_errors"], r["card_errors"]  # every opportunity renders a valid, honest card on lane D
    assert r["cards"]["trailer"][1] == "CONTACT" and r["cards"]["mower"][1] == "PASS", r["cards"]
    assert r["cards"]["enrichment_roundtrip"] == "medium", r["cards"]  # enrichment survives the lane-D ledger


def test_full_lifecycle_with_lane_e_gateway(tmp_path_factory, tmp_path):
    """A-03: Agent 05's real ActionGateway behind the spine on lane D (R4: the gateway owns action receipts)."""
    pytest.importorskip("mbos_governance.spine_adapter")
    import subprocess

    from tests.helpers.common import ROOT

    pgserver = pytest.importorskip("pgserver")
    src = tmp_path_factory.mktemp("lane-d-src-e")
    lane_d.extract(src)
    server = pgserver.get_server(str(tmp_path_factory.mktemp("pge")), cleanup_mode="stop")
    try:
        app = lane_d.build(server, src, "mbos_e")
        server.psql("CREATE DATABASE mbos_e_sys;")
        import io
        import tarfile

        # the whole policy directory: the policy, its schema and the E-04 content rules (each fails closed if missing)
        tar = subprocess.run(["git", "archive", "origin/research/agent-05-governance", "policy"], cwd=ROOT,
                             capture_output=True, check=True).stdout
        tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp_path, filter="data")
        policy = tmp_path / "policy" / "policy.v1.json"
        fixture = fixture_variant(tmp_path, "le", ["FIX-TRAILER-1", "FIX-LEAD-SMARTHOME-1", "FIX-MOWER-1"])
        cp = run_runner((app, server.get_uri().replace("/postgres?", "/mbos_e_sys?")), "lane_d_e2e", str(fixture), "lane_e",
                        timeout=180, extra_env={"MBOS_POLICY_PATH": str(policy), "MBOS_EGRESS_FILE": str(tmp_path / "egress.json"),
                                                "MBOS_LITELLM_FILE": str(tmp_path / "litellm.json")})
    finally:
        server.cleanup()
    assert cp.returncode == 0, cp.stdout[-3000:] + cp.stderr[-4000:]
    r = json.loads(line(cp, "RESULT"))
    assert r["final"]["trailer_after"] == "ACTED", r
    assert r["chain"]["ok"] and r["reference_chain"][0], r
    assert r["effector_calls"] == 1 and r["live_effector_calls"] == 0 and r["executed"] == 1
    assert r["receipt_types"].get("ACTION_EXECUTING") == 1, r["receipt_types"]  # exactly one per edge (R4)
    # A-18: PANIC runs through lane E (hooks, approver-only release) and the reconcile schedule exists
    pn = r["panic"]
    assert pn["engage_error"] is None and pn["frozen_blocks"] is True, pn
    assert pn["release_error"] is None and pn["released_blocks"] is False, pn
    assert pn["litellm_budgets"] and all(b == 0 for b in pn["litellm_budgets"]), pn  # L3 zeroed every LLM budget (lane E hook)
    assert pn["egress_file"], "lane E's egress deny-all policy file was written"
    assert r["reconcile_schedule"] in ("created", "unchanged", "replaced"), r["reconcile_schedule"]
    assert not r["contract_errors"], r["contract_errors"]
