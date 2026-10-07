"""Out-of-process scenarios against the REAL spine for A5/A6. Each mode ends in os._exit (no cleanup); the
next process must recover from durable state alone.  Env: MBOS_QA_APP_URL, MBOS_QA_SYS_URL (+ backend selection
via MBOS_QA_STATE_BACKEND / MBOS_QA_GATEWAY_MODE / MBOS_POLICY_PATH, set by the parent).

    python -m mbos_qa._spine_child crash   <listing> <before_effector|after_effector>
    python -m mbos_qa._spine_child hold    <listing>
    python -m mbos_qa._spine_child resume  <item_id> <wait_acted|hold_check>
"""
import json
import os
import pathlib
import sys
import time
import uuid

from mbos_qa import impl_spine  # sets MBOS_CONTRACTS_DIR before mbos is imported


def say(*a):
    print(*a, flush=True)


def _init(crash_at=None):
    return impl_spine.boot_runtime(os.environ["MBOS_QA_APP_URL"], os.environ["MBOS_QA_SYS_URL"], crash_at=crash_at)


def _qa():
    q = impl_spine.SpineQA.__new__(impl_spine.SpineQA)  # read helpers only; the runtime is already booted here
    from mbos.runtime import runtime

    q.rt, q.engine, q.workdir = runtime(), runtime().engine, pathlib.Path(os.environ.get("TMPDIR", "/tmp"))
    return q


def _discover(rt, listing):
    from dbos import DBOS, SetWorkflowID

    from mbos import workflows
    from mbos.reference.fixture_adapter import FixtureSourceAdapter

    tag = uuid.uuid4().hex[:8]
    rt.components.adapters["qa"] = FixtureSourceAdapter(
        impl_spine.fixture_file(tag, [listing], pathlib.Path(os.environ.get("TMPDIR", "/tmp"))), name="qa")
    with SetWorkflowID(f"discover:qa-{tag}"):
        res = DBOS.start_workflow(workflows.discover, "qa").get_result()
    item_id = next(r["item_id"] for r in res if r["created"])
    say("ITEM", item_id)
    return item_id


def _wait(q, item_id, states, timeout=60):
    deadline = time.monotonic() + timeout
    while q.item(item_id)["state"] not in states and time.monotonic() < deadline:
        time.sleep(0.1)
    return q.item(item_id)["state"]


def crash(listing, point):
    rt = _init(crash_at=point)
    from mbos import workflows

    q = _qa()
    item_id = _discover(rt, listing)
    _wait(q, item_id, {"AWAITING_APPROVAL"}, 30)
    areq = q.areqs(item_id=item_id, status="pending_approval")[-1]
    say("AREQ", areq["action_request_id"])
    workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"], auth_context=impl_spine.STEP_UP)
    time.sleep(60)
    say("ERROR did not crash")
    os._exit(3)


def hold(listing):
    rt = _init()
    from mbos import workflows

    q = _qa()
    item_id = _discover(rt, listing)
    _wait(q, item_id, {"AWAITING_APPROVAL"}, 30)
    areq = q.areqs(item_id=item_id, status="pending_approval")[-1]
    say("AREQ", areq["action_request_id"])
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["michael_ping"],
                                    "renotify_after": "PT1H", "escalate_after": "P30D"})
    say("STATE", _wait(q, item_id, {"HELD"}, 30))
    os._exit(0)


def resume(item_id, action):
    _init()  # DBOS.launch() recovers every PENDING workflow from the system database
    q = _qa()
    if action == "wait_acted":
        _wait(q, item_id, {"ACTED", "FAILED"}, 90)
    elif action == "hold_check":
        time.sleep(2.0)  # give the recovered workflow time to prove it does NOT act on its own
        say("STATE_AFTER_RESTART", q.item(item_id)["state"])
        from mbos import workflows

        workflows.ping(item_id)
        _wait(q, item_id, {"AWAITING_APPROVAL"}, 30)
    say("STATE", q.item(item_id)["state"])
    say("INVOCATIONS", json.dumps(impl_spine.INVOCATIONS))
    os._exit(0)


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    {"crash": crash, "hold": hold, "resume": resume}[mode](*args)
