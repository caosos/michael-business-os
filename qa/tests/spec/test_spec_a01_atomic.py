"""A1 (real spine): a state change and its receipt commit in one transaction — a fault between them leaves neither."""
import pytest
import sqlalchemy as sa


def _snapshot(qa, led, item_id):
    return qa.item(item_id, led.engine)["state"], len(qa.receipts(led.engine)), \
        qa.scalar("SELECT count(*) FROM mbos.outbox", led.engine)


def test_python_fault_after_state_write_rolls_back_both(qa, led, monkeypatch):
    import mbos.ledger as ledger

    item_id = led.seed(approve=False)["item_id"]  # AWAITING_APPROVAL
    before = _snapshot(qa, led, item_id)

    def boom(*a, **k):
        raise RuntimeError("QA fault injected between state write and receipt")

    monkeypatch.setattr(ledger, "append_receipt", boom)
    with pytest.raises(RuntimeError):
        with led.engine.begin() as c:
            ledger.transition_item(c, item_id, "HELD", intent="qa", provenance_ids=[qa.item(item_id, led.engine)["provenance_ids"][0]])
    monkeypatch.undo()
    assert _snapshot(qa, led, item_id) == before


def test_db_side_receipt_failure_rolls_back_the_state_change(qa, led):
    import mbos.ledger as ledger

    item_id = led.seed(approve=False)["item_id"]
    before = _snapshot(qa, led, item_id)
    with pytest.raises(sa.exc.DBAPIError):
        with led.engine.begin() as c:  # unknown provenance id: refused by the DB, not by Python
            ledger.transition_item(c, item_id, "HELD", intent="qa", provenance_ids=["prov_01ZZZZZZZZZZZZZZZZZZZZZZZZ"])
    assert _snapshot(qa, led, item_id) == before


def test_illegal_transition_refused_by_the_database_itself(qa, led):
    item_id = led.seed(approve=False)["item_id"]
    with pytest.raises(sa.exc.DBAPIError, match="illegal item transition"):
        led.superuser_sql("UPDATE mbos.items SET body = jsonb_set(body, '{state}', '\"LEARNED\"') WHERE item_id = :i",
                          i=item_id)
    assert qa.item(item_id, led.engine)["state"] == "AWAITING_APPROVAL"


def test_item_state_history_is_reconstructable_from_receipts(qa, pending_flip):
    item_id, areq = pending_flip
    qa.decide(areq["action_request_id"], "YES")
    qa.wait_state(item_id, {"ACTED", "FAILED"})
    changes = [r for r in qa.receipts(item_id=item_id, type="ITEM_STATE_CHANGED")]
    assert (changes[0].get("before_state") or {}).get("state") is None  # genesis; ADR-0010 drops top-level nulls
    for prev, nxt in zip(changes, changes[1:]):
        assert nxt["before_state"]["state"] == prev["after_state"]["state"], "gap in the receipted state history"
    assert changes[-1]["after_state"]["state"] == qa.item(item_id)["state"]
