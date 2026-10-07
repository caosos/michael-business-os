"""A-13: Agent 06's REAL comms planner (F-05) and dry-run comms effector (F-06) wired into the spine,
behind the reference gateway, through the real DBOS workflow. 06's code is extracted read-only from its
pushed branch with `git archive` (never merged). Fixed clocks keep the send-window check deterministic."""

from __future__ import annotations

import io
import subprocess
import sys
import tarfile
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

from mbos import workflows
from mbos.audit import dry_run_exceptions
from mbos.hashing import sha256_of
from mbos.reference.governance import DryRunEffector, ReferenceGateway
from tests.helpers.common import ROOT, STEP_UP, pending_request, receipts_for, wait_state

REF = "origin/research/agent-06-communications"
NOON = datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc)   # Wed 12:00 CDT: inside the window
LATE = datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc)   # Wed 21:30 CDT: outside the window


@pytest.fixture(scope="module")
def lane_f(tmp_path_factory):
    dest = tmp_path_factory.mktemp("lane-f")
    tar = subprocess.run(["git", "archive", REF, "comms_spec", "operator_ui/mbos_canonical.py", "operator_ui/__init__.py"],
                         cwd=ROOT, capture_output=True)
    if tar.returncode:
        pytest.skip(f"lane F code not available at {REF}: {tar.stderr.decode()[:200]}")
    tarfile.open(fileobj=io.BytesIO(tar.stdout)).extractall(dest, filter="data")
    sys.path.insert(0, str(dest))
    from comms_spec.effector import CommsDryRunEffector
    from comms_spec.planner import CommsActionPlanner
    yield CommsActionPlanner, CommsDryRunEffector
    sys.path.remove(str(dest))


@pytest.fixture()
def wire(rt, lane_f, monkeypatch):
    from mbos.runtime import components

    Planner, Effector = lane_f
    comps = components()

    def _wire(clock):
        monkeypatch.setattr(comps, "planner", Planner())
        monkeypatch.setattr(comps, "gateway", ReferenceGateway(Effector(clock=lambda: clock, fallback=DryRunEffector()),
                                                               comps.kill_switch))
    return _wire


def _approve(rt, item_id):
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    assert "comms" in areq["payload"], "A-13: the planner's comms block is part of the frozen payload"
    assert sha256_of(areq["payload"]) == areq["payload_hash"]
    workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"], auth_context=STEP_UP)
    return areq


def test_comms_send_inside_window_is_receipted_with_comms_details(rt, run_discovery, wire):
    wire(NOON)
    item_id = run_discovery("FIX-LEAD-SMARTHOME-1")["FIX-LEAD-SMARTHOME-1"]
    areq = _approve(rt, item_id)
    wait_state(rt.engine, item_id, "ACTED")
    ex = receipts_for(rt.engine, areq=areq["action_request_id"], type="ACTION_EXECUTED")[0]
    assert ex["details"]["kind"] == "comms" and ex["details"]["dry_run"] is True
    assert ex["effector_response"]["dry_run"] is True
    with rt.engine.connect() as c:
        assert dry_run_exceptions(c)["ok"]


def test_effector_block_becomes_action_failed(rt, run_discovery, wire):
    wire(LATE)
    item_id = run_discovery("FIX-LEAD-SMARTHOME-1")["FIX-LEAD-SMARTHOME-1"]
    areq = _approve(rt, item_id)
    wait_state(rt.engine, item_id, "FAILED")
    assert not receipts_for(rt.engine, areq=areq["action_request_id"], type="ACTION_EXECUTED")
    failed = receipts_for(rt.engine, areq=areq["action_request_id"], type="ACTION_FAILED")
    assert len(failed) == 1 and failed[0]["effect"] == "none" and "effector blocked" in failed[0]["intent"]
    with rt.engine.connect() as c:
        st = c.execute(sa.text("SELECT status FROM mbos.action_requests WHERE action_request_id = :a"),
                       {"a": areq["action_request_id"]}).scalar_one()
    assert st == "failed"
