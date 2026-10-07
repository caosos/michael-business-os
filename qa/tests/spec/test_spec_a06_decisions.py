"""A6 (real spine + DBOS): YES executes the frozen payload; NO archives with a reason; MODIFY creates a new request
(derived_from) and never mutates the old one; HOLD parks durably, wakes on its condition, re-notifies, and NEVER
auto-executes — including across a process restart."""
import json
import time
from datetime import datetime, timedelta, timezone

import pytest

from mbos_qa import impl_spine
from mbos_qa.core import sha256_ref
from mbos_qa.impl_spine import Refused

from .conftest import SERVICE_YES, effector_calls_for, invocations


def _iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def test_yes_executes_exactly_the_frozen_payload(qa, pending_flip):
    item_id, areq = pending_flip
    out = qa.decide(areq["action_request_id"], "YES")
    assert qa.wait_state(item_id, {"ACTED", "FAILED"}) == "ACTED"
    (ex,) = [r for r in qa.receipts(action_request_id=areq["action_request_id"]) if r["type"] == "ACTION_EXECUTED"]
    assert ex["payload_hash"] == areq["payload_hash"] == out["approval"]["payload_hash_seen"] == sha256_ref(areq["payload"])
    assert ex["approval_id"] == out["approval"]["approval_id"]
    assert invocations(qa, areq) == 1 and effector_calls_for(qa, areq["action_request_id"]) == 1


def test_service_lane_yes_also_executes(qa):
    item_id = qa.discover(SERVICE_YES)
    areq = qa.pending(item_id)
    qa.decide(areq["action_request_id"], "YES")
    assert qa.wait_state(item_id, {"ACTED", "FAILED"}) == "ACTED"


def test_yes_on_a_payload_not_seen_is_refused(qa, pending_flip):
    _, areq = pending_flip
    with pytest.raises(Refused):
        qa.decide(areq["action_request_id"], "YES", payload_hash_seen=sha256_ref({"other": 1}))
    assert qa.approvals(areq["action_request_id"]) == []


def test_irreversible_yes_without_step_up_is_refused(qa, pending_flip):
    _, areq = pending_flip
    assert areq["reversibility"] == "irreversible"
    with pytest.raises(Refused, match="step-up"):
        qa.decide(areq["action_request_id"], "YES", step_up=False)


def test_no_archives_with_reason_and_never_executes(qa, pending_flip):
    item_id, areq = pending_flip
    n_prov = qa.scalar("SELECT count(*) FROM mbos.provenance")
    with pytest.raises(Refused):
        qa.decide(areq["action_request_id"], "NO")  # the contract requires a reason
    assert qa.approvals(areq["action_request_id"]) == []
    assert qa.scalar("SELECT count(*) FROM mbos.provenance") == n_prov, "a refused decision left a partial write"
    qa.decide(areq["action_request_id"], "NO", reason="too far for the margin")
    assert qa.wait_state(item_id, "ARCHIVED") == "ARCHIVED"
    assert qa.areq(areq["action_request_id"])["status"] == "rejected"
    assert qa.approvals(areq["action_request_id"])[-1]["reason"] == "too far for the margin"
    assert invocations(qa, areq) == 0 and effector_calls_for(qa, areq["action_request_id"]) == 0


def test_modify_creates_new_request_and_never_mutates_the_old(qa, pending_flip):
    item_id, areq = pending_flip
    new_payload = {**areq["payload"], "summary": areq["payload"]["summary"] + " (QA MODIFY: offer lowered)"}
    out = qa.decide(areq["action_request_id"], "MODIFY", new_payload=new_payload, step_up=False)
    old = qa.areq(areq["action_request_id"])
    assert old["payload"] == areq["payload"] and old["payload_hash"] == areq["payload_hash"], "old request was mutated"
    assert old["status"] == "rejected"
    new_id = out["new_action_request_id"]
    new = qa.areq(new_id)
    assert new["derived_from"] == areq["action_request_id"]
    assert new["payload_hash"] == sha256_ref(new_payload) == out["approval"]["modifications"]["new_payload_hash"]
    time.sleep(1.0)
    assert qa.areq(new_id)["status"] == "pending_approval", "MODIFY is not approval of the new payload"
    assert invocations(qa, areq) == 0 and invocations(qa, new) == 0
    qa.decide(new_id, "YES")
    assert qa.wait_state(item_id, {"ACTED", "FAILED"}) == "ACTED"
    (ex,) = [r for r in qa.receipts(item_id=item_id) if r["type"] == "ACTION_EXECUTED"]
    assert ex["action_request_id"] == new_id and ex["payload_hash"] == new["payload_hash"]


def test_hold_wakes_at_hold_until_renotifies_and_never_executes(qa, pending_flip):
    item_id, areq = pending_flip
    until = datetime.now(timezone.utc) + timedelta(seconds=4)
    qa.decide(areq["action_request_id"], "HOLD", step_up=False,
              hold={"hold_until": _iso(until), "wake_on": ["time"], "renotify_after": "PT1S", "escalate_after": "P7D"})
    assert qa.wait_state(item_id, "HELD") == "HELD"
    assert qa.wait_state(item_id, "AWAITING_APPROVAL", timeout=30) == "AWAITING_APPROVAL"
    reqs = [r for r in qa.receipts(action_request_id=areq["action_request_id"]) if r["type"] == "APPROVAL_REQUESTED"]
    assert any("re-notify" in r["intent"] for r in reqs), "no re-notify receipt while held"
    assert any("never auto-executed" in r["intent"] or "re-presented" in r["intent"] for r in reqs)
    time.sleep(1.5)
    assert qa.areq(areq["action_request_id"])["status"] == "pending_approval"
    assert invocations(qa, areq) == 0 and effector_calls_for(qa, areq["action_request_id"]) == 0
    assert not [r for r in qa.receipts(action_request_id=areq["action_request_id"]) if r["type"] == "ACTION_EXECUTING"]


def test_hold_wakes_only_on_declared_condition(qa, pending_flip):
    item_id, areq = pending_flip
    qa.decide(areq["action_request_id"], "HOLD", step_up=False,
              hold={"hold_until": "2099-01-01T00:00:00Z", "wake_on": ["time"], "renotify_after": "PT1H", "escalate_after": "P30D"})
    qa.wait_state(item_id, "HELD")
    qa.ping(item_id)  # michael_ping is NOT in wake_on
    time.sleep(2.0)
    assert qa.item(item_id)["state"] == "HELD"
    assert invocations(qa, areq) == 0


def test_hold_survives_a_process_restart_and_never_executes(qa):
    urls = (impl_spine.new_database("qa_hold_app"), impl_spine.new_database("qa_hold_sys"))
    first = impl_spine.child("hold", "FIX-TRAILER-1", urls=urls)
    assert first.returncode == 0, first.stderr[-2000:]
    item_id = next(ln.split()[1] for ln in first.stdout.splitlines() if ln.startswith("ITEM"))
    assert "STATE HELD" in first.stdout
    second = impl_spine.child("resume", item_id, "hold_check", urls=urls)
    assert second.returncode == 0, second.stderr[-2000:]
    assert "STATE_AFTER_RESTART HELD" in second.stdout, second.stdout
    assert "STATE AWAITING_APPROVAL" in second.stdout  # woke on michael_ping after restart …
    inv = json.loads(next(ln.split(" ", 1)[1] for ln in second.stdout.splitlines() if ln.startswith("INVOCATIONS")))
    assert sum(inv.values()) == 0  # … and nothing executed
