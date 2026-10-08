"""G-18: the real runtime (01 mbos @ 71d5cdb) with SPLIT logins, in a child process (own DBOS singleton): the workflow login is refused a forged
decision, the owner login's decision wakes the parked `_approval_gate`, and the gateway executes the dry-run send exactly once."""
import json
import os
import pathlib
import subprocess
import sys

QA = pathlib.Path(__file__).resolve().parents[2]


def test_workflow_gate_proceeds_after_the_owner_decides_and_not_after_a_forgery():
    env = dict(os.environ, PYTHONPATH=str(QA), MBOS_QA_STATE_BACKEND="lane_d", MBOS_QA_GATEWAY_MODE="lane_e")
    p = subprocess.run([sys.executable, "-W", "ignore", "-m", "mbos_qa._split_e2e"], cwd=QA, env=env, capture_output=True, text=True, timeout=400)
    line = [l for l in p.stdout.splitlines() if l.startswith("RESULT ")]
    assert line, p.stdout[-2000:] + p.stderr[-2000:]
    r = json.loads(line[-1][7:])
    assert r["engine_user"] == "mbos_dbos"
    assert r["pending_state"] == "AWAITING_APPROVAL"
    assert "InsufficientPrivilege" in r["workflow_decide_refused"] and r["approvals_after_forgery"] == 0 and r["state_after_forgery"] == "AWAITING_APPROVAL"
    assert r["decision_ok"] and r["approval_written_by_owner"] == 1
    assert r["areq_status"] == "executed" and r["final_item_state"] == "ACTED" and r["effector_executions"] == 1 and r["chain_ok"]
