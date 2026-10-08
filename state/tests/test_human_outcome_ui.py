"""P-06-19: Michael records a HUMAN outcome through the Operator UI (real login mbos_operator_ui = role approver).
A closing human outcome moves capital (D-18); the UI role is refused any non-human actor; agent_write is unchanged;
the UI role still cannot mint capital directly."""

import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import AGENT, GATEWAY, MICHAEL, key, make_areq, make_item, payload_hash, to_pending
from mbos_state.store import Actor
from test_capital_ledger import Cap
from test_flow import yes


def _executed_areq(db):
    agent, gw, ui = db.store("agent_write"), db.store("gateway"), db.store("approver")
    item_id, pid = make_item(agent, "RECOMMENDED")
    areq = make_areq(agent, item_id, pid)
    to_pending(gw, areq, pid)
    appr = ui.record_approval(yes(areq, payload_hash(ui, areq)), MICHAEL, "Michael: YES", key())
    gw.set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "guard passed", [pid], key(),
                         extra={"approval_id": appr})
    gw.set_action_status(areq, "executed", "ACTION_EXECUTED", GATEWAY, "dry-run send", [pid], key(),
                         extra={"approval_id": appr, "effect": "send", "tool_name": "comms-mock 0.1",
                                "effector_response": {"provider": "mock", "status": "accepted", "dry_run": True},
                                "details": {"kind": "comms"}})
    return item_id, areq, pid


def test_ui_role_records_a_human_outcome(db):
    item_id, areq, pid = _executed_areq(db)
    ui = db.store("approver")
    assert ui.conn.execute("SELECT session_user").fetchone()[0] == "mbos_operator_ui"
    k = key("ui-outcome")
    out = {"item_id": item_id, "action_request_id": areq, "kind": "message_replied", "provenance_ids": [pid]}
    oid = ui.record_outcome(out, MICHAEL, "Michael: seller replied", k)
    assert oid.startswith("outc_")
    assert ui.record_outcome(out, MICHAEL, "Michael: seller replied", k) == oid          # idempotent replay
    st = ui.conn.execute("SELECT status FROM mbos.action_requests WHERE action_request_id=%s", (areq,)).fetchone()[0]
    assert st == "outcome_recorded"
    actor = ui.conn.execute("SELECT actor FROM mbos.receipts WHERE outcome_id=%s AND type='OUTCOME_RECORDED'",
                            (oid,)).fetchone()[0]
    assert actor == {"type": "human", "id": "michael"}
    assert ui.verify_chain().ok


@pytest.mark.parametrize("actor", [AGENT, GATEWAY, Actor("human", " ")])
def test_ui_role_refuses_a_non_human_actor(db, actor):
    item_id, pid = make_item(db.store("agent_write"), "RESEARCHING")
    ui = db.store("approver")
    with pytest.raises(errors.InsufficientPrivilege, match="human outcome"):
        ui.record_outcome({"item_id": item_id, "kind": "message_replied", "provenance_ids": [pid]},
                          actor, "agent pretending via the UI", key())
    assert db.connect("reader").execute("SELECT count(*) FROM mbos.outcomes").fetchone()[0] == 0


def test_agent_write_unchanged(db):
    agent = db.store("agent_write")
    item_id, pid = make_item(agent, "RESEARCHING")
    agent.record_outcome({"item_id": item_id, "kind": "message_replied", "provenance_ids": [pid]}, AGENT, "agent outcome", key())
    with pytest.raises(errors.InsufficientPrivilege):      # D-28 (F-86): a human claim from agent_write is refused
        agent.record_outcome({"item_id": item_id, "kind": "message_replied", "provenance_ids": [pid]}, MICHAEL, "forged", key())
    assert db.connect("reader").execute("SELECT count(*) FROM mbos.outcomes").fetchone()[0] == 1
    assert agent.verify_chain().ok


def test_ui_human_closing_outcome_moves_capital_and_capital_stays_approver_only(db):
    cap = Cap(db)
    cap.fund(500)
    item = cap.item(); cap.deploy(item, 40)
    ui = db.store("approver")
    cap.close(item, 100, 40, store=ui)                                                   # Michael via the UI
    assert cap.pos()[:4] == (500, 60, 0, 60)
    assert cap.verified()[0]
    with pytest.raises(errors.InsufficientPrivilege):                                    # agent actor via the UI
        cap.close(cap.item(), 9999, 1, store=db.store("approver"), human=False)
    with pytest.raises(errors.InsufficientPrivilege):                                    # agents still cannot close
        cap.close(cap.item(), 5000, 1, store=db.store("agent_write"))
    for role in ("agent_write", "gateway"):                                              # nor fund
        with pytest.raises(errors.InsufficientPrivilege):
            db.connect(role).execute("SELECT mbos.capital_fund(1000::numeric,%s,'x',%s,%s)",
                                     (Jsonb({"type": "human", "id": "michael"}), [cap.pid], key()))
    assert cap.pos()[:4] == (500, 60, 0, 60)
    assert db.connect("reader").execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]
