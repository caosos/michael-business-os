"""F-18: the Weekly Mission page, built from the A-23 examples and validated with mbos.mission."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from mbos import mission
from operator_ui import mission_view as mv
from tests.test_operator_ui import ready, req

EX = Path(__file__).resolve().parent.parent / "docs/research/contracts/examples/mission"
PLAN = json.loads((EX / "mission-plan.example.json").read_text())


def write(tmp_path, doc, name="plan.json"):
    p = tmp_path / name
    p.write_text(json.dumps(doc))
    return str(p)


def html_of(doc, tmp_path, known=()):
    return mv.render_page(mv.load_plan(write(tmp_path, doc)), set(known))


def test_the_a23_examples_validate_and_render_everything_asked_for(tmp_path):
    mission.validate_plan(PLAN)                                                # Agent 01's validator accepts the example
    h = html_of(PLAN, tmp_path)
    assert "$1,500" in h and "30 h" in h and "2026-10-05 to 2026-10-11" in h                       # target, hours, week
    for label, v in (("Protected principal", "$500"), ("Earned working capital", "$0"), ("Capital deployed", "$30"),
                     ("Realized profit", "$0"), ("Available to deploy", "$470")):               # the five ledger fields
        assert f"<td>{label}</td><td class='num'>{v}</td>" in h, label
    assert "$275 / $455 / $570" in h and "$1,045" in h and ">low<" in h                          # projected week, gap, confidence
    assert "Remaining gap" in h and "Realized so far" in h and "Best next opportunities (2)" in h
    assert "MICRO_FLIP" in h and "SERVICE_JOB" in h and "$25 / <b>$55</b> / $70" in h
    assert "current_cash_context" in h and "real weekly target" in h                              # the plan's own UNKNOWN list
    assert "Replace if stale" in h and "does not close the gap" in h


def test_every_leg_links_to_its_card_and_unverified_legs_are_flagged(tmp_path):
    for l in PLAN["legs"]:
        assert f"<a href='/item/{l['item_id']}'>" in html_of(PLAN, tmp_path, known=[]), l["item_id"]    # never a leg without a link
    h = html_of(PLAN, tmp_path, known=[PLAN["legs"][0]["item_id"]])
    assert h.count("not in this store: unverified") == 1 and "open the card" in h


def test_null_target_and_hours_render_unknown_and_the_gap_stays_unknown(tmp_path):
    doc = copy.deepcopy(PLAN)
    doc["mission"].update(weekly_target_usd=None, hours_available=None)
    doc["remaining_gap"] = None
    mission.validate_plan(doc)
    h = html_of(doc, tmp_path)
    assert "The weekly target and/or your hours are not set" in h
    assert h.count("<b class='unk'>UNKNOWN</b>") >= 3 and "no target set, so there is no gap to compute" in h
    assert "$1,045" not in h and "$1,500" not in h                                                  # nothing invented
    doc["remaining_gap"] = 1045                                                                      # a gap without a target is invalid
    bad = html_of(doc, tmp_path)
    assert "failed validation" in bad and "remaining_gap must be null" in bad and "$1,045" not in bad


def test_mission_without_a_plan_shows_unknown_target_and_no_plan_yet(tmp_path):
    m = json.loads((EX / "mission-unknown-target.example.json").read_text())
    h = html_of(m, tmp_path)
    assert "not set" in h and "No plan yet." in h and "<b class='unk'>UNKNOWN</b>" in h


def test_do_not_spend_is_shown_plainly_and_first(tmp_path):
    doc = copy.deepcopy(PLAN)
    doc["recommendation"] = "DO_NOT_SPEND"
    doc["legs"] = [dict(doc["legs"][1])]                                                             # the zero-cash service leg only
    doc["ledger"]["capital_deployed"] = 0
    doc["ledger"]["available_to_deploy"] = 500
    doc["projected_week"] = {"low": 250, "likely": 400, "high": 500}
    doc["remaining_gap"] = 1100
    mission.validate_plan(doc)
    h = html_of(doc, tmp_path)
    assert "<b>DO NOT SPEND.</b>" in h and h.index("DO NOT SPEND") < h.index("<h2>Mission</h2>")
    doc["legs"][0]["cash_at_risk"] = 100                                                              # DO_NOT_SPEND that commits cash is invalid
    assert "failed validation" in html_of(doc, tmp_path) and "DO NOT SPEND." not in html_of(doc, tmp_path)


def test_invalid_plans_are_never_rendered_as_numbers(tmp_path):
    doc = copy.deepcopy(PLAN)
    doc["ledger"]["available_to_deploy"] = 999999                                                     # breaks the ledger arithmetic
    h = html_of(doc, tmp_path)
    assert "failed validation, so its numbers are not shown" in h and "available_to_deploy" in h
    assert "$999,999" not in h and "Best next opportunities" not in h


@pytest.mark.parametrize("content,msg", [(None, "not set"), ("nope", "not found"), ("{bad json", "unreadable"), ("[1]", "unrecognised")])
def test_missing_or_malformed_files_are_reported(tmp_path, monkeypatch, content, msg):
    monkeypatch.delenv("MBOS_MISSION_PLAN_FILE", raising=False)
    path = None
    if content == "nope":
        path = str(tmp_path / "missing.json")
    elif content is not None:
        path = str(tmp_path / "f.json")
        Path(path).write_text(content)
    h = mv.render_page(mv.load_plan(path), set())
    assert msg in h and "Best next opportunities" not in h


def test_hostile_text_is_escaped(tmp_path):
    doc = copy.deepcopy(PLAN)
    evil = "<script>alert(1)</script>"
    doc["legs"][0]["why"] = evil
    doc["explanation"] = evil
    doc["mission"]["notes"] = evil
    doc["unknowns"] = [evil]
    h = html_of(doc, tmp_path)
    assert "<script>" not in h and h.count("&lt;script&gt;") >= 4


def test_page_on_the_live_ui_links_a_real_card_and_is_read_only(rt, discover, ui, tmp_path):
    item_id, _ = ready(rt, discover)
    doc = copy.deepcopy(PLAN)
    doc["legs"][0]["item_id"] = item_id
    ui.mission_file = write(tmp_path, doc)
    s, _, body = req(ui, "GET", "/mission")
    assert s == 200 and f"<a href='/item/{item_id}'>open the card</a>" in body and "Weekly mission" in body
    assert "<form" not in body.split("<main>")[1]                                                    # no controls: nothing to spend or commit
    assert req(ui, "GET", "/mission", host="evil.example")[0] == 403
    ui.mission_file = None
