"""A1 — each transition writes its state change and its receipt in one transaction.
A fault injected between them leaves BOTH or NEITHER."""
import pytest

from mbos_qa.mocks.store import InjectedFault, InvariantViolation
from mbos_qa.mocks.workflow import WF
from mbos_qa.statemachine import IllegalTransition

from .conftest import pending


def _boom():
    raise InjectedFault("simulated crash")


def _snapshot(h, item_id):
    return (h.store.get("item", item_id)["state"], h.store.count("receipts"), h.store.count("outbox"))


@pytest.mark.parametrize("point", ["after_state_before_receipt", "after_receipt_before_commit"])
def test_fault_between_state_and_receipt_leaves_neither(h, point):
    item_id, areq = pending(h)
    before = _snapshot(h, item_id)
    h.store.faults[point] = _boom
    with pytest.raises(InjectedFault):
        h.workflow.decide(areq["action_request_id"], "YES")
    assert _snapshot(h, item_id) == before, "partial write survived a fault"
    assert h.store.get("action-request", areq["action_request_id"])["status"] == "pending_approval"
    assert h.store.approvals_for(areq["action_request_id"]) == []

    h.store.faults.clear()
    h.workflow.decide(areq["action_request_id"], "YES")
    state, n_rcpt, n_outbox = _snapshot(h, item_id)
    assert state == "APPROVED"
    assert n_rcpt > before[1] and n_outbox - before[2] == n_rcpt - before[1], "every receipt has its outbox row"
    last = h.store.receipts(item_id=item_id, type="ITEM_STATE_CHANGED")[-1]
    assert last["before_state"] == {"state": "AWAITING_APPROVAL"} and last["after_state"] == {"state": "APPROVED"}


def test_unresolvable_provenance_rolls_back_the_state_change(h):
    item_id, _ = pending(h)
    before = _snapshot(h, item_id)
    with pytest.raises(InvariantViolation):
        with h.store.tx() as t:
            t.transition_item(item_id, "HELD", actor=WF, intent="x", provenance_ids=["prov_01ZZZZZZZZZZZZZZZZZZZZZZZZ"])
    assert _snapshot(h, item_id) == before


def test_illegal_transition_writes_nothing(h):
    item_id, _ = pending(h)
    before = _snapshot(h, item_id)
    with pytest.raises(IllegalTransition):
        with h.store.tx() as t:
            t.transition_item(item_id, "ACTED", actor=WF, intent="skip ahead", provenance_ids=[h.workflow.prov_id])
    assert _snapshot(h, item_id) == before


def test_item_state_is_reconstructable_from_receipts(ran):
    for r in ran.results:
        item = ran.store.get("item", r["item_id"])
        changes = ran.store.receipts(item_id=r["item_id"], type="ITEM_STATE_CHANGED")
        assert changes[0]["before_state"] is None
        for prev, nxt in zip(changes, changes[1:]):
            assert nxt["before_state"]["state"] == prev["after_state"]["state"], "gap in the state history"
        assert changes[-1]["after_state"]["state"] == item["state"]
        assert set(item["receipt_ids"]) == {c["receipt_id"] for c in changes}


def test_reingesting_the_same_listing_dedups_without_new_writes(h):
    from mbos_qa.e2e import FIXTURES
    first = h.workflow.ingest(FIXTURES / "flip_trailer" / "raw.json")
    n = (h.store.count("items"), h.store.count("receipts"))
    assert h.workflow.ingest(FIXTURES / "flip_trailer" / "raw.json") == first
    assert (h.store.count("items"), h.store.count("receipts")) == n
