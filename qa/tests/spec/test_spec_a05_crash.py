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


def _crash_and_restart(qa, point):
    urls = impl_spine.new_runtime_databases("qa_crash")
    first = impl_spine.child("crash", "FIX-TRAILER-1", point, urls=urls)
    assert first.returncode == 137, first.stderr[-2000:]
    item_id, areq_id = _line(first, "ITEM"), _line(first, "AREQ")
    executed_before_crash = 1 if "CRASH after_effector" in first.stdout else 0
    second = impl_spine.child("resume", item_id, "wait_acted", urls=urls)
    assert second.returncode == 0, second.stderr[-2000:]
    from mbos.db.engine import engine_for

    return dict(urls=urls, eng=engine_for(urls[0]), item_id=item_id, areq_id=areq_id,
                executed_before_crash=executed_before_crash, second=second,
                restart_invocations=sum(json.loads(_line(second, "INVOCATIONS")).values()))


@pytest.mark.parametrize("point", ["before_effector", "after_effector"])
def test_kill_mid_act_never_duplicates_the_effector(qa, point):
    """THE invariant: a hard kill mid-ACT and a restart never produce a second effector execution or receipt."""
    r = _crash_and_restart(qa, point)
    try:
        assert r["executed_before_crash"] + r["restart_invocations"] <= 1, "duplicate effector execution after restart"
        assert len([x for x in qa.receipts(r["eng"], action_request_id=r["areq_id"]) if x["type"] == "ACTION_EXECUTED"]) <= 1
        assert len(qa.effector_rows(r["eng"], r["areq_id"])) == 1, "exactly one effector claim row"
        assert qa.verify_chain(r["eng"])["ok"]
    finally:
        r["eng"].dispose()


@pytest.mark.parametrize("point", ["before_effector", "after_effector"])
def test_kill_mid_act_settles_truthfully_per_R22(qa, point):
    """Ruling R22 (Agent 01): A5 means never duplicate the effect, and settle TRUTHFULLY.
      * if the send happened before the crash (provider/ledger can prove it): the request settles `executed` and the
        item reaches ACTED, with no second effector call;
      * if no send happened: either (a) the restart completes it, exactly one effector call, `executed`/ACTED, or
        (b) it settles `failed` with a RECONCILED receipt and zero effector calls (Michael re-approves).
    Never two sends, never a settlement that contradicts what happened."""
    r = _crash_and_restart(qa, point)
    try:
        calls = r["executed_before_crash"] + r["restart_invocations"]
        areq = qa.areq(r["areq_id"], r["eng"])
        item_state = qa.item(r["item_id"], r["eng"])["state"]
        receipts = qa.receipts(r["eng"], action_request_id=r["areq_id"])
        executed = [x for x in receipts if x["type"] == "ACTION_EXECUTED"]
        assert calls <= 1, f"{calls} effector calls: a duplicate send"
        assert len(executed) <= 1 and len(qa.effector_rows(r["eng"], r["areq_id"])) == 1
        if r["executed_before_crash"]:
            assert areq["status"] == "executed" and item_state == "ACTED" and len(executed) == 1, \
                f"the send happened but the request settled {areq['status']!r} / item {item_state!r} (untruthful)"
        elif areq["status"] == "executed":
            assert item_state == "ACTED" and calls == 1 and len(executed) == 1
        else:
            assert areq["status"] == "failed" and calls == 0 and not executed
            assert any("RECONCILED" in (x.get("intent", "") + json.dumps(x.get("details") or {})) for x in receipts), \
                "failed after a crash without a RECONCILED receipt"
        assert qa.verify_chain(r["eng"])["ok"]
    finally:
        r["eng"].dispose()


def test_replayed_gateway_call_does_not_reinvoke_effector(qa, led):
    out = led.seed()
    areq = qa.areq(out["action_request_id"], led.engine)
    from mbos_qa.impl_spine import INVOCATIONS

    before = INVOCATIONS.get(areq["idempotency_key"], 0)
    again = led.gateway(areq["action_request_id"], out["approval"]["approval_id"])
    assert INVOCATIONS.get(areq["idempotency_key"], 0) == before, "the effector ran a second time"
    assert len(qa.effector_rows(led.engine, areq["action_request_id"])) == 1
    assert not again["ok"] or again["reason"].startswith("idempotent replay"), again["reason"]
