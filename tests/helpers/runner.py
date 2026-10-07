"""Out-of-process scenarios for crash/restart tests (A5, A6). Each mode ends in os._exit, i.e. a hard
process death with no cleanup — the next process must recover from durable state alone.

    python -m tests.helpers.runner <mode> <args...>     (env: MBOS_DATABASE_URL, MBOS_SYSTEM_DATABASE_URL)
"""

from __future__ import annotations

import json
import os
import sys
import time

from dbos import DBOS, SetWorkflowID

from mbos.config import Settings
from mbos.reference.fixture_adapter import FixtureSourceAdapter
from mbos.runtime import Components, init_runtime, runtime
from tests.helpers.common import pending_request, wait_state


def say(*parts) -> None:
    print(*parts, flush=True)


def _settings() -> Settings:
    return Settings(database_url=os.environ["MBOS_DATABASE_URL"],
                    system_database_url=os.environ["MBOS_SYSTEM_DATABASE_URL"], approval_poll_seconds=0.3)


def _discover_one(fixture: str) -> str:
    from mbos import workflows

    runtime().components.adapters["fx"] = FixtureSourceAdapter(fixture, name="fx")
    with SetWorkflowID("discover:fx"):
        results = DBOS.start_workflow(workflows.discover, "fx").get_result()
    item_id = next(r["item_id"] for r in results if r["created"])
    say("ITEM", item_id)
    wait_state(runtime().engine, item_id, "AWAITING_APPROVAL")
    return item_id


def crash_mid_act(fixture: str, point: str) -> None:
    """Approve YES and die inside the gateway step — before or after the effector committed."""
    import mbos.reference.governance as g

    original = g.DryRunEffector.execute

    def crashing(self, engine, areq):
        if point == "before_effector":
            say("CRASH before effector")
            os._exit(137)
        resp = original(self, engine, areq)  # effector call committed …
        say("CRASH after effector")
        os._exit(137)  # … but the process dies before DBOS checkpoints the step
        return resp

    g.DryRunEffector.execute = crashing
    init_runtime(_settings(), Components())
    from mbos import workflows

    item_id = _discover_one(fixture)
    areq = pending_request(runtime().engine, item_id)
    workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"])
    time.sleep(60)
    say("ERROR: did not crash")
    os._exit(3)


def hold_then_die(fixture: str) -> None:
    init_runtime(_settings(), Components())
    from mbos import workflows

    item_id = _discover_one(fixture)
    areq = pending_request(runtime().engine, item_id)
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["michael_ping"],
                                    "renotify_after": "PT1H", "escalate_after": "P30D"})
    wait_state(runtime().engine, item_id, "HELD")
    say("HELD")
    os._exit(0)


def resume(item_id: str, action: str) -> None:
    """Restart: launching DBOS recovers every PENDING workflow from the system database."""
    init_runtime(_settings(), Components())
    from mbos import workflows
    from tests.helpers.common import item_state

    engine = runtime().engine
    if action == "result":
        say("RESULT", json.dumps(DBOS.retrieve_workflow(f"item:{item_id}").get_result()))
    elif action == "ping":
        time.sleep(1.5)  # give the recovered workflow time to prove it does NOT act on its own
        say("STATE_AFTER_RESTART", item_state(engine, item_id))
        workflows.ping(item_id)
        wait_state(engine, item_id, "AWAITING_APPROVAL")
        say("STATE_AFTER_PING", item_state(engine, item_id))
    os._exit(0)


if __name__ == "__main__":
    mode, *args = sys.argv[1:]
    {"crash_mid_act": crash_mid_act, "hold_then_die": hold_then_die, "resume": resume}[mode](*args)
