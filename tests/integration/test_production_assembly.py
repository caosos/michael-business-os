"""A-36: `mbos worker` must run the REAL lanes when they are installed, and say plainly what is still a stand-in."""

import io
import subprocess
import tarfile

import pytest

from mbos.config import Settings
from mbos.production import build_components, render_report
from tests.helpers import lane_d
from tests.helpers.common import ROOT


@pytest.fixture(scope="module")
def assembled(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    pytest.importorskip("mbos_governance")
    pytest.importorskip("mbos_economics")
    tmp = tmp_path_factory.mktemp("prod")
    src = tmp / "src"
    src.mkdir()
    lane_d.extract(src)
    tar = subprocess.run(["git", "archive", "origin/research/agent-05-governance", "policy"], cwd=ROOT, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp, filter="data")
    server = pgserver.get_server(str(tmp / "pg"), cleanup_mode="stop")
    try:
        app, sysu, owner = lane_d.build_as_worker(server, src, "mbos_prod")
        import os

        os.environ["MBOS_POLICY_PATH"] = str(tmp / "policy" / "policy.v1.json")
        os.environ["MBOS_EGRESS_FILE"] = str(tmp / "egress.json")
        os.environ["MBOS_LITELLM_FILE"] = str(tmp / "litellm.json")
        s = Settings(database_url=app, system_database_url=sysu, state_backend="lane_d", gateway_mode="lane_e")
        yield build_components(s)
    finally:
        server.cleanup()


def test_the_real_lanes_are_wired_and_reported(assembled):
    comps, report = assembled
    by = {r["component"]: r for r in report}
    assert by["state store"]["kind"] == "REAL" and by["governance (PDP, gateway, PANIC)"]["kind"] == "REAL" and by["scoring"]["kind"] == "REAL"
    assert type(comps.scorer).__name__ == "EconomicsEngineScorer"
    assert type(comps.gateway).__module__.startswith("mbos_governance")
    assert any(type(e).__name__ == "EconomicsEnricher" for e in comps.enrichers)


def test_stand_ins_are_named_not_hidden(assembled):
    _, report = assembled
    text = render_report(report)
    assert "STAND-IN" in text and "sources" in text            # no live source until credentials exist
    assert all(r["detail"] for r in report)


def test_the_worker_assembly_never_holds_the_owner_login(assembled):
    comps, _ = assembled
    dsns = comps.governance.action_gateway.store.dsns
    assert dsns["approver"] == dsns["gateway"]                 # approver role falls back to the WORKER login: it cannot release PANIC (D-26)


def test_reference_settings_are_reported_as_stand_in():
    s = Settings(database_url="postgresql://x/y", system_database_url="postgresql://x/z")
    _, report = build_components(s)
    assert next(r for r in report if r["component"] == "state store")["kind"] == "STAND-IN"
