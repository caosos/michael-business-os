"""Operator UI acceptance tests (stdlib unittest).

Maps to the integration doc §8: A1, A2, A3, A4, A5, A6, A7, A9, A10 — as far as
the approval surface is concerned — plus the UI rules in the round-two brief.
Run: python3 -I -m unittest discover -s tests -t .
"""

import http.client
import json
import os
import pathlib
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from operator_ui.approvals import ApprovalService, DecisionError, StaleView, StepUpRequired  # noqa: E402
from operator_ui.contracts import CONTRACTS_DIR, SUPPORTED, ContractValidator  # noqa: E402
from operator_ui.effectors import DryRunEffector, LiveEffectorForbidden  # noqa: E402
from operator_ui.gateway import DryRunGateway  # noqa: E402
from operator_ui.seed import seed  # noqa: E402
from operator_ui.server import App, make_handler  # noqa: E402
from operator_ui.store import Store  # noqa: E402
from operator_ui.util import Clock, sha256_of  # noqa: E402

T0 = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)
PIN = "4321"
TRAILER, DRYWALL, GENERATOR = (f"areq_01JA{n:022d}" for n in (1, 2, 3))


class Crash(BaseException):
    """Simulates the process dying (not an ordinary, receipted failure)."""


def rig(db=":memory:", pin=PIN, do_seed=True):
    clock = Clock(T0)
    store = Store(db)
    svc = ApprovalService(store, clock, operator_pin=pin)
    eff = DryRunEffector(store)
    svc.gateway = DryRunGateway(store, clock, eff, svc)
    if do_seed:
        seed(store, clock.now())
    return store, svc, eff, clock


def h(store, areq_id):
    return store.action_request(areq_id)["payload_hash"]


def count(store, table):
    return store.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


class Contracts(unittest.TestCase):
    def test_examples_and_negative_invariants(self):
        v = ContractValidator()
        kinds = {"item-": "item", "action-request-": "action_request", "approval-": "approval",
                 "receipt-": "receipt", "provenance-": "provenance", "outcome-": "outcome"}
        for ex in CONTRACTS_DIR.glob("examples/*.json"):
            kind = next(k for p, k in kinds.items() if ex.name.startswith(p))
            self.assertEqual(v.errors(kind, json.loads(ex.read_text())), [], ex.name)
        r = json.loads((CONTRACTS_DIR / "examples/receipt-approval-decided.example.json").read_text())
        r["provenance_ids"] = []
        self.assertTrue(v.errors("receipt", r), "receipt without provenance must fail")
        a = json.loads((CONTRACTS_DIR / "examples/action-request-email-held.example.json").read_text())
        a["tier"] = 1
        self.assertTrue(v.errors("action_request", a), "irreversible at tier 1 must fail")
        ap = json.loads((CONTRACTS_DIR / "examples/approval-hold.example.json").read_text())
        ap["decision"] = "NO"
        self.assertTrue(v.errors("approval", ap), "NO without reason must fail")

    def test_fallback_validator_covers_every_keyword_in_frozen_schemas(self):
        used = set()

        def walk(s):
            if isinstance(s, dict):
                used.update(k for k in s if not k.startswith("x-"))
                for k, sub in s.items():
                    if k in ("properties", "$defs"):
                        for v in sub.values():
                            walk(v)
                    elif k in ("items", "if", "then", "else", "not", "additionalProperties"):
                        walk(sub)
                    elif k in ("allOf", "anyOf", "oneOf"):
                        for v in sub:
                            walk(v)
        for p in list(CONTRACTS_DIR.glob("*.schema.json")) + list(CONTRACTS_DIR.glob("vendor/agent-03/*.schema.json")):
            walk(json.loads(p.read_text()))
        self.assertEqual(used - SUPPORTED, set())


class Yes(unittest.TestCase):
    def test_yes_executes_frozen_payload_dry_run_only(self):
        store, svc, eff, _ = rig()
        frozen = store.action_request(TRAILER)["payload"]
        r = svc.yes(TRAILER, h(store, TRAILER), pin=PIN)
        self.assertEqual(r["execution"]["status"], "executed")
        self.assertEqual(eff.calls, 1)
        out = json.loads(store.db.execute("SELECT response FROM dryrun_outbox").fetchone()[0])
        self.assertTrue(out["dry_run"])
        a = store.action_request(TRAILER)
        self.assertEqual((a["status"], a["payload"]), ("executed", frozen))
        self.assertEqual(store.item(a["item_id"])["state"], "ACTED")
        types = [x["type"] for x in store.receipts(areq_id=TRAILER)]
        for t in ("ACTION_PROPOSED", "APPROVAL_REQUESTED", "APPROVAL_DECIDED", "ACTION_EXECUTING", "ACTION_EXECUTED"):
            self.assertIn(t, types)
        ex = store.receipts(areq_id=TRAILER, rtype="ACTION_EXECUTED")[0]
        self.assertEqual(ex["payload_hash"], sha256_of(frozen))
        self.assertEqual(ex["details"]["kind"], "comms")
        appr = store.approvals_for(TRAILER)[0]
        self.assertEqual((appr["decision"], appr["payload_hash_seen"]), ("YES", sha256_of(frozen)))
        self.assertTrue(appr["auth_context"]["step_up"])

    def test_stale_hash_refused_and_nothing_written(self):
        store, svc, eff, _ = rig()
        before = count(store, "receipts")
        with self.assertRaises(StaleView):
            svc.yes(GENERATOR, "sha256:" + "0" * 64)
        self.assertEqual(count(store, "receipts"), before)
        self.assertEqual(count(store, "approvals"), 0)
        self.assertEqual(eff.calls, 0)

    def test_tampered_stored_payload_never_executes(self):
        store, svc, eff, _ = rig()
        doc = store.action_request(GENERATOR)
        doc["payload"]["notify_counterparty"] = True  # hash left unchanged
        store.db.execute("UPDATE action_requests SET doc=? WHERE action_request_id=?", (json.dumps(doc), GENERATOR))
        with self.assertRaises(StaleView):
            svc.yes(GENERATOR, doc["payload_hash"])
        self.assertEqual(eff.calls, 0)

    def test_tamper_after_approval_denied_by_guard(self):
        store, svc, eff, _ = rig()
        svc.yes(GENERATOR, h(store, GENERATOR), execute=False)
        doc = store.action_request(GENERATOR)
        doc["payload"]["title"] = "something else"
        store.db.execute("UPDATE action_requests SET doc=? WHERE action_request_id=?", (json.dumps(doc), GENERATOR))
        appr = store.approvals_for(GENERATOR)[0]
        r = svc.gateway.execute(GENERATOR, appr["approval_id"])
        self.assertEqual((r["status"], r["check"]), ("denied", "payload_hash_match"))
        self.assertEqual(eff.calls, 0)

    def test_step_up_required_for_irreversible(self):
        store, svc, eff, _ = rig()
        with self.assertRaises(StepUpRequired):
            svc.yes(TRAILER, h(store, TRAILER))
        with self.assertRaises(StepUpRequired):
            svc.yes(TRAILER, h(store, TRAILER), pin="0000")
        store2, svc2, *_ = rig(pin=None)
        with self.assertRaises(StepUpRequired):  # no PIN configured => fail closed
            svc2.yes(TRAILER, h(store2, TRAILER), pin="anything")
        self.assertEqual(svc.yes(GENERATOR, h(store, GENERATOR))["execution"]["status"], "executed")  # reversible

    def test_double_yes_cannot_execute_twice(self):
        store, svc, eff, _ = rig()
        hh = h(store, GENERATOR)
        svc.yes(GENERATOR, hh)
        with self.assertRaises(DecisionError):
            svc.yes(GENERATOR, hh)
        self.assertEqual(eff.calls, 1)


class No(unittest.TestCase):
    def test_no_requires_reason_and_archives(self):
        store, svc, *_ = rig()
        with self.assertRaises(DecisionError):
            svc.no(DRYWALL, h(store, DRYWALL), "  ")
        svc.no(DRYWALL, h(store, DRYWALL), "too far for a small patch")
        a = store.action_request(DRYWALL)
        self.assertEqual(a["status"], "rejected")
        self.assertEqual(store.item(a["item_id"])["state"], "ARCHIVED")
        self.assertEqual(store.approvals_for(DRYWALL)[0]["reason"], "too far for a small patch")

    def test_no_without_archive_marks_rejected(self):
        store, svc, *_ = rig()
        svc.no(DRYWALL, h(store, DRYWALL), "not now", archive=False)
        self.assertEqual(store.item(store.action_request(DRYWALL)["item_id"])["state"], "REJECTED")


class Modify(unittest.TestCase):
    def test_modify_creates_new_request_and_never_mutates(self):
        store, svc, eff, _ = rig()
        old = store.action_request(TRAILER)
        newp = dict(old["payload"], offer=950)
        r = svc.modify(TRAILER, old["payload_hash"], newp, note="start lower")
        nid = r["new_action_request_id"]
        self.assertEqual(store.action_request(TRAILER)["payload"], old["payload"])  # untouched
        self.assertEqual(store.action_request(TRAILER)["status"], "rejected")
        new = store.action_request(nid)
        self.assertEqual((new["derived_from"], new["status"], new["payload"]["offer"]), (TRAILER, "pending_approval", 950))
        self.assertNotEqual(new["payload_hash"], old["payload_hash"])
        self.assertNotEqual(new["idempotency_key"], old["idempotency_key"])
        self.assertEqual(new["tier"], 0)
        mods = store.approvals_for(TRAILER)[0]["modifications"]
        self.assertEqual((mods["new_action_request_id"], mods["diff"]["offer"]), (nid, {"from": 1050, "to": 950}))
        self.assertEqual(eff.calls, 0, "MODIFY is not approval")
        with self.assertRaises(DecisionError):  # the superseded request is closed
            svc.yes(TRAILER, old["payload_hash"], pin=PIN)
        svc.yes(nid, new["payload_hash"], pin=PIN)
        ex = store.receipts(areq_id=nid, rtype="ACTION_EXECUTED")[0]
        self.assertEqual(ex["payload_hash"], sha256_of(newp))

    def test_modify_requires_a_change(self):
        store, svc, *_ = rig()
        with self.assertRaises(DecisionError):
            svc.modify(TRAILER, h(store, TRAILER), store.action_request(TRAILER)["payload"])


class Hold(unittest.TestCase):
    def test_hold_is_durable_reminds_wakes_and_never_executes(self):
        with tempfile.TemporaryDirectory() as d:
            db = os.path.join(d, "ui.sqlite3")
            store, svc, eff, clock = rig(db)
            svc.hold(GENERATOR, h(store, GENERATOR), preset="new_info", reason="waiting on seller photos")
            store.db.close()
            # restart: new process, same DB
            store, svc, eff, clock = rig(db, do_seed=False)
            self.assertEqual(store.action_request(GENERATOR)["status"], "held")
            # generator request expires after 30h; reminders at 24h, never executes
            clock.advance(timedelta(hours=24, minutes=1))
            self.assertEqual(svc.tick(), [("renotified", GENERATOR)])
            self.assertEqual(store.action_request(GENERATOR)["status"], "held")
            self.assertFalse(svc.wake(GENERATOR, "time"), "time is not in this preset's wake_on")
            self.assertTrue(svc.wake(GENERATOR, "price_change"))
            self.assertEqual(store.action_request(GENERATOR)["status"], "pending_approval")
            self.assertEqual(store.receipts(rtype="ACTION_EXECUTING"), [])
            self.assertEqual(eff.calls, 0)

    def test_time_hold_re_presents_and_needs_a_fresh_yes(self):
        store, svc, eff, clock = rig()
        svc.hold(DRYWALL, h(store, DRYWALL), preset="24h")
        self.assertEqual(store.item(store.action_request(DRYWALL)["item_id"])["state"], "HELD")
        clock.advance(timedelta(hours=23))
        self.assertEqual(svc.tick(), [])
        clock.advance(timedelta(hours=2))
        self.assertEqual(svc.tick(), [("hold_until reached", DRYWALL)])
        self.assertEqual(store.action_request(DRYWALL)["status"], "pending_approval")
        self.assertEqual(eff.calls, 0)
        self.assertEqual(store.receipts(rtype="ACTION_EXECUTED"), [])

    def test_escalation_re_presents_not_executes(self):
        store, svc, eff, clock = rig()
        doc = store.action_request(DRYWALL)  # give it a long deadline so escalation (72h) comes first
        doc["expires_at"] = "2026-10-20T00:00:00Z"
        store.db.execute("UPDATE action_requests SET doc=? WHERE action_request_id=?", (json.dumps(doc), DRYWALL))
        svc.hold(DRYWALL, h(store, DRYWALL), preset="new_info")
        clock.advance(timedelta(hours=71, minutes=59))
        svc.tick()
        self.assertEqual(store.action_request(DRYWALL)["status"], "held")
        clock.advance(timedelta(minutes=2))
        self.assertEqual(svc.tick(), [("escalated", DRYWALL)])
        self.assertEqual(store.action_request(DRYWALL)["status"], "pending_approval")
        self.assertEqual(eff.calls, 0)

    def test_hold_until_expiry_expires_never_executes(self):
        store, svc, eff, clock = rig()
        svc.hold(DRYWALL, h(store, DRYWALL), preset="new_info")  # request deadline is 72h
        clock.advance(timedelta(hours=72, minutes=1))
        self.assertIn(("expired", DRYWALL), svc.tick())
        self.assertEqual(store.action_request(DRYWALL)["status"], "expired")
        self.assertEqual(store.item(store.action_request(DRYWALL)["item_id"])["state"], "ARCHIVED")
        self.assertEqual(eff.calls, 0)

    def test_custom_hold_until_and_tomorrow_preset(self):
        store, svc, *_ = rig()
        svc.hold(DRYWALL, h(store, DRYWALL), preset="tomorrow_8am")
        hold = store.approvals_for(DRYWALL)[0]["hold"]
        self.assertEqual(hold["hold_until"], "2026-10-08T13:00:00Z")  # 8am CDT
        with self.assertRaises(DecisionError):
            svc.hold(TRAILER, h(store, TRAILER), hold_until="2026-10-01T09:00")

    def test_expired_request_cannot_be_approved(self):
        store, svc, eff, clock = rig()
        clock.advance(timedelta(hours=31))
        self.assertIn(("expired", GENERATOR), svc.tick())
        with self.assertRaises(DecisionError):
            svc.yes(GENERATOR, h(store, GENERATOR))
        self.assertEqual(eff.calls, 0)


class Ledger(unittest.TestCase):
    def test_a1_decision_is_all_or_nothing(self):
        store, svc, *_ = rig()
        before = (count(store, "receipts"), count(store, "approvals"), count(store, "provenance"))
        from operator_ui import store as store_mod

        orig = store_mod.Tx.add_receipt

        def boom(self, now, **kw):
            if kw.get("type") == "ITEM_STATE_CHANGED":
                raise RuntimeError("injected fault between state change and receipt")
            return orig(self, now, **kw)

        store_mod.Tx.add_receipt = boom
        try:
            with self.assertRaises(RuntimeError):
                svc.no(DRYWALL, h(store, DRYWALL), "x")
        finally:
            store_mod.Tx.add_receipt = orig
        self.assertEqual((count(store, "receipts"), count(store, "approvals"), count(store, "provenance")), before)
        self.assertEqual(store.action_request(DRYWALL)["status"], "pending_approval")

    def test_a2_insert_only(self):
        store, svc, *_ = rig()
        svc.no(DRYWALL, h(store, DRYWALL), "x")
        for sql in ("UPDATE receipts SET doc='{}'", "DELETE FROM receipts", "UPDATE approvals SET doc='{}'",
                    "DELETE FROM provenance"):
            with self.assertRaises(sqlite3.DatabaseError, msg=sql):
                store.db.execute(sql)

    def test_a3_chain_verifies_and_detects_tamper(self):
        store, svc, *_ = rig()
        svc.yes(GENERATOR, h(store, GENERATOR))
        self.assertTrue(store.verify_chain()[0])
        store.db.execute("DROP TRIGGER receipts_no_update")
        store.db.execute("UPDATE receipts SET doc=replace(doc,'Michael','Mike') WHERE seq=(SELECT max(seq) FROM receipts WHERE doc LIKE '%Michael%')")
        self.assertFalse(store.verify_chain()[0])

    def test_a4_a10_every_row_conforms_and_provenance_resolves(self):
        store, svc, *_ = rig()
        svc.yes(GENERATOR, h(store, GENERATOR))
        r = svc.modify(TRAILER, h(store, TRAILER), dict(store.action_request(TRAILER)["payload"], offer=999))
        svc.hold(r["new_action_request_id"], h(store, r["new_action_request_id"]), preset="3d")
        svc.no(DRYWALL, h(store, DRYWALL), "x")
        v = store.validator
        for table, kind in (("items", "item"), ("action_requests", "action_request"), ("approvals", "approval"),
                            ("provenance", "provenance"), ("receipts", "receipt")):
            for (doc,) in store.db.execute(f"SELECT doc FROM {table}"):
                self.assertEqual(v.errors(kind, json.loads(doc)), [], table)
        for rc in store.receipts():
            for p in rc["provenance_ids"]:
                self.assertIsNotNone(store.provenance(p), f"{rc['receipt_id']} -> {p}")

    def test_a5_crash_mid_execute_resumes_without_duplicate(self):
        store, svc, eff, _ = rig()
        real = eff.execute

        def crash_after_send(areq, dry_run):
            real(areq, dry_run)
            raise Crash()

        eff.execute = crash_after_send
        with self.assertRaises(Crash):
            svc.yes(GENERATOR, h(store, GENERATOR))
        self.assertEqual(store.action_request(GENERATOR)["status"], "executing")
        eff.execute = real
        res = svc.gateway.resume()
        self.assertEqual(res[0]["status"], "executed")
        self.assertTrue(res[0]["replayed"])
        self.assertEqual(eff.calls, 1)
        self.assertEqual(len(store.receipts(areq_id=GENERATOR, rtype="ACTION_EXECUTED")), 1)

    def test_a7_effector_receipts_are_all_dry_run(self):
        store, svc, eff, _ = rig()
        svc.yes(GENERATOR, h(store, GENERATOR))
        svc.yes(TRAILER, h(store, TRAILER), pin=PIN)
        ex = [r for r in store.receipts() if r.get("effector_response")]
        self.assertTrue(ex)
        self.assertTrue(all(r["effector_response"]["dry_run"] is True for r in ex))
        with self.assertRaises(LiveEffectorForbidden):
            eff.execute(store.action_request(DRYWALL), dry_run=False)

    def test_a9_kill_switch_and_live_mode_fail_closed(self):
        for setup, check in ((lambda s: s.db.execute("UPDATE system SET value='FROZEN' WHERE key='system_state'"), "kill_switch_clear"),
                             (lambda s: s.db.execute("DELETE FROM system WHERE key='system_state'"), "kill_switch_clear"),
                             (lambda s: s.db.execute("UPDATE system SET value='live' WHERE key='system_mode'"), "dry_run_forced")):
            store, svc, eff, _ = rig()
            setup(store)
            r = svc.yes(GENERATOR, h(store, GENERATOR))
            self.assertEqual((r["execution"]["status"], r["execution"]["check"]), ("denied", check))
            self.assertEqual(eff.calls, 0)
            self.assertTrue(store.receipts(areq_id=GENERATOR, rtype="POLICY_DECIDED"))


class Web(unittest.TestCase):
    def setUp(self):
        from http.server import ThreadingHTTPServer

        self.store, self.svc, self.eff, self.clock = rig()
        self.app = App(self.store, self.svc, self.clock)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.port = self.httpd.server_address[1]

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def req(self, method, path, form=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port)
        body = urlencode(form) if form else None
        hdr = {"Host": host or f"127.0.0.1:{self.port}"}
        if body:
            hdr["Content-Type"] = "application/x-www-form-urlencoded"
        c.request(method, path, body=body, headers=hdr)
        r = c.getresponse()
        return r.status, r.getheader("Location"), r.read().decode()

    def test_queue_and_card_show_why(self):
        s, _, body = self.req("GET", "/")
        self.assertEqual(s, 200)
        for text in ("FLIP", "SERVICE", "System says YES", "System says MAYBE", "Needs your decision (3)", "DRY-RUN"):
            self.assertIn(text, body)
        s, _, body = self.req("GET", f"/areq/{TRAILER}")
        for text in ("Why the system recommends this", "Economics", "Confidence &amp; risk", "Provenance",
                     "external source", "deterministic tool", "model output", "https://example.invalid/comps",
                     h(self.store, TRAILER), "Step-up PIN", ">YES<", ">NO<", ">MODIFY<", ">HOLD<", "irreversible",
                     "ACTION_PROPOSED"):
            self.assertIn(text, body)

    def test_post_requires_csrf_and_local_host(self):
        f = {"decision": "YES", "payload_hash_seen": h(self.store, GENERATOR)}
        s, loc, _ = self.req("POST", f"/areq/{GENERATOR}/decide", f)
        self.assertIn("err=", loc)
        self.assertEqual(self.store.action_request(GENERATOR)["status"], "pending_approval")
        s, _, _ = self.req("GET", "/", host="evil.example:80")
        self.assertEqual(s, 403)
        s, loc, _ = self.req("POST", f"/areq/{GENERATOR}/decide", dict(f, csrf=self.app.csrf), host="evil.example")
        self.assertEqual(s, 403)

    def test_full_web_flow_yes_modify_hold_no(self):
        csrf = self.app.csrf
        s, loc, _ = self.req("POST", f"/areq/{GENERATOR}/decide",
                             {"csrf": csrf, "decision": "YES", "payload_hash_seen": h(self.store, GENERATOR)})
        self.assertEqual(s, 303)
        self.assertIn("msg=", loc)
        self.assertEqual(self.store.action_request(GENERATOR)["status"], "executed")
        newp = dict(self.store.action_request(TRAILER)["payload"], offer=900)
        s, loc, _ = self.req("POST", f"/areq/{TRAILER}/decide",
                             {"csrf": csrf, "decision": "MODIFY", "payload_hash_seen": h(self.store, TRAILER),
                              "new_payload": json.dumps(newp)})
        nid = loc.split("?")[0].rsplit("/", 1)[1]
        self.assertNotEqual(nid, TRAILER)
        self.assertEqual(self.store.action_request(nid)["status"], "pending_approval")
        s, loc, _ = self.req("POST", f"/areq/{nid}/decide",
                             {"csrf": csrf, "decision": "HOLD", "payload_hash_seen": h(self.store, nid), "hold_preset": "3d"})
        self.assertEqual(self.store.action_request(nid)["status"], "held")
        s, loc, _ = self.req("POST", f"/areq/{DRYWALL}/decide",
                             {"csrf": csrf, "decision": "NO", "payload_hash_seen": h(self.store, DRYWALL), "reason": ""})
        self.assertIn("err=", loc)
        s, loc, _ = self.req("POST", f"/areq/{DRYWALL}/decide",
                             {"csrf": csrf, "decision": "NO", "payload_hash_seen": h(self.store, DRYWALL),
                              "reason": "customer outside area", "archive": "1"})
        self.assertEqual(self.store.action_request(DRYWALL)["status"], "rejected")
        s, _, body = self.req("GET", "/ledger")
        self.assertIn("chain verified", body)

    def test_untrusted_text_is_escaped(self):
        r = self.svc.modify(GENERATOR, h(self.store, GENERATOR),
                            dict(self.store.action_request(GENERATOR)["payload"], title="<script>alert(1)</script>"))
        _, _, body = self.req("GET", f"/areq/{r['new_action_request_id']}")
        self.assertNotIn("<script>alert(1)</script>", body)
        self.assertIn("&lt;script&gt;", body)


if __name__ == "__main__":
    unittest.main()
