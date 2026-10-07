"""A6 — YES executes the frozen payload. NO archives with a reason. MODIFY creates a new areq with
derived_from. HOLD survives a restart, wakes on its condition, re-notifies after the TTL and NEVER
auto-executes."""
import json
from datetime import timedelta

import pytest

from mbos_qa import drafts
from mbos_qa.core import sha256_ref
from mbos_qa.harness import build
from mbos_qa.mocks.governance import GuardDenied
from mbos_qa.mocks.workflow import ApprovalRejected

from .conftest import approve, effector_attempts, pending


# ---------------------------------------------------------------- YES
def test_yes_executes_exactly_the_frozen_payload(h):
    item_id, areq = pending(h)
    appr = approve(h, areq)
    h.workflow.act(item_id)
    (ex,) = h.store.receipts(type="ACTION_EXECUTED")
    assert ex["payload_hash"] == areq["payload_hash"] == appr["payload_hash_seen"] == sha256_ref(areq["payload"])
    assert ex["approval_id"] == appr["approval_id"]
    packet = json.loads((h.workdir / "packets" / f"{areq['action_request_id']}.json").read_text())
    assert packet["payload_hash"] == areq["payload_hash"]
    assert packet["content_hash"] == sha256_ref(areq["payload"]["content"])
    md = (h.workdir / "packets" / f"{areq['action_request_id']}.md").read_text()
    assert areq["payload"]["content"]["body"] in md
    assert sha256_ref(md) == ex["artifact_hashes"][0]


def test_yes_on_a_different_payload_is_void(h):
    _, areq = pending(h)
    with pytest.raises(ApprovalRejected):
        h.workflow.decide(areq["action_request_id"], "YES", payload_hash_seen=sha256_ref({"other": 1}))
    assert h.store.approvals_for(areq["action_request_id"]) == []


def test_payload_swapped_after_yes_is_refused(h):
    item_id, areq = pending(h)
    appr = approve(h, areq)
    swapped = h.store.get("action-request", areq["action_request_id"])
    swapped["payload"]["content"]["body"] = "Send me your bank details"
    h.store.conn.execute("UPDATE action_requests SET doc=? WHERE action_request_id=?",
                         (json.dumps(swapped), areq["action_request_id"]))
    with pytest.raises(GuardDenied) as e:
        h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    assert e.value.check == "3-payload-hash"
    assert effector_attempts(h) == 0
    assert h.store.receipts(type="POLICY_DECIDED", action_request_id=areq["action_request_id"])[-1]["after_state"]["guard"] == "deny"


def test_irreversible_yes_without_step_up_is_refused(h):
    _, areq = pending(h)
    appr = approve(h, areq, step_up=False)
    with pytest.raises(GuardDenied) as e:
        h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    assert e.value.check == "6-grant" and effector_attempts(h) == 0


def test_expired_request_is_refused(h):
    _, areq = pending(h)
    appr = approve(h, areq)
    h.clock.advance(timedelta(days=3))
    with pytest.raises(GuardDenied) as e:
        h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    assert e.value.check == "2-not-expired" and effector_attempts(h) == 0


# ---------------------------------------------------------------- NO
def test_no_requires_reason(h):
    _, areq = pending(h)
    with pytest.raises(ApprovalRejected):
        h.workflow.decide(areq["action_request_id"], "NO")


def test_no_archives_with_reason_and_never_executes(h):
    item_id, areq = pending(h)
    appr = h.workflow.decide(areq["action_request_id"], "NO", reason="too far for the margin")
    assert appr["reason"] == "too far for the margin"
    assert h.store.get("action-request", areq["action_request_id"])["status"] == "rejected"
    assert h.store.get("item", item_id)["state"] == "ARCHIVED"
    with pytest.raises(GuardDenied):
        h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    h.workflow.act(item_id)
    assert effector_attempts(h) == 0
    decided = h.store.receipts(type="APPROVAL_DECIDED", action_request_id=areq["action_request_id"])
    assert "too far for the margin" in decided[-1]["intent"]


# ---------------------------------------------------------------- MODIFY
def test_modify_creates_new_request_and_never_mutates_the_old(h):
    item_id, areq = pending(h)
    original = h.store.get("action-request", areq["action_request_id"])
    new_payload = drafts.seller_inquiry(h.store.get("item", item_id), offer=800, questions=["Still available?"])
    appr = h.workflow.decide(areq["action_request_id"], "MODIFY", new_payload=new_payload)

    old = h.store.get("action-request", areq["action_request_id"])
    assert old["payload"] == original["payload"] and old["payload_hash"] == original["payload_hash"]
    assert old["status"] == "rejected"

    new_id = appr["modifications"]["new_action_request_id"]
    new = h.store.get("action-request", new_id)
    assert new["derived_from"] == areq["action_request_id"]
    assert new["payload_hash"] == appr["modifications"]["new_payload_hash"] == sha256_ref(new_payload)
    assert new["status"] == "pending_approval", "MODIFY is not approval of the new payload"
    assert appr["modifications"]["diff"]

    with pytest.raises(GuardDenied):  # old request can never run
        h.gateway.execute(areq["action_request_id"], appr["approval_id"])
    h.workflow.act(item_id)
    assert effector_attempts(h) == 0, "the modified request executed without its own YES"

    yes = h.workflow.decide(new_id, "YES")
    h.workflow.act(item_id)
    (ex,) = h.store.receipts(type="ACTION_EXECUTED")
    assert ex["action_request_id"] == new_id and ex["approval_id"] == yes["approval_id"]


# ---------------------------------------------------------------- HOLD
HOLD = {"hold_until": "2026-10-10T12:00:00Z", "wake_on": ["time", "price_change"],
        "renotify_after": "PT24H", "escalate_after": "PT60H"}


def test_hold_requires_until_and_wake_condition(h):
    _, areq = pending(h)
    with pytest.raises(ApprovalRejected):
        h.workflow.decide(areq["action_request_id"], "HOLD", hold={"renotify_after": "PT24H"})


def test_hold_survives_restart(tmp_path):
    h = build(tmp_path / "run")
    item_id, areq = pending(h)
    h.workflow.decide(areq["action_request_id"], "HOLD", hold=HOLD)
    h.store.close()
    h2 = build(tmp_path / "run", seed=None)
    assert h2.store.get("action-request", areq["action_request_id"])["status"] == "held"
    assert h2.store.get("item", item_id)["state"] == "HELD"
    assert h2.store.approvals_for(areq["action_request_id"])[-1]["hold"]["hold_until"] == HOLD["hold_until"]
    h2.workflow.act(item_id)
    assert effector_attempts(h2) == 0


def test_hold_renotifies_then_wakes_and_never_executes(h):
    item_id, areq = pending(h)
    appr = h.workflow.decide(areq["action_request_id"], "HOLD", hold=HOLD)
    rid = areq["action_request_id"]

    with pytest.raises(GuardDenied):
        h.gateway.execute(rid, appr["approval_id"])

    h.clock.advance(timedelta(hours=25))
    assert h.workflow.tick() == [f"renotify:{rid}:1"]
    assert h.workflow.tick() == [], "re-notify must be idempotent within a TTL window"
    h.workflow.act(item_id)
    assert h.store.get("action-request", rid)["status"] == "held"

    h.clock.advance(timedelta(hours=24))
    assert h.workflow.tick() == [f"renotify:{rid}:2"]

    h.clock.advance(timedelta(hours=24))  # past hold_until (72h)
    events = h.workflow.tick()
    assert events == [f"woke: hold_until reached:{rid}"]
    assert h.store.get("action-request", rid)["status"] == "pending_approval"
    assert h.store.get("item", item_id)["state"] == "AWAITING_APPROVAL"
    for _ in range(5):
        h.workflow.tick()
        h.workflow.act(item_id)
    assert effector_attempts(h) == 0
    assert h.store.receipts(type="ACTION_EXECUTING") == [] and h.store.receipts(type="ACTION_EXECUTED") == []
    requested = h.store.receipts(type="APPROVAL_REQUESTED", action_request_id=rid)
    assert any("NOT executed" in r["intent"] for r in requested)


def test_hold_escalates_without_executing(h):
    item_id, areq = pending(h)
    h.workflow.decide(areq["action_request_id"], "HOLD",
                      hold={**HOLD, "hold_until": "2026-10-20T00:00:00Z", "escalate_after": "PT36H"})
    h.clock.advance(timedelta(hours=37))
    assert any(e.startswith("escalated") for e in h.workflow.tick())
    assert h.store.get("action-request", areq["action_request_id"])["status"] == "pending_approval"
    h.workflow.act(item_id)
    assert effector_attempts(h) == 0


def test_hold_wakes_only_on_declared_condition(h):
    _, areq = pending(h)
    h.workflow.decide(areq["action_request_id"], "HOLD", hold=HOLD)
    assert h.workflow.wake(areq["action_request_id"], "auction_ending") is None
    assert h.store.get("action-request", areq["action_request_id"])["status"] == "held"
    assert h.workflow.wake(areq["action_request_id"], "price_change")
    assert h.store.get("action-request", areq["action_request_id"])["status"] == "pending_approval"
    assert effector_attempts(h) == 0
