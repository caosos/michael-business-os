"""A5. Killing the process mid-ACT, then restarting, resumes at the step with no duplicate
effector call (idempotency key). The kill is a real os._exit in a separate process."""

import json

import pytest

from mbos.db.engine import engine_for
from tests.helpers.common import create_database, fixture_variant, receipts_for, scalar
from tests.helpers.proc import line, run_runner

pytestmark = pytest.mark.acceptance


@pytest.mark.parametrize("point", ["after_effector", "before_effector"])
def test_kill_mid_act_then_restart_executes_exactly_once(pg, tmp_path, point):
    urls = (create_database(pg, "a5app"), create_database(pg, "a5sys"))
    fixture = fixture_variant(tmp_path, "a5", ["FIX-TRAILER-1"])

    crashed = run_runner(urls, "crash_mid_act", str(fixture), point)
    assert crashed.returncode == 137, crashed.stdout + crashed.stderr[-2000:]
    assert f"CRASH {point.replace('_', ' ')}" in crashed.stdout
    item_id = line(crashed, "ITEM")

    engine = engine_for(urls[0])
    expected_calls_before = 1 if point == "after_effector" else 0
    assert scalar(engine, "SELECT count(*) FROM mbos.effector_calls") == expected_calls_before
    assert scalar(engine, "SELECT state FROM mbos.items WHERE item_id = :i", i=item_id) == "ACTING"

    resumed = run_runner(urls, "resume", item_id, "result")
    assert resumed.returncode == 0, resumed.stdout + resumed.stderr[-2000:]
    assert json.loads(line(resumed, "RESULT"))["status"] == "acted"

    assert scalar(engine, "SELECT count(*) FROM mbos.effector_calls") == 1, "exactly one effector call"
    assert scalar(engine, "SELECT state FROM mbos.items WHERE item_id = :i", i=item_id) == "ACTED"
    assert len(receipts_for(engine, item_id=item_id, type="ACTION_EXECUTING")) == 1, "begin_act not re-applied"
    executed = receipts_for(engine, item_id=item_id, type="ACTION_EXECUTED")
    assert len(executed) == 1
    if point == "after_effector":
        assert "idempotent replay" in executed[0]["details"]["guard_reason"]
    assert executed[0]["effector_response"]["dry_run"] is True
    with engine.connect() as c:
        from mbos.ledger import verify_chain
        assert verify_chain(c)["ok"]
    engine.dispose()
