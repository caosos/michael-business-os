"""F-07: consent ledger + DNC scrub store on the real spine database (pgserver Postgres, mbos @ aa88e7a)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

import comms_spec as cs
from comms_spec import ledger as L
from comms_spec.effector import CommsDryRunEffector
from comms_spec.planner import CommsActionPlanner
from mbos import workflows
from mbos.ledger import verify_chain
from mbos.reference.governance import DryRunEffector, ReferenceGateway
from mbos.runtime import components

NOON_AR = datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc)
STEP_UP = {"method": "test_step_up", "step_up": True}
RAW_EMAIL = "Seller.Person+trailer@Example.invalid"
RAW_PHONE = "(501) 555-0142"


@pytest.fixture()
def ledger(rt):
    first = L.ensure_schema(rt.engine)
    assert first in ("created", "skipped")
    assert L.ensure_schema(rt.engine) == "skipped"  # owner-managed on lane D: never re-create (Agent 04, D-10)
    return L.ConsentLedger(rt.engine)


def q(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(sa.text(sql), p).all()


def subject(tag):
    return f"https://example.invalid/listing/{tag}"


def test_tables_are_insert_only(rt, ledger):
    with rt.engine.begin() as c:
        cref = L.register_contact(c, subject("io"), "email", "io@example.invalid")
        L.record_consent(c, cref, "inbound_inquiry", "https://example.invalid/form/io")
    for sql in ("UPDATE mbos_comms.contacts SET value = 'x'", "DELETE FROM mbos_comms.consent_events",
                "TRUNCATE mbos_comms.dnc_scrubs", "UPDATE mbos_comms.consent_events SET event = 'granted'"):
        with pytest.raises(sa.exc.DBAPIError, match="insert-only"):
            with rt.engine.begin() as c:
                c.execute(sa.text(sql))


def test_raw_values_stay_in_contacts_and_receipts_are_chained(rt, ledger):
    with rt.engine.begin() as c:
        cref = L.register_contact(c, subject("raw"), "email", RAW_EMAIL)
        assert L.register_contact(c, subject("raw"), "email", RAW_EMAIL.upper()) == cref  # normalized, idempotent
        r1 = L.record_consent(c, cref, "listing_published_contact", subject("raw"))
        r2 = L.record_dnc_scrub(c, cref, listed=False)
    assert cref.startswith("cref_")
    for r in (r1, r2):
        body = q(rt.engine, "SELECT body FROM mbos.receipts WHERE receipt_id = :r", r=r["receipt_id"])[0][0]
        text = json.dumps(body).lower()
        assert "seller.person" not in text and "example.invalid\"" not in text.replace(subject("raw"), "")
        assert body["entity_id"] == cref and body["details"]["kind"] == "comms"
    assert (r1["type"], r2["type"]) == ("GRANT_CREATED", "GRANT_CREATED")
    with rt.engine.connect() as c:
        assert verify_chain(c)["ok"] is True
    ((stored,),) = q(rt.engine, "SELECT value FROM mbos_comms.contacts WHERE contact_ref = :c", c=cref)
    assert stored == RAW_EMAIL.lower()


def test_ledger_event_and_receipt_commit_together(rt, ledger, monkeypatch):
    with rt.engine.begin() as c:
        cref = L.register_contact(c, subject("atomic"), "sms", "501-555-0199")
    before = q(rt.engine, "SELECT count(*) FROM mbos.receipts")[0][0]

    def boom(*a, **k):
        raise RuntimeError("injected fault after the receipt, before the ledger row")

    with pytest.raises(RuntimeError):
        with rt.engine.begin() as c:
            L.record_consent(c, cref, "written_opt_in", "https://example.invalid/optin")
            boom()
    assert q(rt.engine, "SELECT count(*) FROM mbos.receipts")[0][0] == before
    assert q(rt.engine, "SELECT count(*) FROM mbos_comms.consent_events WHERE contact_ref = :c", c=cref)[0][0] == 0


def test_lookups_fail_closed_and_follow_latest_event(rt, ledger):
    ref = subject("lookup")
    assert ledger.consent_lookup(ref, "sms")["result"] == "not_found"
    assert ledger.dnc_lookup(ref, "sms") == (None, None, False)
    with rt.engine.begin() as c:
        cref = L.register_contact(c, ref, "sms", RAW_PHONE)
    assert ledger.consent_lookup(ref, "sms")["result"] == "not_found"
    with rt.engine.begin() as c:
        L.record_consent(c, cref, "inbound_inquiry", "https://example.invalid/form/9", at=NOON_AR - timedelta(days=1))
        L.record_dnc_scrub(c, cref, listed=False, at=NOON_AR - timedelta(days=2))
    assert ledger.consent_lookup(ref, "sms")["result"] == "pass"
    scrubbed_at, listed, suppressed = ledger.dnc_lookup(ref, "sms")
    assert listed is False and suppressed is False
    assert cs.dnc_check(scrubbed_at, listed, suppressed, "sms", NOON_AR)["result"] == "clear"
    with rt.engine.begin() as c:
        assert L.handle_inbound(c, cref, "hello?") is None
        stop = L.handle_inbound(c, cref, " Stop. ")
    assert stop["type"] == "GRANT_REVOKED"
    assert ledger.consent_lookup(ref, "sms")["result"] == "fail"
    assert ledger.dnc_lookup(ref, "sms")[2] is True  # suppressed
    assert cs.dnc_check(*ledger.dnc_lookup(ref, "sms"), "sms", NOON_AR)["result"] == "suppressed"


def test_e4_stop_suppresses_within_60s_and_blocks_next_send(rt, discover, ledger):
    item_id = discover("FIX-TRAILER-1")["FIX-TRAILER-1"]
    _wait(rt, item_id, "AWAITING_APPROVAL")
    item = q(rt.engine, "SELECT body FROM mbos.items WHERE item_id = :i", i=item_id)[0][0]
    item["normalized"]["counterparty"]["contact_method"] = "phone"
    (pa,) = CommsActionPlanner().plan(item)
    ref = pa["comms"]["recipient"]["ref"]
    with rt.engine.begin() as c:
        cref = L.register_contact(c, ref, "sms", "501-555-0177")
        L.record_consent(c, cref, "listing_published_contact", ref, at=NOON_AR - timedelta(hours=1))
        L.record_dnc_scrub(c, cref, listed=False, at=NOON_AR - timedelta(days=1))
    stop_at = datetime.now(timezone.utc)
    with rt.engine.begin() as c:
        L.handle_inbound(c, cref, "STOP")
    (suppressed_at,) = q(rt.engine, "SELECT recorded_at FROM mbos_comms.consent_events WHERE contact_ref = :c "
                                    "AND event = 'revoked'", c=cref)[0]
    areq = q(rt.engine, "SELECT body FROM mbos.action_requests WHERE item_id = :i", i=item_id)[0][0]
    areq = dict(areq, capability=pa["capability"], idempotency_key="t-after-stop",
                payload={**areq["payload"], "comms": pa["comms"]})
    eff = CommsDryRunEffector(clock=lambda: NOON_AR, consent_lookup=ledger.consent_lookup, dnc_lookup=ledger.dnc_lookup)
    r = eff.execute(rt.engine, areq)
    assert r["status"] == "blocked"
    sends_after = 0 if r["status"] == "blocked" else 1
    g = cs.audit([], stop_events=[{"stop_at": stop_at, "suppressed_at": suppressed_at, "sends_after": sends_after}])
    assert g["E4"]["status"] == "PASS"


def test_e2_graded_pass_on_a_spine_run(rt, discover, ledger, monkeypatch):
    """With the ledger wired, E2 is graded PASS (not DRY_RUN_EXEMPT); without a consent record the send blocks."""
    comps = components()
    eff = CommsDryRunEffector(clock=lambda: NOON_AR, consent_lookup=ledger.consent_lookup,
                              dnc_lookup=ledger.dnc_lookup, fallback=DryRunEffector())
    monkeypatch.setattr(comps, "planner", CommsActionPlanner())
    monkeypatch.setattr(comps, "gateway", ReferenceGateway(eff, comps.kill_switch))

    def run(with_consent: bool):
        item_id = discover("FIX-TRAILER-1")["FIX-TRAILER-1"]
        _wait(rt, item_id, "AWAITING_APPROVAL")
        areq = q(rt.engine, "SELECT body FROM mbos.action_requests WHERE item_id = :i AND status = 'pending_approval'",
                 i=item_id)[0][0]
        ref = areq["payload"]["comms"]["recipient"]["ref"]
        with rt.engine.begin() as c:
            cref = L.register_contact(c, ref, "email", f"seller-{item_id[-6:]}@example.invalid")
            if with_consent:
                L.record_consent(c, cref, "listing_published_contact", ref)
        workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"], auth_context=STEP_UP)
        _wait(rt, item_id, "ACTED" if with_consent else "FAILED")
        return [r[0] for r in q(rt.engine, "SELECT body FROM mbos.receipts WHERE action_request_id = :a ORDER BY seq",
                                a=areq["action_request_id"])]

    ok = cs.audit(run(with_consent=True))
    assert ok["sends"] == 1 and ok["E2"]["status"] == "PASS" and ok["E2"]["ratio"] == 1.0
    assert ok["E1"]["status"] == ok["E3"]["status"] == ok["E6"]["status"] == ok["E7"]["status"] == "PASS"
    no = run(with_consent=False)
    failed = [r for r in no if r["type"] == "ACTION_FAILED"]
    assert failed and any("consent" in x for x in failed[0]["details"]["blocked_reasons"])
    assert cs.audit(no)["sends"] == 0


def test_e2_fail_when_a_live_style_send_lacks_recorded_checks():
    r = {"type": "ACTION_EXECUTED", "receipt_id": "rcpt_x", "approval_id": "appr_x",
         "details": {"kind": "comms", "channel": "email", "first_message": True, "disclosure_present": True,
                     "consent_check": {"result": "not_evaluated"}, "dnc_check": {"result": "not_applicable"},
                     "send_window_check": {"ok": True}},
         "effector_response": {"status": "sent", "provider_msg_id": "m1", "dry_run": False}}
    assert cs.audit([r])["E2"]["status"] == "FAIL"


def _wait(rt, item_id, state, timeout=30.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if q(rt.engine, "SELECT state FROM mbos.items WHERE item_id = :i", i=item_id)[0][0] == state:
            return
        time.sleep(0.1)
    raise AssertionError(f"{item_id} never reached {state}")
