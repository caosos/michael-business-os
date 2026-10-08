"""A6. YES executes the frozen payload. NO archives with a reason. MODIFY creates a new areq with
derived_from. HOLD survives a restart, wakes on its condition, re-notifies after the TTL and never
auto-executes."""

import time
from datetime import timedelta

import pytest
import sqlalchemy as sa

from mbos import spine, workflows
from mbos.clock import iso, utcnow
from mbos.db.engine import engine_for
from mbos.hashing import sha256_of
from tests.helpers.common import (
    STEP_UP,
    create_database, fixture_variant, pending_request, receipts_for, scalar, wait_state,
)
from tests.helpers.proc import line, run_runner

pytestmark = pytest.mark.acceptance


def _effector_calls(engine, areq_id):
    return scalar(engine, "SELECT count(*) FROM mbos.effector_calls WHERE action_request_id = :a", a=areq_id)


def test_yes_executes_the_frozen_payload(rt, run_discovery):
    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"], auth_context=STEP_UP)
    wait_state(rt.engine, item_id, "ACTED")
    with rt.engine.connect() as c:
        call = c.execute(sa.text("SELECT request, response FROM mbos.effector_calls WHERE action_request_id = :a"),
                         {"a": areq["action_request_id"]}).one()
    assert call.request == areq["payload"] and sha256_of(call.request) == areq["payload_hash"]
    executed = receipts_for(rt.engine, areq=areq["action_request_id"], type="ACTION_EXECUTED")[0]
    assert executed["payload_hash"] == areq["payload_hash"] and executed["effector_response"]["dry_run"] is True
    assert all(executed["details"]["guard_checks"][k] for k in executed["details"]["guard_checks"])


def test_no_archives_with_reason(rt, run_discovery):
    item_id = run_discovery("FIX-LEAD-SMARTHOME-1")["FIX-LEAD-SMARTHOME-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    with pytest.raises(Exception, match="reason"):  # contract: NO requires a reason
        workflows.record_decision(areq["action_request_id"], "NO", areq["payload_hash"])
    workflows.record_decision(areq["action_request_id"], "NO", areq["payload_hash"], reason="too far this week")
    wait_state(rt.engine, item_id, "ARCHIVED")
    assert _effector_calls(rt.engine, areq["action_request_id"]) == 0
    decided = receipts_for(rt.engine, areq=areq["action_request_id"], type="APPROVAL_DECIDED")[0]
    assert "too far this week" in decided["intent"]
    states = [r["after_state"]["state"] for r in receipts_for(rt.engine, item_id=item_id, type="ITEM_STATE_CHANGED")]
    assert states[-2:] == ["REJECTED", "ARCHIVED"]


def test_modify_creates_derived_request_and_executes_only_the_new_payload(rt, run_discovery):
    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    old = pending_request(rt.engine, item_id)
    out = workflows.record_decision(old["action_request_id"], "MODIFY", old["payload_hash"],
                                    payload_changes={"summary": "Offer $725 cash, pickup Saturday (DRY-RUN draft)"})
    new_id = out["new_action_request_id"]
    for _ in range(50):
        if pending_request(rt.engine, item_id)["action_request_id"] == new_id:
            break
        time.sleep(0.1)
    new = pending_request(rt.engine, item_id)
    assert new["action_request_id"] == new_id and new["derived_from"] == old["action_request_id"]
    assert new["payload_hash"] != old["payload_hash"] and new["payload"]["summary"].startswith("Offer $725")
    assert scalar(rt.engine, "SELECT status FROM mbos.action_requests WHERE action_request_id = :a",
                  a=old["action_request_id"]) == "rejected"
    with pytest.raises(spine.DecisionRefused):  # the superseded request can no longer be approved
        workflows.record_decision(old["action_request_id"], "YES", old["payload_hash"], auth_context=STEP_UP)
    workflows.record_decision(new_id, "YES", new["payload_hash"], auth_context=STEP_UP)
    wait_state(rt.engine, item_id, "ACTED")
    assert _effector_calls(rt.engine, old["action_request_id"]) == 0
    with rt.engine.connect() as c:
        req = c.execute(sa.text("SELECT request FROM mbos.effector_calls WHERE action_request_id = :a"), {"a": new_id}).scalar_one()
    assert req["summary"].startswith("Offer $725")


def test_hold_renotifies_wakes_on_time_and_never_auto_executes(rt, run_discovery):
    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": iso(utcnow() + timedelta(seconds=4)), "wake_on": ["time"],
                                    "renotify_after": "PT1S", "escalate_after": "P1D"})
    wait_state(rt.engine, item_id, "HELD")
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL", timeout=15)  # woke on time …
    requested = receipts_for(rt.engine, areq=areq["action_request_id"], type="APPROVAL_REQUESTED")
    intents = [r["intent"] for r in requested]
    assert any(i.startswith("re-notify") for i in intents), intents
    assert any(i.startswith("re-presented after HOLD") for i in intents), intents
    assert scalar(rt.engine, "SELECT status FROM mbos.action_requests WHERE action_request_id = :a",
                  a=areq["action_request_id"]) == "pending_approval"
    time.sleep(1.0)
    assert _effector_calls(rt.engine, areq["action_request_id"]) == 0, "… and was re-presented, not executed"
    assert not receipts_for(rt.engine, areq=areq["action_request_id"], type="ACTION_EXECUTING")
    workflows.record_decision(areq["action_request_id"], "NO", areq["payload_hash"], reason="test cleanup")
    wait_state(rt.engine, item_id, "ARCHIVED")


def test_hold_survives_a_hard_restart_and_wakes_on_ping(pg, tmp_path):
    urls = (create_database(pg, "a6app"), create_database(pg, "a6sys"))
    fixture = fixture_variant(tmp_path, "a6", ["FIX-TRAILER-1"])
    first = run_runner(urls, "hold_then_die", str(fixture))
    assert first.returncode == 0 and "HELD" in first.stdout, first.stdout + first.stderr[-2000:]
    item_id = line(first, "ITEM")

    second = run_runner(urls, "resume", item_id, "ping")
    assert second.returncode == 0, second.stdout + second.stderr[-2000:]
    assert line(second, "STATE_AFTER_RESTART") == "HELD"
    assert line(second, "STATE_AFTER_PING") == "AWAITING_APPROVAL"
    engine = engine_for(urls[0])
    assert scalar(engine, "SELECT count(*) FROM mbos.effector_calls") == 0
    assert any("michael_ping" in r["intent"] for r in receipts_for(engine, item_id=item_id, type="APPROVAL_REQUESTED"))
    engine.dispose()


def test_decision_on_a_payload_michael_did_not_see_is_refused(rt, run_discovery):
    item_id = run_discovery("FIX-LEAD-SMARTHOME-1")["FIX-LEAD-SMARTHOME-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    with pytest.raises(spine.DecisionRefused, match="payload_hash_seen"):
        workflows.record_decision(areq["action_request_id"], "YES", "sha256:" + "f" * 64, auth_context=STEP_UP)
    with pytest.raises(sa.exc.DBAPIError, match="approval void"):  # the DB refuses it independently
        with rt.engine.begin() as c:
            c.execute(sa.text("INSERT INTO mbos.approvals (body) VALUES (CAST(:b AS jsonb))"), {"b": (
                '{"approval_id":"appr_01JA0000000000000000000009","action_request_id":"%s","decision":"YES",'
                '"payload_hash_seen":"sha256:%s"}' % (areq["action_request_id"], "f" * 64))})
    workflows.record_decision(areq["action_request_id"], "NO", areq["payload_hash"], reason="cleanup")
    wait_state(rt.engine, item_id, "ARCHIVED")


def test_hold_ping_then_yes_reaches_acted_with_receipts(rt, run_discovery):
    """F-116: a HOLD woken by `mbos ping` can still be approved, and the YES runs."""
    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["michael_ping"],
                                    "renotify_after": "PT1H", "escalate_after": "P30D"})
    wait_state(rt.engine, item_id, "HELD")
    workflows.ping(item_id)
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    # a second gate on the same request (duplicate worker / orphan recovery) replays the old HOLD from seq 0
    from dbos import DBOS
    twin = DBOS.start_workflow(workflows.followup_lifecycle, item_id, areq["action_request_id"])
    time.sleep(2.0)
    assert scalar(rt.engine, "SELECT state FROM mbos.items WHERE item_id = :i", i=item_id) == "AWAITING_APPROVAL", "stale HOLD re-applied"
    workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"], auth_context=STEP_UP)
    wait_state(rt.engine, item_id, "ACTED")
    twin.get_result()
    assert _effector_calls(rt.engine, areq["action_request_id"]) == 1
    assert receipts_for(rt.engine, areq=areq["action_request_id"], type="ACTION_EXECUTED")


def test_yes_straight_from_hold_reaches_acted(rt, run_discovery):
    """F-116: even without a ping, a YES recorded on a HELD request runs (it is re-presented first, then approved)."""
    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    workflows.record_decision(areq["action_request_id"], "HOLD", areq["payload_hash"],
                              hold={"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["michael_ping"],
                                    "renotify_after": "PT1H", "escalate_after": "P30D"})
    wait_state(rt.engine, item_id, "HELD")
    workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"], auth_context=STEP_UP)
    wait_state(rt.engine, item_id, "ACTED")
    assert _effector_calls(rt.engine, areq["action_request_id"]) == 1


@pytest.mark.parametrize("decision", ["NO", "YES"])
def test_duplicate_gate_applies_a_decision_once_and_logs_no_errors(rt, run_discovery, caplog, decision):
    """F-113/F-118: a second gate on the same request (duplicate worker, orphan recovery) is a clean no-op."""
    from dbos import DBOS
    item_id = run_discovery("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending_request(rt.engine, item_id)
    twin = DBOS.start_workflow(workflows.followup_lifecycle, item_id, areq["action_request_id"])
    time.sleep(1.0)
    kw = {"auth_context": STEP_UP} if decision == "YES" else {"reason": "dup"}
    with caplog.at_level("ERROR"):
        workflows.record_decision(areq["action_request_id"], decision, areq["payload_hash"], **kw)
        wait_state(rt.engine, item_id, "ACTED" if decision == "YES" else "ARCHIVED")
        twin.get_result()
        DBOS.retrieve_workflow(f"item:{item_id}").get_result()
    assert [r.getMessage()[:200] for r in caplog.records if r.levelname == "ERROR"] == []
    assert _effector_calls(rt.engine, areq["action_request_id"]) == (1 if decision == "YES" else 0)
