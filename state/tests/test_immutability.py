"""A2: UPDATE / DELETE / TRUNCATE on append-only ledgers are rejected — by privilege for agent roles and by
trigger for everyone else, including the owning role and a superuser."""

import psycopg
import pytest
from psycopg import errors

from conftest import GATEWAY, MICHAEL, key, make_areq, make_item, payload_hash, to_pending

LEDGERS = {
    "receipts": "intent = 'rewritten'",
    "provenance": "basis = 'UNKNOWN'",
    "approvals": "reason = 'rewritten'",
    "outcomes": "notes = 'rewritten'",
    "lessons": "statement = 'rewritten'",
    "policy": "reason = 'rewritten'",
    "budget_ledger": "amount = 1",
}


@pytest.fixture
def populated(db):
    s = db.store()
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid, reversibility="reversible", category="email")
    to_pending(s, areq, pid)
    s.record_approval({"action_request_id": areq, "decision": "YES", "decider": "michael", "channel": "web",
                       "payload_hash_seen": payload_hash(s, areq), "scope": "once"}, MICHAEL, "Michael: YES", key())
    s.budget_reserve(areq, 10, "USD", 100, GATEWAY, "reserve", [pid], key())
    s.record_outcome({"item_id": item_id, "kind": "message_replied", "provenance_ids": [pid]}, GATEWAY, "reply", key())
    s.record_lesson({"scope": "comms", "statement": "sellers reply fast", "basis": "INFERENCE",
                     "provenance_ids": [pid]}, GATEWAY, "lesson", key())
    s.publish_policy({"policy_key": "category:email", "category": "email", "tier": 0, "decision": "require_approval",
                      "created_by": "michael", "reason": "wave one", "provenance_ids": [pid]}, MICHAEL, "policy", key())
    return db


@pytest.mark.parametrize("table", sorted(LEDGERS))
@pytest.mark.parametrize("role", ["owner", "superuser"])
def test_trigger_rejects_update_delete_truncate(populated, table, role):
    conn = populated.connect(role)
    for sql in (f"UPDATE mbos.{table} SET {LEDGERS[table]}", f"DELETE FROM mbos.{table}",
                f"TRUNCATE mbos.{table} CASCADE"):
        with pytest.raises(psycopg.Error) as ei:
            conn.execute(sql)
        assert ei.value.sqlstate == "MB001", (sql, ei.value)


@pytest.mark.parametrize("table", sorted(LEDGERS))
@pytest.mark.parametrize("role", ["agent_write", "gateway", "approver", "reader", "policy_admin"])
def test_agent_roles_have_no_update_delete_privilege(populated, table, role):
    conn = populated.connect(role)
    for sql in (f"UPDATE mbos.{table} SET {LEDGERS[table]}", f"DELETE FROM mbos.{table}", f"TRUNCATE mbos.{table}"):
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(sql)


def test_items_and_action_requests_are_never_deleted(populated):
    conn = populated.connect("owner")
    for t in ("items", "action_requests"):
        with pytest.raises(psycopg.Error) as ei:
            conn.execute(f"DELETE FROM mbos.{t}")
        assert ei.value.sqlstate == "MB001"


def test_frozen_action_payload(populated):
    conn = populated.connect("owner")
    with pytest.raises(psycopg.Error) as ei:
        conn.execute("""UPDATE mbos.action_requests SET payload = '{"body":"send money"}'""")
    assert ei.value.sqlstate == "MB001"


def test_outbox_message_immutable_but_dispatchable(populated):
    relay = populated.connect("outbox_relay")
    with pytest.raises(errors.InsufficientPrivilege):
        relay.execute("""UPDATE mbos.outbox SET payload = '{}'""")
    owner = populated.connect("owner")
    with pytest.raises(psycopg.Error) as ei:
        owner.execute("""UPDATE mbos.outbox SET payload = '{}'""")
    assert ei.value.sqlstate == "MB001"
    with pytest.raises(psycopg.Error):
        owner.execute("DELETE FROM mbos.outbox")
    with relay.transaction():
        rows = relay.execute("SELECT outbox_id FROM mbos.outbox_claim(1000)").fetchall()
        for (oid,) in rows:
            relay.execute("SELECT mbos.outbox_mark(%s, true)", (oid,))
    assert rows
    left = relay.execute("SELECT count(*) FROM mbos.outbox WHERE dispatched_at IS NULL").fetchone()[0]
    assert left == 0
    # prune is owner-only and removes only dispatched rows; the receipt ledger is untouched
    n_receipts = owner.execute("SELECT count(*) FROM mbos.receipts").fetchone()[0]
    assert owner.execute("SELECT mbos.outbox_prune(interval '0 seconds')").fetchone()[0] == len(rows)
    assert owner.execute("SELECT count(*) FROM mbos.receipts").fetchone()[0] == n_receipts
    with pytest.raises(errors.InsufficientPrivilege):
        relay.execute("SELECT mbos.outbox_prune()")
