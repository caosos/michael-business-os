"""A5 (real spine + DBOS): kill the process mid-ACT with os._exit(137), restart, and the effector runs exactly once.
Crash and restart are separate OS processes over the same databases; recovery is DBOS.launch()."""
import json

import pytest

from mbos_qa import impl_spine


def _line(cp, prefix):
    for ln in cp.stdout.splitlines():
        if ln.startswith(prefix):
            return ln[len(prefix):].strip()
    raise AssertionError(f"no {prefix!r}\nSTDOUT:\n{cp.stdout[-2000:]}\nSTDERR:\n{cp.stderr[-3000:]}")


@pytest.mark.parametrize("point,expected_restart_invocations", [("before_effector", 1), ("after_effector", 0)])
def test_kill_mid_act_then_restart_runs_effector_exactly_once(qa, point, expected_restart_invocations):
    urls = (impl_spine.new_database("qa_crash_app"), impl_spine.new_database("qa_crash_sys"))
    first = impl_spine.child("crash", "FIX-TRAILER-1", point, urls=urls)
    assert first.returncode == 137, first.stderr[-2000:]
    item_id = _line(first, "ITEM")
    areq_id = _line(first, "AREQ")

    second = impl_spine.child("resume", item_id, "wait_acted", urls=urls)
    assert second.returncode == 0, second.stderr[-2000:]
    assert _line(second, "STATE") == "ACTED"
    inv = json.loads(_line(second, "INVOCATIONS"))
    assert sum(inv.values()) == expected_restart_invocations, inv

    from mbos.db.engine import engine_for

    eng = engine_for(urls[0])
    try:
        assert len(qa.effector_rows(eng, areq_id)) == 1, "effector recorded more (or less) than once"
        executed = [r for r in qa.receipts(eng, action_request_id=areq_id) if r["type"] == "ACTION_EXECUTED"]
        assert len(executed) == 1
        assert qa.verify_chain(eng)["ok"]
    finally:
        eng.dispose()


def test_replayed_gateway_call_does_not_reinvoke_effector(qa, led):
    out = led.seed()
    areq = qa.areq(out["action_request_id"], led.engine)
    from mbos_qa.impl_spine import INVOCATIONS

    before = INVOCATIONS.get(areq["idempotency_key"], 0)
    again = led.gateway(areq["action_request_id"], out["approval"]["approval_id"])
    assert INVOCATIONS.get(areq["idempotency_key"], 0) == before, "the effector ran a second time"
    assert len(qa.effector_rows(led.engine, areq["action_request_id"])) == 1
    assert not again["ok"] or again["reason"].startswith("idempotent replay"), again["reason"]
