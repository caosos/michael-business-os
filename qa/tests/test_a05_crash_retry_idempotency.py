"""A5 — killing the process mid-ACT, then restarting, resumes at the step with no duplicate effector call.

The crash is real: a child process is hard-killed with os._exit(137) (no cleanup, no atexit) at the fault
point; the parent then reopens the same durable files as a fresh process would."""
import os
import subprocess
import sys
import textwrap
import threading

import pytest

from mbos_qa.harness import build

from .conftest import ROOT, approve, effector_attempts, pending

CHILD = textwrap.dedent("""
    import os, sys
    from mbos_qa.harness import build
    from tests.conftest import pending, approve
    h = build(sys.argv[1])
    item_id, areq = pending(h)
    approve(h, areq)
    h.gateway.faults[sys.argv[2]] = lambda: os._exit(137)
    h.workflow.act(item_id)
    os._exit(0)
""")


def _crash(workdir, point):
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    p = subprocess.run([sys.executable, "-c", CHILD, str(workdir), point], cwd=ROOT, env=env, capture_output=True, text=True)
    assert p.returncode == 137, p.stderr


@pytest.mark.parametrize("point,attempts_at_crash", [
    ("after_executing_before_effector", 0),
    ("after_effector_before_executed", 1),
])
def test_kill_mid_act_then_restart_calls_effector_exactly_once(tmp_path, point, attempts_at_crash):
    wd = tmp_path / "run"
    _crash(wd, point)

    h = build(wd, seed=None)  # fresh process over the same durable state
    (areq,) = h.store.action_requests()
    assert areq["status"] == "executing"
    assert len(h.store.receipts(type="ACTION_EXECUTING")) == 1
    assert h.store.receipts(type="ACTION_EXECUTED") == []
    assert effector_attempts(h) == attempts_at_crash

    h.workflow.act(areq["item_id"])  # resume
    assert effector_attempts(h) == 1, "duplicate (or missing) effector call after restart"
    assert len(h.store.receipts(type="ACTION_EXECUTED")) == 1
    assert h.store.get("action-request", areq["action_request_id"])["status"] == "executed"
    assert h.store.get("item", areq["item_id"])["state"] == "ACTED"
    assert h.store.verify_chain().ok

    h.workflow.act(areq["item_id"])  # a second restart / retry is a no-op
    h.gateway.recover()
    assert effector_attempts(h) == 1 and len(h.store.receipts(type="ACTION_EXECUTED")) == 1


def test_repeat_execute_is_a_noop(h):
    item_id, areq = pending(h)
    appr = approve(h, areq)
    first = h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    again = h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    assert (first.status, first.effector_calls) == ("executed", 1)
    assert (again.status, again.effector_calls) == ("already_executed", 0)
    assert again.receipt["receipt_id"] == first.receipt["receipt_id"]
    assert effector_attempts(h) == 1


def test_concurrent_execute_calls_effector_once(h):
    item_id, areq = pending(h)
    appr = approve(h, areq)
    results, errors = [], []
    barrier = threading.Barrier(8)

    def go():
        barrier.wait()
        try:
            results.append(h.gateway.execute(areq["action_request_id"], appr["approval_id"]).status)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=go) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert effector_attempts(h) == 1
    assert results.count("executed") == 1
    assert set(results) <= {"executed", "in_flight", "already_executed"}
    assert len(h.store.receipts(type="ACTION_EXECUTED")) == 1


def test_frozen_at_restart_leaves_inflight_unretried(tmp_path):
    wd = tmp_path / "run"
    _crash(wd, "after_executing_before_effector")
    h = build(wd, seed=None)
    h.kill.set(level="L3", target=None, frozen=True)
    res = h.gateway.recover()
    assert [r.status for r in res] == ["left_in_flight_by_freeze"]
    assert effector_attempts(h) == 0
