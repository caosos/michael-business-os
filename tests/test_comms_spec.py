"""F-03: comms dry-run spec as data. Pure tests, with no database and no network. Nothing can send."""

from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import comms_spec as cs

ROOT = Path(__file__).resolve().parent.parent
UTC = timezone.utc
CENTRAL = "America/Chicago"


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


# ---------------------------------------------------------------- package is send-free
@pytest.mark.parametrize("path", sorted((ROOT / "comms_spec").glob("*.py")), ids=lambda p: p.name)
def test_spec_package_has_no_network_or_send_path(path):
    src = path.read_text()
    tree = ast.parse(src)
    mods = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    mods |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not mods & {"socket", "http", "urllib", "smtplib", "ssl", "requests", "httpx", "aiohttp",
                       "telnyx", "twilio", "postmark", "vapi", "retell", "subprocess"}, mods
    assert "def send" not in src


# ---------------------------------------------------------------- template registry
def test_registry_hashes_versions_and_no_fabricated_approval():
    reg = cs.load("templates")
    keys = [(t["template_id"], t["version"], t["channel"]) for t in reg["templates"]]
    assert len(keys) == len(set(keys))
    for t in reg["templates"]:
        assert t["content_hash"] == cs.template_hash(t), t["template_id"]
        assert t["channel"] in cs.CHANNELS
        # Pre-approval is Michael's decision: nothing may claim it until an Approval row exists.
        assert t["approval"] == {"status": "draft", "approved_by": None, "approval_id": None}
    assert len({t["content_hash"] for t in reg["templates"]}) == len(reg["templates"])


def test_edit_without_version_bump_is_detected(tmp_path, monkeypatch):
    reg = cs.load("templates")
    edited = json.loads(json.dumps(reg))
    edited["templates"][0]["body"] += " Also, cash only."
    p = tmp_path / "templates.v1.json"
    p.write_text(json.dumps(edited))
    monkeypatch.setattr(cs, "DATA", tmp_path)
    cs.load.cache_clear()
    try:
        with pytest.raises(ValueError, match="content_hash mismatch"):
            cs.render(edited["templates"][0]["template_id"], edited["templates"][0]["channel"],
                      {"listing_title": "x", "question_1": "q", "question_2": "q"})
    finally:
        cs.load.cache_clear()


def test_e1_disclosure_in_every_first_message_and_voice_opening():
    reg = cs.load("templates")
    for t in reg["templates"]:
        if t["first_message"] or t["channel"] == "voice":
            need = "voice_disclosure" if t["channel"] == "voice" else "disclosure"
            assert need in cs.placeholders(t), t["template_id"]
    r = cs.render("voice_opening", "voice", {"topic": "your generator listing"})
    assert r["body"].startswith(reg["voice_disclosure"]) and "recorded" in r["body"]
    with pytest.raises(ValueError, match="may not supply"):
        cs.render("seller_first_inquiry", "sms", {"listing_title": "x", "question_1": "q", "disclosure": "hi"})


def test_sms_carry_opt_out_and_commercial_email_carries_can_spam():
    for t in cs.load("templates")["templates"]:
        if t["channel"] == "sms" and t["first_message"]:
            assert "STOP" in t["body"], t["template_id"]
        if t["channel"] == "email" and t["commercial"]:
            assert {"business_postal_address", "unsubscribe_link"} <= cs.placeholders(t), t["template_id"]


def test_render_is_a_draft_and_binding_templates_force_tier0_step_up():
    r = cs.render("seller_offer", "email", {"listing_title": "6x12 trailer", "offer_amount": "800",
                                            "pickup_window": "Saturday", "offer_expires": "Sunday 6pm"})
    assert r["binding"] is True and r["template_approval"] == "draft" and "$800" in r["body"]
    assert cs.action_constraints(r) == {"tier": 0, "reversibility": "irreversible", "step_up": True, "category": "offer"}
    nb = cs.render("customer_photo_request", "email", {"service_name": "drywall", "photo_subject": "the patch"})
    assert cs.action_constraints(nb)["step_up"] is False and cs.action_constraints(nb)["category"] == "email"
    with pytest.raises(ValueError, match="missing template variables"):
        cs.render("seller_offer", "email", {"listing_title": "x"})
    binding_ids = {t["template_id"] for t in cs.load("templates")["templates"] if t["binding"]}
    assert binding_ids == {"seller_offer", "customer_quote"}


# ---------------------------------------------------------------- Q&A coverage
def test_qa_covers_every_item_category():
    item = json.loads((ROOT / "docs/research/contracts/item.schema.json").read_text())
    branches = {b["if"]["properties"]["type"]["const"]: b["then"]["properties"]["category"]["enum"] for b in item["allOf"]}
    for lane, cats in branches.items():
        for c in cats:
            qs = cs.questions(lane, c)
            assert qs and all(q["q"].endswith("?") and q["decides"] for q in qs), (lane, c)
            assert len({q["id"] for q in qs}) == len(qs), (lane, c)
    assert any("title" in q["q"].lower() for q in cs.questions("flip", "project_vehicle"))


# ---------------------------------------------------------------- E3 send window
@pytest.mark.parametrize("when,ok", [
    (utc(2026, 10, 7, 12, 59), False),   # 07:59 CDT (Wednesday)
    (utc(2026, 10, 7, 13, 0), True),     # 08:00
    (utc(2026, 10, 8, 0, 59), True),     # 19:59
    (utc(2026, 10, 8, 1, 0), False),     # 20:00, stricter than TCPA's 21:00
    (utc(2026, 10, 11, 17, 0), False),   # Sunday noon
])
def test_send_window(when, ok):
    assert cs.window_check(when, CENTRAL, "sms")["ok"] is ok


def test_send_window_never_looser_than_tcpa_and_unknown_tz_denies():
    w = cs.load("comms_policy")["send_window"]
    assert w["legal_floor"]["start"] <= w["effective"]["start"] and w["effective"]["end"] <= w["legal_floor"]["end"]
    assert cs.window_check(utc(2026, 10, 7, 17), None, "sms")["ok"] is False
    assert cs.window_check(utc(2026, 10, 7, 17), "Mars/Base", "sms")["ok"] is False


def test_reply_exemption_never_applies_to_voice():
    late = utc(2026, 10, 8, 3, 0)  # 22:00 CDT
    inbound = late - timedelta(minutes=10)
    assert cs.window_check(late, CENTRAL, "sms", inbound)["ok"] is True
    assert cs.window_check(late, CENTRAL, "voice", inbound)["ok"] is False
    assert cs.window_check(late, CENTRAL, "sms", late - timedelta(hours=2))["ok"] is False


# ---------------------------------------------------------------- rate limits
def test_rate_limits():
    now = utc(2026, 10, 7, 17)
    out = lambda h, ch="sms": {"contact": "c1", "channel": ch, "direction": "outbound", "at": now - timedelta(hours=h)}  # noqa: E731
    inn = lambda h: {"contact": "c1", "channel": "sms", "direction": "inbound", "at": now - timedelta(hours=h)}  # noqa: E731
    assert cs.rate_check([], "c1", "sms", now)["ok"]
    assert not cs.rate_check([out(2)], "c1", "sms", now)["ok"]                       # 1/day cold
    assert cs.rate_check([out(2), inn(1)], "c1", "sms", now)["ok"]                   # active thread
    assert not cs.rate_check([out(30), out(60), out(100)], "c1", "sms", now)["ok"]   # 3 unanswered / 7d
    assert not cs.rate_check([out(2, "voice")], "c1", "voice", now)["ok"]
    assert not cs.rate_check([out(30, "voice"), out(80, "voice")], "c1", "voice", now)["ok"]
    assert cs.rate_check([out(2)], "c2", "sms", now)["ok"]                           # per contact


# ---------------------------------------------------------------- opt-out + DNC
@pytest.mark.parametrize("text,stop", [("STOP", True), (" stop. ", True), ("Stop all", True), ("unsubscribe!", True),
                                       ("opt out", True), ("please don't stop asking", False), ("", False), ("HELP", False)])
def test_opt_out_keywords(text, stop):
    assert cs.is_opt_out(text) is stop


def test_dnc_fails_closed():
    now = utc(2026, 10, 7, 17)
    assert cs.dnc_check(None, None, False, "sms", now)["result"] == "unknown"
    assert cs.dnc_check(now - timedelta(days=32), False, False, "sms", now)["result"] == "stale"
    assert cs.dnc_check(now - timedelta(days=5), True, False, "voice", now)["result"] == "listed"
    assert cs.dnc_check(now - timedelta(days=5), False, True, "email", now)["result"] == "suppressed"
    assert cs.dnc_check(now - timedelta(days=5), False, False, "sms", now)["ok"] is True
    assert cs.dnc_check(None, None, False, "email", now)["result"] == "not_applicable"


# ---------------------------------------------------------------- E1-E7 thresholds + audit
def test_thresholds_cover_e1_to_e7():
    t = cs.load("acceptance_thresholds")["tests"]
    assert sorted(t) == [f"E{i}" for i in range(1, 8)]
    assert t["E3"]["pass"]["max_count"] == 0 and t["E4"]["pass"]["max_seconds_p100"] == 60
    assert t["E5"]["pass"]["p95_max_seconds"] == 1.0


def _receipt(i, **details):
    d = {"kind": "comms", "channel": "sms", "first_message": True, "disclosure_present": True,
         "consent_check": {"result": "not_evaluated"}, "dnc_check": {"result": "not_evaluated"},
         "send_window_check": {"ok": True}, "binding": False, **details}
    return {"receipt_id": f"rcpt_{i}", "type": "ACTION_EXECUTED", "approval_id": f"appr_{i}", "details": d,
            "effector_response": {"provider": "mock-dryrun", "provider_msg_id": f"dry_{i}", "dry_run": True}}


def test_audit_dry_run_and_failures():
    good = cs.audit([_receipt(1), _receipt(2, channel="voice")])
    assert good["E1"]["status"] == "PASS" and good["E2"]["status"] == "DRY_RUN_EXEMPT"
    assert good["E3"]["status"] == good["E6"]["status"] == good["E7"]["status"] == "PASS"
    assert good["E5"]["status"] == "NOT_TESTABLE_IN_DRY_RUN"
    bad_r = _receipt(3, disclosure_present=False, send_window_check={"ok": False}, binding=True)
    bad_r["approval_id"] = None
    bad_r["effector_response"].pop("provider_msg_id")
    bad = cs.audit([bad_r], stop_events=[{"stop_at": utc(2026, 10, 7, 17), "suppressed_at": utc(2026, 10, 7, 17, 2), "sends_after": 1}])
    assert {k: bad[k]["status"] for k in ("E1", "E3", "E4", "E6", "E7")} == dict.fromkeys(("E1", "E3", "E4", "E6", "E7"), "FAIL")
    live = _receipt(4, consent_check={"result": "pass"}, dnc_check={"result": "clear"})
    assert cs.audit([live])["E2"]["status"] == "PASS"  # evaluated checks are needed outside dry-run
