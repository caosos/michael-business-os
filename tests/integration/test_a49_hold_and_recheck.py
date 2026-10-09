"""A-49 (F-126, F-129) end to end on real PG16, lane D with the split logins, the real assembly (lane C engine, lane E gateway), and every
Michael action in a separate Operator-UI-like process: HOLD then YES straight from the HOLD list -> ACTED; HOLD -> Wake now -> YES -> ACTED;
inputs on a parked item -> one recheck per input, never two at once, no ERROR records."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile

import pytest

from tests.helpers import lane_d
from tests.helpers.common import ROOT
from tests.helpers.proc import line, run_runner

FIXTURE = ROOT / "fixtures" / "sources" / "training_examples.json"


@pytest.fixture(scope="module")
def result(tmp_path_factory):
    pgserver = pytest.importorskip("pgserver")
    pytest.importorskip("mbos_governance")
    pytest.importorskip("mbos_economics")
    tmp = tmp_path_factory.mktemp("a49")
    src = tmp / "src"
    src.mkdir()
    lane_d.extract(src)
    tar = subprocess.run(["git", "archive", "origin/research/agent-05-governance", "policy"], cwd=ROOT, capture_output=True, check=True).stdout
    tarfile.open(fileobj=io.BytesIO(tar)).extractall(tmp, filter="data")
    server = pgserver.get_server(str(tmp / "pg"), cleanup_mode="stop")
    try:
        app, sysu, owner = lane_d.build_as_worker(server, src, "mbos_a49")
        cp = run_runner((app, sysu), "hold_paths", str(FIXTURE), timeout=300, extra_env={
            "MBOS_OWNER_DATABASE_URL": owner, "PYTHONPATH": str(ROOT / "src") + ":" + str(ROOT), "MBOS_SCORER": "engine",
            "MBOS_POLICY_PATH": str(tmp / "policy" / "policy.v1.json"),
            "MBOS_EGRESS_FILE": str(tmp / "egress.json"), "MBOS_LITELLM_FILE": str(tmp / "litellm.json")})
        assert cp.returncode == 0, cp.stdout[-3000:] + cp.stderr[-14000:]
        r = json.loads(line(cp, "RESULT"))
        r["stderr_tracebacks"] = cp.stderr.count("Traceback")
        yield r
    finally:
        server.cleanup()


def test_yes_on_a_held_request_acts_without_a_wake(result):
    assert result["first"]["tv"] == "AWAITING_APPROVAL" and result["tv_held"] == "HELD"
    assert result["tv_final"] == "ACTED", result
    assert result["tv_executed"] == 1


def test_hold_wake_now_from_the_ui_process_then_yes_acts(result):
    assert result["lead_after_inputs"] == "AWAITING_APPROVAL", result
    assert result["lead_held"] == "HELD" and result["lead_woken"] == "AWAITING_APPROVAL"
    assert result["lead_final"] == "ACTED", result
    assert result["lead_executed"] == 1


def test_one_input_seen_by_both_watchers_queues_one_recheck(result):
    first = result["queued"][0]
    assert len(first) == 2 and len(set(first)) == 1, first  # ResearchWatcher and HumanInputWatcher both fired: coalesced into one workflow
    assert len(result["rechecks"]) <= 3, result["rechecks"]


def test_the_same_provenance_written_twice_at_once_is_stored_once_without_error(result):
    assert result["provenance_race"] is True, result["provenance_race"]


def test_no_error_records_no_tracebacks_and_the_chain_verifies(result):
    assert not result["error_workflows"], result["error_workflows"]
    assert not result["error_logs"], result["error_logs"]
    assert result["stderr_tracebacks"] == 0
    assert result["chain"]["ok"], result["chain"]
