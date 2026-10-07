"""Out-of-process scenarios against the REAL spine for A5/A6. Each mode ends in os._exit (no cleanup); the
next process must recover from durable state alone.  Env: MBOS_QA_APP_URL, MBOS_QA_SYS_URL.

    python -m mbos_qa._spine_child crash   <listing> <before_effector|after_effector>
    python -m mbos_qa._spine_child hold    <listing>
    python -m mbos_qa._spine_child resume  <item_id> <wait_acted|hold_check>
"""
import json
import os
import sys
import time

from mbos_qa import impl_spine  # sets MBOS_CONTRACTS_DIR before mbos is imported


def say(*a):
    print(*a, flush=True)


def _init(wrap_crash_at=None):
    import mbos.reference.governance as g
    from mbos.config import Settings
    from mbos.runtime import Components, init_runtime

    impl_spine._wrap_effector()  # count invocations in THIS process
    if wrap_crash_at:
        inner = g.DryRunEffector.execute

        def crashing(self, engine, areq):
            if wrap_crash_at == "before_effector":
                say("CRASH before_effector")
                os._exit(137)
            resp = inner(self, engine, areq)  # the effector call is durably recorded …
            say("CRASH after_effector")
            os._exit(137)  # … but the process dies before DBOS checkpoints the gateway step
            return resp

        g.DryRunEffector.execute = crashing
    s = Settings(database_url=os.environ["MBOS_QA_APP_URL"], system_database_url=os.environ["MBOS_QA_SYS_URL"],
                 approval_poll_seconds=0.3)
    return init_runtime(s, Components())


def _discover(rt, listing):
    import pathlib
    import uuid

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


def _pending(rt, item_id):
    import sqlalchemy as sa

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with rt.engine.connect() as c:
            row = c.execute(sa.text("SELECT body FROM mbos.action_requests WHERE item_id = :i AND status = "
                                    "'pending_approval'"), {"i": item_id}).one_or_none()
        if row:
            return row.body
        time.sleep(0.1)
    raise SystemExit("no pending request")


def _state(rt, item_id):
    import sqlalchemy as sa

    with rt.engine.connect() as c:
        return c.execute(sa.text("SELECT state FROM mbos.items WHERE item_id = :i"), {"i": item_id}).scalar_one()


def crash(listing, point):
    rt = _init(wrap_crash_at=point)
    from mbos import workflows

    item_id = _discover(rt, listing)
    areq = _pending(rt, item_id)
    say("AREQ", areq["action_request_id"])
    workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"], auth_context=impl_spine.STEP_UP)
    time.sleep(60)
    say("ERROR did not crash")
    os._exit(3)


def hold(listing):
    rt = _init()
    from mbos import workflows

    item_id = _discover(rt, listing)
    areq = _pending(rt, item_id)
    say("AREQ", areq["action_request_id"])
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["michael_ping"],
                                    "renotify_after": "PT1H", "escalate_after": "P30D"})
    deadline = time.monotonic() + 30
    while _state(rt, item_id) != "HELD" and time.monotonic() < deadline:
        time.sleep(0.1)
    say("STATE", _state(rt, item_id))
    os._exit(0)


def resume(item_id, action):
    rt = _init()  # DBOS.launch() recovers every PENDING workflow from the system database
    if action == "wait_acted":
        deadline = time.monotonic() + 60
        while _state(rt, item_id) not in ("ACTED", "FAILED") and time.monotonic() < deadline:
            time.sleep(0.1)
    elif action == "hold_check":
        time.sleep(2.0)  # give the recovered workflow time to prove it does NOT act on its own
        say("STATE_AFTER_RESTART", _state(rt, item_id))
        from mbos import workflows

        workflows.ping(item_id)
        deadline = time.monotonic() + 30
        while _state(rt, item_id) != "AWAITING_APPROVAL" and time.monotonic() < deadline:
            time.sleep(0.1)
    say("STATE", _state(rt, item_id))
    say("INVOCATIONS", json.dumps(impl_spine.INVOCATIONS))
    os._exit(0)


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    {"crash": crash, "hold": hold, "resume": resume}[mode](*args)
