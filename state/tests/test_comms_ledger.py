"""D-10: Agent 06's consent/DNC ledger (F-07) on lane D's schema. Statements below are 06's own SQL from
comms_spec/ledger.py (@ 19b0982), with receipts written through lane D's append_receipt."""

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from mbos_state.ids import ulid
from conftest import key, tool_prov

ACTOR = {"type": "agent", "id": "agent-06-communications"}


def register_contact(conn, subject_ref, channel, value):
    row = conn.execute("SELECT contact_ref FROM mbos_comms.contacts WHERE channel = %s AND value = %s",
                       (channel, value)).fetchone()
    if row:
        return row[0]
    ref = f"cref_{ulid()}"
    conn.execute("INSERT INTO mbos_comms.contacts (contact_ref, subject_ref, channel, value) VALUES (%s, %s, %s, %s)",
                 (ref, subject_ref, channel, value))
    return ref


def _receipt(conn, rtype, entity_type, cref, intent, prov, after):
    return conn.execute("SELECT receipt_id FROM mbos.append_receipt(%s)", (Jsonb({
        "type": rtype, "intent": intent, "provenance_ids": [prov], "actor": ACTOR, "entity_type": entity_type,
        "entity_id": cref, "effect": "create", "tool_name": "comms_spec.ledger@0.1.0", "idempotency_key": key("c"),
        "after_state": after, "details": {"kind": "comms", "dry_run": True, "contact_ref": cref}}),)).fetchone()[0]


def record_consent(conn, cref, event="granted", basis="inbound_inquiry"):
    prov = tool_prov_conn(conn)
    rid = _receipt(conn, "GRANT_CREATED" if event == "granted" else "GRANT_REVOKED", "consent", cref,
                   f"consent {event} ({basis})", prov, {"consent": event, "basis": basis})
    conn.execute("INSERT INTO mbos_comms.consent_events (contact_ref, event, basis, evidence_uri, recorded_at, receipt_id) "
                 "VALUES (%s, %s, %s, %s, now(), %s)", (cref, event, basis, "https://example.invalid/form", rid))
    return rid


def record_dnc_scrub(conn, cref, listed):
    prov = tool_prov_conn(conn)
    rid = _receipt(conn, "GRANT_REVOKED" if listed else "GRANT_CREATED", "dnc_scrub", cref, "DNC scrub", prov,
                   {"dnc": "listed" if listed else "clear"})
    conn.execute("INSERT INTO mbos_comms.dnc_scrubs (contact_ref, scrubbed_at, listed, source, receipt_id) "
                 "VALUES (%s, now(), %s, 'national_dnc_registry', %s)", (cref, listed, rid))
    return rid


def tool_prov_conn(conn):
    return conn.execute("SELECT mbos.record_provenance(%s)", (Jsonb({
        "actor_type": "system", "agent_name": ACTOR["id"], "basis": "FACT", "tool_name": "comms_spec.ledger",
        "tool_version": "0.1.0"}),)).fetchone()[0]


@pytest.fixture
def gw(db):
    return db.connect("gateway")


def test_06_flow_on_lane_d_schema(db, gw):
    with gw.transaction():
        cref = register_contact(gw, "https://example.invalid/listing/1", "email", "seller@example.invalid")
        assert register_contact(gw, "x", "email", "seller@example.invalid") == cref      # idempotent
        record_consent(gw, cref)
        record_dnc_scrub(gw, cref, listed=False)
    with gw.transaction():
        record_consent(gw, cref, "revoked", "stop_keyword")
    last = gw.execute("SELECT event FROM mbos_comms.consent_events WHERE contact_ref=%s ORDER BY seq DESC LIMIT 1",
                      (cref,)).fetchone()[0]
    assert last == "revoked"
    # receipts never carry the raw value; chain still verifies
    texts = [r[0] for r in gw.execute("SELECT canonical FROM mbos.receipts WHERE entity_id=%s", (cref,))]
    assert len(texts) == 3 and not any("seller@example.invalid" in t for t in texts)
    assert gw.execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]


def test_insert_only_with_06_error_text(db, gw):
    with gw.transaction():
        cref = register_contact(gw, "s", "sms", "+15015550142")
        record_consent(gw, cref)
    owner = db.connect("owner")
    for sql in ("UPDATE mbos_comms.contacts SET value = 'x'", "DELETE FROM mbos_comms.consent_events",
                "TRUNCATE mbos_comms.dnc_scrubs CASCADE", "UPDATE mbos_comms.consent_events SET event = 'granted'"):
        with pytest.raises(psycopg.Error, match="insert-only") as ei:
            owner.execute(sql)
        assert ei.value.sqlstate == "MB001"


def test_event_and_receipt_commit_together(db, gw):
    with gw.transaction():
        cref = register_contact(gw, "s", "sms", "+15015550199")
    n = gw.execute("SELECT count(*) FROM mbos.receipts").fetchone()[0]
    with pytest.raises(RuntimeError):
        with gw.transaction():
            record_consent(gw, cref)
            raise RuntimeError("fault after receipt + ledger row")
    assert gw.execute("SELECT count(*) FROM mbos.receipts").fetchone()[0] == n
    assert gw.execute("SELECT count(*) FROM mbos_comms.consent_events").fetchone()[0] == 0


def test_event_needs_its_own_same_tx_receipt(db, gw):
    with gw.transaction():
        cref = register_contact(gw, "s", "email", "a@example.invalid")
        other = register_contact(gw, "s2", "email", "b@example.invalid")
        old = record_consent(gw, cref)
    with pytest.raises(psycopg.Error) as ei:              # a receipt from an earlier transaction
        gw.execute("INSERT INTO mbos_comms.consent_events (contact_ref, event, basis, recorded_at, receipt_id) "
                   "VALUES (%s, 'granted', 'x', now(), %s)", (cref, old))
    assert ei.value.sqlstate in ("MB003", "23505")
    with gw.transaction():
        prov = tool_prov_conn(gw)
        rid = _receipt(gw, "GRANT_CREATED", "consent", other, "for another contact", prov, {})
    with pytest.raises(psycopg.Error) as ei:              # receipt for a different contact, and stale
        with gw.transaction():
            gw.execute("INSERT INTO mbos_comms.consent_events (contact_ref, event, basis, recorded_at, receipt_id) "
                       "VALUES (%s, 'granted', 'x', now(), %s)", (cref, rid))
    assert ei.value.sqlstate == "MB003"
    with pytest.raises(psycopg.Error) as ei:              # receipt direction must match (revoked needs GRANT_REVOKED)
        with gw.transaction():
            prov = tool_prov_conn(gw)
            rid = _receipt(gw, "GRANT_CREATED", "consent", cref, "wrong type", prov, {})
            gw.execute("INSERT INTO mbos_comms.consent_events (contact_ref, event, basis, recorded_at, receipt_id) "
                       "VALUES (%s, 'revoked', 'x', now(), %s)", (cref, rid))
    assert ei.value.sqlstate == "MB003"


def test_fail_safe_asymmetry(db, gw):
    with gw.transaction():
        cref = register_contact(gw, "s", "sms", "+15015550100")
    agent = db.connect("agent_write")
    with pytest.raises(errors.InsufficientPrivilege):    # agents cannot grant consent ...
        with agent.transaction():
            record_consent(agent, cref)
    with pytest.raises(errors.InsufficientPrivilege):    # ... or clear a DNC scrub
        with agent.transaction():
            record_dnc_scrub(agent, cref, listed=False)
    with agent.transaction():                            # but STOP / listing always records
        record_consent(agent, cref, "revoked", "stop_keyword")
        record_dnc_scrub(agent, cref, listed=True)


def test_raw_values_visible_to_gateway_only(db, gw):
    with gw.transaction():
        register_contact(gw, "s", "email", "private@example.invalid")
    for role in ("reader", "agent_write", "approver"):
        c = db.connect(role)
        assert c.execute("SELECT contact_ref, subject_ref, channel FROM mbos_comms.contacts").fetchall()
        with pytest.raises(errors.InsufficientPrivilege):
            c.execute("SELECT value FROM mbos_comms.contacts")
    assert gw.execute("SELECT value FROM mbos_comms.contacts").fetchone()[0] == "private@example.invalid"
