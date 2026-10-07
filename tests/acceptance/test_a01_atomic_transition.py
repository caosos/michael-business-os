"""A1. Each transition writes its state change and its receipt in one transaction.
A fault injected between them leaves both or neither."""

import pytest
import sqlalchemy as sa

from mbos import ledger
from tests.helpers.common import scalar
from tests.helpers.seed import seed_flow

pytestmark = pytest.mark.acceptance


def _snapshot(engine, item_id):
    return (scalar(engine, "SELECT state FROM mbos.items WHERE item_id = :i", i=item_id),
            scalar(engine, "SELECT count(*) FROM mbos.receipts"),
            scalar(engine, "SELECT count(*) FROM mbos.outbox"))


def test_fault_between_state_change_and_receipt_leaves_neither(ledger_db, monkeypatch):
    item_id = seed_flow(ledger_db, act=False)["item_id"]  # AWAITING_APPROVAL
    before = _snapshot(ledger_db, item_id)

    def boom(*a, **k):
        raise RuntimeError("injected fault after UPDATE items, before INSERT receipts")

    with pytest.raises(RuntimeError, match="injected fault"):
        with ledger_db.begin() as c:
            prov = ledger.tool_provenance(c, "tests.a1")
            monkeypatch.setattr(ledger, "append_receipt", boom)
            ledger.transition_item(c, item_id, "HELD", intent="A1 fault test", provenance_ids=[prov])
            # the UPDATE ran; the receipt never did
    assert _snapshot(ledger_db, item_id) == before, "neither the state change nor a receipt may survive"


def test_db_side_receipt_failure_rolls_back_state_change(ledger_db):
    item_id = seed_flow(ledger_db, act=False)["item_id"]
    before = _snapshot(ledger_db, item_id)
    with pytest.raises(sa.exc.DBAPIError, match="no receipt without provenance"):
        with ledger_db.begin() as c:  # provenance id is well-formed but does not exist → DB trigger refuses
            ledger.transition_item(c, item_id, "HELD", intent="A1", provenance_ids=["prov_01JA0000000000000000000099"])
    assert _snapshot(ledger_db, item_id) == before


def test_successful_transition_writes_both(ledger_db):
    item_id = seed_flow(ledger_db, act=False)["item_id"]
    state0, n0, _ = _snapshot(ledger_db, item_id)
    with ledger_db.begin() as c:
        prov = ledger.tool_provenance(c, "tests.a1")
        ledger.transition_item(c, item_id, "HELD", intent="A1 ok", provenance_ids=[prov])
    state1, n1, _ = _snapshot(ledger_db, item_id)
    assert (state0, state1) == ("AWAITING_APPROVAL", "HELD")
    assert n1 == n0 + 1
    last = ledger.load_receipts(ledger_db.connect(), "item_id = :i", {"i": item_id})[-1]
    assert last["type"] == "ITEM_STATE_CHANGED"
    assert last["before_state"]["state"] == "AWAITING_APPROVAL" and last["after_state"]["state"] == "HELD"


def test_illegal_transition_refused_by_db_even_without_python_check(ledger_db):
    item_id = seed_flow(ledger_db, act=False)["item_id"]
    with pytest.raises(sa.exc.DBAPIError, match="illegal item transition"):
        with ledger_db.begin() as c:
            c.execute(sa.text("UPDATE mbos.items SET body = jsonb_set(body, '{state}', '\"ACTED\"') WHERE item_id = :i"),
                      {"i": item_id})
