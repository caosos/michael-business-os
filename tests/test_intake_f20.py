"""F-20: conversational-intake draft flow over mbos.intake (A-27): only missing questions, answers carry basis, nothing verified, never published."""

from __future__ import annotations

import pytest

from mbos import intake
from mbos.contracts.schemas import ContractViolation
from operator_ui import intake_view
from tests.test_operator_ui import req

SAY = "sell this mower, smokes, at least $400"


def test_acceptance_draft_and_ordered_missing_questions():
    d = intake_view.start(SAY)
    assert d["category"] == "mower"
    assert d["answers"]["price_usd"] == {"value": "at least $400", "basis": "seller_stated"}
    assert d["answers"]["known_defects"] == {"value": "smokes", "basis": "seller_stated"}
    qs = intake.missing(d)
    keys = [q["key"] for q in qs]
    assert "price_usd" not in keys and "known_defects" not in keys                    # asks only what is missing
    assert keys[0] == "safety_features"                                                # safety first, then material
    assert [q["safety_relevant"] for q in qs] == sorted((q["safety_relevant"] for q in qs), reverse=True)
    inv = intake_view.inventory_draft(d)
    assert inv["published"] is False and inv["status"] == "DRAFT" and inv["dry_run"] is True
    assert all(f["basis"] != "verified" for f in inv["facts"]) and inv["unverified_facts"] == ["price_usd", "known_defects"]


def test_verified_cannot_be_set_and_unknown_is_unknown():
    d = intake_view.start(SAY)
    with pytest.raises(ContractViolation):
        intake.answer(d, "hours", "100", "verified")
    d = intake_view.apply_answers(d, {"a_hours": "ignored", "u_hours": "1", "a_make_model": " Brand X 42T "})
    assert d["answers"]["hours"]["basis"] == "UNKNOWN" and d["answers"]["make_model"] == {"value": "Brand X 42T", "basis": "seller_stated"}
    with pytest.raises(ContractViolation):
        intake_view.apply_answers(d, {"a_bogus": "x"})
    with pytest.raises(ValueError):
        intake_view.start("sell my couch")


def test_http_flow_escapes_hostile_text_and_requires_csrf(ui):
    st, _, body = req(ui, "GET", "/intake")
    assert st == 200 and "sell this mower" in body
    assert "invalid form token" in req(ui, "POST", "/intake/start", {"csrf": "bad", "text": SAY})[2]
    st, _, body = req(ui, "POST", "/intake/start", {"csrf": ui.csrf, "text": SAY + " <script>alert(1)</script>"})
    assert st == 200 and "<script>" not in body and "DRAFT" in body and "Verified facts: 0" in body and "safety_features" in body
    iid = next(iter(ui.intake_drafts))
    st, _, body = req(ui, "POST", f"/intake/{iid}/answer", {"csrf": ui.csrf, "a_safety_features": "<b>blade brake works</b>", "u_hours": "1"})
    assert "<b>blade brake" not in body and "&lt;b&gt;blade brake" in body and "UNKNOWN" in body
    assert "verified" not in {a["basis"] for a in ui.intake_drafts[iid]["answers"].values()}
    assert req(ui, "GET", f"/intake/{iid}")[0] == 200 and req(ui, "POST", "/intake/int-nope/answer", {"csrf": ui.csrf})[0] == 404
