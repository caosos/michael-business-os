"""F-06: CommsDryRunEffector on the REAL spine (DBOS + pgserver Postgres; mbos @ bf215b2).

F-05's planner and F-06's effector are swapped into the running Components. `A13_shim` reproduces the
one seam Agent 01 is asked to add in A-13 (merge `payload_extension(pa)` into the payload before
hashing), so the approved payload carries the draft. Everything is dry-run.
"""

from __future__ import annotations

import copy
from datetime import datetime, timezone

import pytest
import sqlalchemy as sa

import comms_spec as cs
from comms_spec.effector import CommsDryRunEffector
from comms_spec.planner import CommsActionPlanner, payload_extension
from mbos import spine, workflows
from mbos.audit import dry_run_exceptions
from mbos.hashing import sha256_of
from mbos.interfaces import Effector
from mbos.reference.governance import DryRunEffector, ReferenceGateway
from mbos.runtime import components

STEP_UP = {"method": "test_step_up", "step_up": True}
NOON_AR = datetime(2026, 10, 7, 17, 0, tzinfo=timezone.utc)      # Wednesday 12:00 CDT
LATE_AR = datetime(2026, 10, 8, 2, 30, tzinfo=timezone.utc)      # Wednesday 21:30 CDT
SUNDAY_AR = datetime(2026, 10, 11, 17, 0, tzinfo=timezone.utc)


def q(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(sa.text(sql), p).all()


def wait_state(engine, item_id, state, timeout=30.0):
    import time

    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if q(engine, "SELECT state FROM mbos.items WHERE item_id = :i", i=item_id)[0][0] == state:
            return
        time.sleep(0.1)
    raise AssertionError(f"{item_id} never reached {state}")


def pending(engine, item_id):
    return q(engine, "SELECT body FROM mbos.action_requests WHERE item_id = :i AND status = 'pending_approval'", i=item_id)[0][0]


@pytest.fixture()
def comms_lane(rt, monkeypatch):
    """F-05 planner + F-06 effector behind the reference gateway, plus the A-13 payload shim."""
    comps = components()
    eff = CommsDryRunEffector(clock=lambda: NOON_AR, fallback=DryRunEffector())
    monkeypatch.setattr(comps, "planner", CommsActionPlanner())
    monkeypatch.setattr(comps, "gateway", ReferenceGateway(eff, comps.kill_switch))

    orig_propose, orig_insert = spine._propose, spine._insert_and_classify

    def A13_shim(conn, item, pa, prov, comps_):
        ext = payload_extension(pa)

        def insert(conn2, areq, prov2, comps2, actor):
            if ext:
                areq["payload"].update(ext)
                areq["payload_hash"] = sha256_of(areq["payload"])
            return orig_insert(conn2, areq, prov2, comps2, actor)

        spine._insert_and_classify = insert
        try:
            return orig_propose(conn, item, pa, prov, comps_)
        finally:
            spine._insert_and_classify = orig_insert

    monkeypatch.setattr(spine, "_propose", A13_shim)
    return eff


def test_is_an_mbos_effector():
    e = CommsDryRunEffector()
    assert isinstance(e, Effector) and e.dry_run is True


def test_spine_run_planner_to_effector_graded_e1_to_e7(rt, discover, comms_lane):
    item_id = discover("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending(rt.engine, item_id)
    c = areq["payload"]["comms"]
    assert areq["capability"] == "comms.email.send" and c["template_id"] == "seller_first_inquiry"
    assert sha256_of(areq["payload"]) == areq["payload_hash"]  # the draft is inside what Michael approves
    workflows.record_decision(areq["action_request_id"], "YES", areq["payload_hash"], auth_context=STEP_UP)
    wait_state(rt.engine, item_id, "ACTED")

    ((req, resp),) = q(rt.engine, "SELECT request, response FROM mbos.effector_calls WHERE action_request_id = :a",
                       a=areq["action_request_id"])
    assert req == areq["payload"]  # sent exactly the frozen payload
    assert resp["status"] == "simulated_send" and resp["dry_run"] is True and resp["comms"]["blocked_reasons"] == []
    assert resp["comms"]["template_conformant"] is True and resp["comms"]["disclosure_present"] is True
    assert resp["comms"]["dnc_check"]["result"] == "not_applicable"           # email
    assert resp["comms"]["consent_check"]["result"] == "not_evaluated"        # no ledger yet: honest

    receipts = [r[0] for r in q(rt.engine, "SELECT body FROM mbos.receipts WHERE action_request_id = :a ORDER BY seq",
                                a=areq["action_request_id"])]
    graded = cs.audit(receipts)
    assert graded["sends"] == 1 and graded["blocked"] == 0
    assert {k: graded[k]["status"] for k in ("E1", "E2", "E3", "E5", "E6", "E7")} == {
        "E1": "PASS", "E2": "DRY_RUN_EXEMPT", "E3": "PASS", "E5": "NOT_TESTABLE_IN_DRY_RUN", "E6": "PASS", "E7": "PASS"}
    with rt.engine.connect() as conn:
        a7 = dry_run_exceptions(conn)
    assert a7["ok"] is True and a7["receipt_exceptions"] == [] and a7["call_exceptions"] == []


def _proposed(rt, discover, contact_method=None):
    """A real pending areq, plus (optionally) a re-planned comms payload for another contact method."""
    item_id = discover("FIX-TRAILER-1")["FIX-TRAILER-1"]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    areq = pending(rt.engine, item_id)
    if contact_method:
        item = q(rt.engine, "SELECT body FROM mbos.items WHERE item_id = :i", i=item_id)[0][0]
        item["normalized"]["counterparty"]["contact_method"] = contact_method
        (pa,) = CommsActionPlanner().plan(item)
        areq = copy.deepcopy(areq)
        areq["capability"] = pa["capability"]
        areq["payload"] = {**areq["payload"], **payload_extension(pa)}
    return areq


def test_exactly_once_replays_without_re_evaluating(rt, discover, comms_lane):
    areq = _proposed(rt, discover)
    first = comms_lane.execute(rt.engine, areq)
    later = CommsDryRunEffector(clock=lambda: LATE_AR)  # would block if it re-evaluated
    again = later.execute(rt.engine, areq)
    assert again == first and first["status"] == "simulated_send"
    n = q(rt.engine, "SELECT count(*) FROM mbos.effector_calls WHERE idempotency_key = :k", k=areq["idempotency_key"])[0][0]
    assert n == 1


@pytest.mark.parametrize("clock,reason", [(LATE_AR, "send window"), (SUNDAY_AR, "no outbound on Sunday")])
def test_outside_window_blocks(rt, discover, comms_lane, clock, reason):
    areq = dict(_proposed(rt, discover), idempotency_key=f"t-window-{clock.isoformat()}")
    r = CommsDryRunEffector(clock=lambda: clock).execute(rt.engine, areq)
    assert r["status"] == "blocked" and r["provider_msg_id"].startswith("blocked_") and r["dry_run"] is True
    assert any(reason in x for x in r["comms"]["blocked_reasons"])


def test_sms_fails_closed_without_dnc_scrub_and_passes_with_one(rt, discover, comms_lane):
    areq = _proposed(rt, discover, contact_method="phone")
    assert areq["capability"] == "comms.sms.send"
    r = CommsDryRunEffector(clock=lambda: NOON_AR).execute(rt.engine, dict(areq, idempotency_key="t-sms-nodnc"))
    assert r["status"] == "blocked" and r["comms"]["dnc_check"]["result"] == "unknown"
    scrubbed = lambda ref, ch: (NOON_AR.replace(day=1), False, False)  # noqa: E731 — scrubbed 6 days ago, not listed
    r = CommsDryRunEffector(clock=lambda: NOON_AR, dnc_lookup=scrubbed).execute(rt.engine, dict(areq, idempotency_key="t-sms-dnc"))
    assert r["status"] == "simulated_send" and r["comms"]["dnc_check"]["result"] == "clear"
    listed = lambda ref, ch: (NOON_AR.replace(day=1), True, False)  # noqa: E731
    r = CommsDryRunEffector(clock=lambda: NOON_AR, dnc_lookup=listed).execute(rt.engine, dict(areq, idempotency_key="t-sms-listed"))
    assert r["status"] == "blocked" and r["comms"]["dnc_check"]["result"] == "listed"


def test_rate_limit_blocks_second_cold_email_same_day(rt, discover, comms_lane):
    areq = _proposed(rt, discover)
    eff = CommsDryRunEffector(clock=lambda: NOON_AR)
    assert eff.execute(rt.engine, dict(areq, idempotency_key="t-rate-1"))["status"] == "simulated_send"
    r = eff.execute(rt.engine, dict(areq, idempotency_key="t-rate-2"))
    assert r["status"] == "blocked" and any("rate limit" in x for x in r["comms"]["blocked_reasons"])


def test_missing_draft_tampered_body_and_refused_consent_block(rt, discover, comms_lane):
    areq = _proposed(rt, discover)
    eff = CommsDryRunEffector(clock=lambda: NOON_AR)
    bare = dict(areq, payload={k: v for k, v in areq["payload"].items() if k != "comms"}, idempotency_key="t-nodraft")
    assert "no comms draft" in eff.execute(rt.engine, bare)["comms"]["blocked_reasons"][0]
    tampered = copy.deepcopy(areq)
    tampered["payload"]["comms"]["body"] = tampered["payload"]["comms"]["body"].replace(cs.load("templates")["disclosure"], "")
    r = eff.execute(rt.engine, dict(tampered, idempotency_key="t-nodisclosure"))
    assert r["status"] == "blocked" and r["comms"]["disclosure_present"] is False and r["comms"]["template_conformant"] is False
    refused = CommsDryRunEffector(clock=lambda: NOON_AR, consent_lookup=lambda ref, ch: {"result": "fail", "reason": "opted out"})
    r = refused.execute(rt.engine, dict(_proposed(rt, discover), idempotency_key="t-consent"))
    assert r["status"] == "blocked" and any("consent" in x for x in r["comms"]["blocked_reasons"])


def test_blocked_attempts_are_not_counted_as_sends_by_audit():
    blocked = {"type": "ACTION_EXECUTED", "receipt_id": "rcpt_b", "approval_id": "appr_b", "details": {"kind": "comms"},
               "effector_response": {"status": "blocked", "dry_run": True, "provider_msg_id": "blocked_x",
                                     "comms": {"kind": "comms", "channel": "sms", "first_message": True,
                                               "disclosure_present": False, "send_window_check": {"ok": False}}}}
    g = cs.audit([blocked])
    assert g["sends"] == 0 and g["blocked"] == 1 and g["E1"]["status"] == "NO_DATA" and g["E3"]["status"] == "PASS"


def test_non_comms_capability_uses_fallback(rt, discover, comms_lane):
    areq = dict(_proposed(rt, discover), capability="schedule.appointment.create", idempotency_key="t-fallback")
    r = CommsDryRunEffector(fallback=DryRunEffector()).execute(rt.engine, areq)
    assert r["provider"] == "dry-run:schedule.appointment.create" and r["dry_run"] is True
    with pytest.raises(ValueError):
        CommsDryRunEffector().execute(rt.engine, dict(areq, idempotency_key="t-nofallback"))
