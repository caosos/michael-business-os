"""Operator UI on the spine (coordinator ruling R10). Every test drives the real HTTP server,
which calls mbos.spine.decide; execution happens only in the DBOS item workflow.

Run: .venv/bin/python -m pytest -q tests
"""

from __future__ import annotations

import http.client
import json
import re
import time
from pathlib import Path
from urllib.parse import unquote, urlencode

import sqlalchemy as sa

from mbos.clock import parse, utcnow
from mbos.hashing import sha256_of
from tests.conftest import PIN

PKG = Path(__file__).resolve().parent.parent / "operator_ui"


# ---------------------------------------------------------------- helpers
def req(ui, method, path, form=None, host=None):
    c = http.client.HTTPConnection("127.0.0.1", ui.port, timeout=15)
    body = urlencode(form) if form else None
    hdr = {"Host": host or f"127.0.0.1:{ui.port}"}
    if body:
        hdr["Content-Type"] = "application/x-www-form-urlencoded"
    c.request(method, path, body=body, headers=hdr)
    r = c.getresponse()
    return r.status, unquote(r.getheader("Location") or ""), r.read().decode()


def q(engine, sql, **p):
    with engine.connect() as c:
        return c.execute(sa.text(sql), p).all()


def wait(fn, timeout=30.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        v = fn()
        if v:
            return v
        time.sleep(0.1)
    raise AssertionError("condition not reached")


def item_state(engine, item_id):
    return q(engine, "SELECT state FROM mbos.items WHERE item_id = :i", i=item_id)[0][0]


def wait_state(engine, item_id, state):
    return wait(lambda: item_state(engine, item_id) == state)


def open_request(engine, item_id):
    rows = q(engine, "SELECT body FROM mbos.action_requests WHERE item_id = :i AND status IN ('pending_approval','held') "
                     "ORDER BY body->>'created_at' DESC LIMIT 1", i=item_id)
    return rows[0][0] if rows else None


def ready(rt, discover, listing="FIX-TRAILER-1"):
    item_id = discover(listing)[listing]
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    return item_id, open_request(rt.engine, item_id)


def post(ui, areq, decision, **f):
    form = {"csrf": ui.csrf, "decision": decision, "payload_hash_seen": areq["payload_hash"], **f}
    return req(ui, "POST", f"/areq/{areq['action_request_id']}/decide", form)


def approvals(engine, areq_id):
    return [r[0] for r in q(engine, "SELECT body FROM mbos.approvals WHERE action_request_id = :a ORDER BY seq", a=areq_id)]


def effector_calls(engine, areq_id):
    return q(engine, "SELECT request FROM mbos.effector_calls WHERE action_request_id = :a", a=areq_id)


# ---------------------------------------------------------------- R10 structure
def test_ui_owns_no_gateway_timer_or_ledger():
    """R10: the UI dropped DryRunGateway, tick() and its SQLite store; it only calls spine.decide."""
    src = "\n".join(p.read_text() for p in PKG.glob("*.py"))
    for banned in ("sqlite3", "DryRunGateway", "def tick", "Effector", "append_receipt", "INSERT INTO", "UPDATE mbos"):
        assert banned not in src, banned
    assert "spine.decide(" in (PKG / "backend.py").read_text()
    assert {p.name for p in PKG.glob("*.py")} == {"__init__.py", "__main__.py", "backend.py", "mbos_canonical.py",
                                               "server.py", "sources.py", "ux.py", "views.py", "digest.py", "summary.py", "card_view.py", "mission_view.py", "merch.py", "merch_view.py", "usage_view.py", "intake_view.py", "numbers_view.py", "wanted_view.py", "comps_view.py", "attest_view.py", "inputs_view.py", "assets_view.py", "bought_view.py", "glance_view.py", "resale_view.py"}


# ---------------------------------------------------------------- cards
def test_queue_and_card_show_why(rt, discover, ui):
    flip, areq = ready(rt, discover, "FIX-TRAILER-1")
    svc = discover("FIX-LEAD-SMARTHOME-1")["FIX-LEAD-SMARTHOME-1"]
    wait_state(rt.engine, svc, "AWAITING_APPROVAL")
    s, _, body = req(ui, "GET", "/")
    assert s == 200
    for text in ("FLIP", "SERVICE", "System says YES", "Needs your decision", "DRY-RUN"):
        assert text in body
    s, _, body = req(ui, "GET", f"/areq/{areq['action_request_id']}")
    for text in ("Why the system recommends this", "Economics", "Confidence &amp; risk", "Provenance",
                 "external source", "deterministic tool", areq["payload_hash"], "Step-up PIN",
                 ">YES<", ">NO<", ">MODIFY<", ">HOLD<", "irreversible", "ACTION_PROPOSED", "APPROVAL_REQUESTED"):
        assert text in body, text
    assert "MISSING" not in body  # every provenance id on the card resolves in mbos.provenance
    api = json.loads(req(ui, "GET", f"/api/areq/{areq['action_request_id']}.json")[2])
    assert api["lane"] == "flip" and api["areq"]["payload_hash"] == areq["payload_hash"]


# ---------------------------------------------------------------- YES
def test_yes_goes_through_spine_and_workflow_executes_frozen_payload(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    _, loc, _ = post(ui, areq, "YES")  # no PIN: refused before the spine
    assert "err=" in loc and "PIN" in loc
    assert approvals(rt.engine, areq["action_request_id"]) == []
    _, loc, _ = post(ui, areq, "YES", pin="0000")
    assert "err=" in loc and approvals(rt.engine, areq["action_request_id"]) == []
    _, loc, _ = post(ui, areq, "YES", pin=PIN)
    assert "msg=YES recorded" in loc
    (appr,) = approvals(rt.engine, areq["action_request_id"])
    assert (appr["channel"], appr["decision"], appr["payload_hash_seen"]) == ("web", "YES", areq["payload_hash"])
    assert appr["auth_context"]["step_up"] is True and appr["auth_context"]["method"] == "local_pin"
    wait_state(rt.engine, item_id, "ACTED")
    ((request,),) = effector_calls(rt.engine, areq["action_request_id"])
    assert request == areq["payload"] and sha256_of(request) == areq["payload_hash"]
    executed = [r[0] for r in q(rt.engine, "SELECT body FROM mbos.receipts WHERE action_request_id = :a "
                                           "AND type = 'ACTION_EXECUTED'", a=areq["action_request_id"])]
    assert len(executed) == 1 and executed[0]["effector_response"]["dry_run"] is True
    _, loc, _ = post(ui, areq, "YES", pin=PIN)  # double submit
    assert "err=" in loc and len(effector_calls(rt.engine, areq["action_request_id"])) == 1


def test_stale_hash_is_refused_by_the_spine(rt, discover, ui):
    _, areq = ready(rt, discover)
    _, loc, _ = req(ui, "POST", f"/areq/{areq['action_request_id']}/decide",
                    {"csrf": ui.csrf, "decision": "HOLD", "payload_hash_seen": "sha256:" + "0" * 64})
    assert "err=payload_hash_seen does not match" in loc
    assert approvals(rt.engine, areq["action_request_id"]) == []


# ---------------------------------------------------------------- NO
def test_no_requires_reason_and_archives(rt, discover, ui):
    item_id, areq = ready(rt, discover, "FIX-LEAD-SMARTHOME-1")
    _, loc, _ = post(ui, areq, "NO", reason="  ")
    assert "err=NO requires a reason" in loc
    _, loc, _ = post(ui, areq, "NO", reason="outside service area")
    assert "msg=NO recorded" in loc
    wait_state(rt.engine, item_id, "ARCHIVED")
    assert approvals(rt.engine, areq["action_request_id"])[0]["reason"] == "outside service area"
    assert effector_calls(rt.engine, areq["action_request_id"]) == []


# ---------------------------------------------------------------- MODIFY
def test_modify_creates_new_request_needing_its_own_yes(rt, discover, ui):
    item_id, old = ready(rt, discover)
    edited = dict(old["payload"], summary="Offer $700 cash, pickup Saturday (DRY-RUN draft)")
    s, loc, _ = post(ui, old, "MODIFY", new_payload=json.dumps(edited), note="start lower")
    new_id = re.search(r"/areq/(areq_\w+)\?msg=MODIFY recorded", loc).group(1)
    assert new_id != old["action_request_id"]
    new = wait(lambda: (lambda r: r if r and r["action_request_id"] == new_id and r["status"] == "pending_approval" else None)(
        open_request(rt.engine, item_id)))
    assert new["derived_from"] == old["action_request_id"] and new["payload"] == edited
    assert new["payload_hash"] == sha256_of(edited) != old["payload_hash"]
    status = q(rt.engine, "SELECT status FROM mbos.action_requests WHERE action_request_id = :a", a=old["action_request_id"])
    assert status[0][0] == "rejected"
    assert effector_calls(rt.engine, old["action_request_id"]) == [] and effector_calls(rt.engine, new_id) == []
    _, loc, _ = post(ui, old, "YES", pin=PIN)  # the superseded request is closed
    assert "err=" in loc
    _, loc, body = req(ui, "GET", f"/areq/{new_id}")
    assert f"Modified from <a href='/areq/{old['action_request_id']}'" in body
    _, loc, _ = post(ui, new, "YES", pin=PIN)
    wait_state(rt.engine, item_id, "ACTED")
    assert effector_calls(rt.engine, new_id)[0][0] == edited


def test_modify_rejects_bad_json_and_removed_fields(rt, discover, ui):
    _, areq = ready(rt, discover)
    _, loc, _ = post(ui, areq, "MODIFY", new_payload="{not json")
    assert "err=edited payload is not valid JSON" in loc
    _, loc, _ = post(ui, areq, "MODIFY", new_payload=json.dumps({"summary": "only this"}))
    assert "err=MODIFY cannot remove payload fields" in loc
    assert approvals(rt.engine, areq["action_request_id"]) == []


# ---------------------------------------------------------------- HOLD
def test_hold_preset_is_recorded_and_wake_now_re_presents_without_executing(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    _, loc, _ = post(ui, areq, "HOLD", hold_preset="3d", reason="waiting for photos")
    assert "msg=HOLD recorded" in loc
    (appr,) = approvals(rt.engine, areq["action_request_id"])
    hold = appr["hold"]
    assert abs((parse(hold["hold_until"]) - utcnow()).total_seconds() - 72 * 3600) < 120
    assert "michael_ping" in hold["wake_on"] and hold["renotify_after"] == "PT24H"
    wait_state(rt.engine, item_id, "HELD")
    _, _, body = req(ui, "GET", f"/areq/{areq['action_request_id']}")
    assert "On HOLD" in body and "Wake now" in body
    _, loc, _ = req(ui, "POST", f"/areq/{areq['action_request_id']}/wake", {"csrf": ui.csrf})
    assert "msg=Wake sent" in loc
    wait_state(rt.engine, item_id, "AWAITING_APPROVAL")
    assert open_request(rt.engine, item_id)["status"] == "pending_approval"
    assert effector_calls(rt.engine, areq["action_request_id"]) == []


def test_hold_tomorrow_8am_and_custom_time(rt, discover, ui):
    from operator_ui.ux import hold_for

    from mbos.clock import parse as p
    from datetime import datetime, timezone

    assert hold_for("tomorrow_8am", datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc))["hold_until"] == "2026-10-08T13:00:00Z"
    _, areq = ready(rt, discover)
    _, loc, _ = post(ui, areq, "HOLD", hold_preset="24h", hold_until="2020-01-01T09:00")
    assert "err=hold_until must be in the future" in loc
    _, loc, _ = post(ui, areq, "HOLD", hold_preset="24h", hold_until="2099-01-02T09:30")
    assert "msg=HOLD recorded" in loc
    assert p(approvals(rt.engine, areq["action_request_id"])[0]["hold"]["hold_until"]).year == 2099


# ---------------------------------------------------------------- web safety
def test_csrf_host_and_escaping(rt, discover, ui):
    item_id, areq = ready(rt, discover)
    _, loc, _ = req(ui, "POST", f"/areq/{areq['action_request_id']}/decide",
                    {"decision": "HOLD", "payload_hash_seen": areq["payload_hash"]})
    assert "err=invalid form token" in loc and approvals(rt.engine, areq["action_request_id"]) == []
    assert req(ui, "GET", "/", host="evil.example")[0] == 403
    assert req(ui, "POST", f"/areq/{areq['action_request_id']}/decide",
               {"csrf": ui.csrf, "decision": "HOLD", "payload_hash_seen": areq["payload_hash"]}, host="evil.example")[0] == 403
    _, loc, _ = post(ui, areq, "MODIFY", new_payload=json.dumps(dict(areq["payload"], summary="<script>alert(1)</script>")))
    new_id = re.search(r"/areq/(areq_\w+)\?", loc).group(1)
    _, _, body = req(ui, "GET", f"/areq/{new_id}")
    assert "<script>alert(1)</script>" not in body and "&lt;script&gt;" in body


def test_ledger_page_uses_spine_verify_chain(rt, discover, ui):
    ready(rt, discover)
    s, _, body = req(ui, "GET", "/ledger")
    assert s == 200 and "chain verified" in body


# ---------------------------------------------------------------- F-02: ADR-0010 conformance
CANON = PKG.parent / "docs/research/contracts/canonical"


def _isolated_reference():
    """Load operator_ui/mbos_canonical.py exactly as tools/interop_check.py does: by path, no package."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("lane06_canonical", PKG / "mbos_canonical.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_f02_vendored_reference_is_byte_identical():
    assert (PKG / "mbos_canonical.py").read_bytes() == (CANON / "mbos_canonical.py").read_bytes()


def test_f02_interop_row_06_is_10_of_10_and_rh1_chain_verifies():
    import pytest

    m = _isolated_reference()
    vec = json.loads((CANON / "vectors.json").read_text())
    ok = [c["name"] for c in vec["cjson"] if m.sha256_of(json.loads(c["input"])) == c["sha256"]]
    assert len(ok) == len(vec["cjson"]) == 10
    for c in vec["cjson"]:
        assert m.canonical_json(json.loads(c["input"])) == c["canonical"], c["name"]
    for c in vec["reject"]:
        with pytest.raises(Exception):
            m.canonical_json(json.loads(c["input"]))
    assert m.verify_chain(vec["receipt_chain"]) == (True, "2 receipts verified")
    assert m.sha256_of({"offer": 850.0}) == m.sha256_of({"offer": 850})  # the F-13 difference, now closed


def test_f02_card_verifies_payload_hash_and_hides_yes_on_mismatch(rt, discover, ui):
    from operator_ui import server, views

    _, areq = ready(rt, discover)
    _, _, body = req(ui, "GET", f"/areq/{areq['action_request_id']}")
    assert "verified (MBOS-CJSON-1)" in body and ">YES<" in body
    assert views.payload_hash_verified(areq) is True
    assert views.payload_hash_verified(dict(areq, payload=dict(areq["payload"], extra=1))) is False
    card = views.card(ui.store, areq["action_request_id"], utcnow())
    card["payload_hash_verified"] = False
    html = server.render_card(card, ui.csrf)
    assert ">YES<" not in html and "YES unavailable" in html and ">HOLD<" in html


def test_f02_ledger_independent_rh1_check_agrees_with_spine(rt, discover, ui):
    """The spine chain verifies under the vendored ADR-0010 reference: links, hashes and contiguity."""
    item_id, areq = ready(rt, discover)
    assert ui.store.verify_chain()["ok"] is True
    ok, msg = ui.store.verify_chain_independent()
    assert ok, msg  # strict since A-16 (c23bee8): no gaps, both verifiers agree
    from operator_ui import mbos_canonical
    from mbos.ledger import load_receipts

    with rt.engine.connect() as c:
        chain = load_receipts(c)
    prev = None
    for r in chain:  # hashes and links, ignoring seq continuity
        assert r["prev_hash"] == prev and mbos_canonical.receipt_row_hash(r) == r["row_hash"], r["seq"]
        prev = r["row_hash"]
    _, _, body = req(ui, "GET", "/ledger")
    assert "independent MBOS-RH-1 check (vendored reference): " in body


def test_regression_no_seq_gap_after_rollback_both_verifiers_agree(rt, ui):
    """Was FINDING (06 → 01, aa88e7a): nextval() seq left gaps after a rollback. Fixed in A-16 (c23bee8,
    migration 0005: seq = max+1 under the chain lock; verify_chain checks contiguity). Now a rolled-back
    receipt transaction leaves no gap, and the DB verifier and the ADR-0010 reference agree."""
    import pytest
    from mbos.ledger import append_receipt, tool_provenance

    with pytest.raises(RuntimeError):
        with rt.engine.begin() as c:
            prov = tool_provenance(c, "tests.regression.rollback")
            append_receipt(c, type="ITEM_STATE_CHANGED", intent="rolled back on purpose", provenance_ids=[prov],
                           entity_type="test", entity_id="rollback", effect="none")
            raise RuntimeError("rollback")
    with rt.engine.begin() as c:
        prov = tool_provenance(c, "tests.regression.after")
        append_receipt(c, type="ITEM_STATE_CHANGED", intent="committed after the rollback", provenance_ids=[prov],
                       entity_type="test", entity_id="after", effect="none")
    assert ui.store.verify_chain()["ok"] is True
    ok, msg = ui.store.verify_chain_independent()
    assert ok is True, msg
    _, _, body = req(ui, "GET", "/ledger")
    assert "FAILED" not in body.split("independent MBOS-RH-1 check")[1].split("</span>")[0]


def test_yes_on_a_held_request_re_presents_then_executes(rt, discover, ui):
    """R12 (bf215b2): a YES on a HELD item re-presents it first (HELD → AWAITING_APPROVAL → APPROVED);
    the HOLD itself never executes."""
    item_id, areq = ready(rt, discover)
    post(ui, areq, "HOLD", hold_preset="24h")
    wait_state(rt.engine, item_id, "HELD")
    assert effector_calls(rt.engine, areq["action_request_id"]) == []
    _, loc, _ = post(ui, areq, "YES", pin=PIN)
    assert "msg=YES recorded" in loc
    wait_state(rt.engine, item_id, "ACTED")
    states = [r[0] for r in q(rt.engine, "SELECT body->'after_state'->>'state' FROM mbos.receipts WHERE item_id = :i "
                                         "AND type = 'ITEM_STATE_CHANGED' ORDER BY seq", i=item_id)]
    i = states.index("HELD")
    assert states[i + 1:i + 3] == ["AWAITING_APPROVAL", "APPROVED"]
    assert len(effector_calls(rt.engine, areq["action_request_id"])) == 1
