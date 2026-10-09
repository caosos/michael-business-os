"""F-32: "Set my quote" and "Tell me about the job" (owner channel). Stubbed store: forms, strict validation, server-set author, true text."""

from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer

import pytest

from operator_ui import card_view, inputs_view
from operator_ui.server import App, make_handler
from tests.conftest import PIN
from tests.test_operator_ui import req

SVC = {"item_id": "itm_" + "0" * 25 + "3", "state": "RECOMMENDED", "type": "service", "category": "drywall_repair",
       "normalized": {"title": "Drywall patch"}, "scores": {"scorecard": {"min_quote_for_yes": 640}}}
FLIP = {"item_id": "itm_" + "0" * 25 + "4", "state": "RESEARCHING", "type": "flip", "category": "other_asset", "normalized": {"title": "mystery gizmo"}}
TRAIL = {SVC["item_id"]: [{"why": "recommended"}],
         FLIP["item_id"]: [{"why": "gaps: BLOCKING scope_override_required: unknown category, tell me the parts cost"}]}


class Stub:
    lane = "lane_d"
    owner_login = True

    def __init__(self):
        self.saved = []
        self.items = {SVC["item_id"]: SVC, FLIP["item_id"]: FLIP}

    def capital_for(self, item_id):
        return {"deployed": 0.0, "closed": False, "net": None}

    def open_acquisitions(self):
        return []

    def item(self, i):
        return self.items.get(i)

    def items_in_states(self, s):
        return []

    def action_requests(self, limit=200):
        return []

    def opportunity_card(self, i):
        return {"card": {"item_id": i, "item": {"title": "t", "category": "c", "make_model": {"value": "x"}}, "activity_trail": TRAIL[i]},
                "errors": [], "areqs": []}

    def system_state(self):
        return "RUNNING"

    def record_human_inputs(self, item_id, inputs, note, by):
        self.saved.append((item_id, inputs, note, by))
        return []


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr(card_view, "render_item_card", lambda *a, **k: "<h1>card</h1>")
    monkeypatch.setattr(card_view, "render_followup_section", lambda *a, **k: "")
    monkeypatch.setattr(card_view, "render_note_section", lambda *a, **k: "")
    monkeypatch.setattr("operator_ui.server.render_outcome_card_section", lambda *a, **k: "")
    app = App(Stub(), operator_pin=PIN, comps_inbox=str(tmp_path / "in"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


def post(ui, item, which, **f):
    body = {"csrf": ui.csrf, "pin": PIN, "nonce": "nonce12345678"}
    body.update(f)
    return req(ui, "POST", f"/item/{item['item_id']}/{which}", body)


def quote(ui, **f):
    return post(ui, SVC, "quote", **{"amount": "700", "note": "called Pat, agreed on the phone", **f})


def scope(ui, **f):
    return post(ui, FLIP, "scope", **{"parts_cost": "120", "labor_hours": "4", "required_skills": "repair, soldering", "note": "I opened it up", **f})


def test_quote_form_only_on_a_service_lead_with_the_suggestion_as_a_suggestion(ui):
    h = req(ui, "GET", f"/item/{SVC['item_id']}")[2]
    assert "Set my quote" in h and f'action="/item/{SVC["item_id"]}/quote"' in h and "$640 or more would clear the bar" in h and "only a suggestion" in h
    h = req(ui, "GET", f"/item/{FLIP['item_id']}")[2]
    assert "Set my quote" not in h and "Tell me about the job" in h and f'action="/item/{FLIP["item_id"]}/scope"' in h
    assert "Tell me about the job" not in req(ui, "GET", f"/item/{SVC['item_id']}")[2]


def test_quote_saves_as_the_server_set_author_with_true_after_save_text(ui):
    s, loc, _ = quote(ui, author="mallory", kind="scope_override")
    assert s == 303 and ui.store.saved == [(SVC["item_id"], [("quote", "amount_usd", 700)], "called Pat, agreed on the phone", "michael")]
    assert "the verdict has not changed yet" in loc and "re-checks this item by itself" in loc and f"mbos recheck {SVC['item_id']}" in loc


def test_quote_strict_validation(ui):
    for bad in ("0", "-5", "abc", "1e9", "nan", "inf", "7,0,0", "99999999", "12.345", ""):
        assert quote(ui, amount=bad)[0] == 200, bad
    assert quote(ui, note=" ")[0] == 200 and quote(ui, note="x\x07yz")[0] == 200
    assert quote(ui, pin="0000")[0] == 200
    assert req(ui, "POST", f"/item/{SVC['item_id']}/quote", {"pin": PIN, "amount": "700", "note": "abc", "nonce": "nonce12345678"})[0] == 200  # no csrf
    assert ui.store.saved == []
    assert quote(ui, amount="$1,250.50")[0] == 303 and ui.store.saved[-1][1] == [("quote", "amount_usd", 1250.5)]


def test_a_quote_is_refused_on_a_non_service_item_and_a_scope_on_an_estimable_one(ui):
    assert post(ui, FLIP, "quote", amount="700", note="abc")[0] == 200
    assert post(ui, SVC, "scope", parts_cost="1", labor_hours="1", required_skills="a1", note="abc")[0] == 200
    assert ui.store.saved == []


def test_scope_saves_each_figure_under_the_item_block(ui):
    s, _, _ = scope(ui, admin_hours="0.5")
    assert s == 303 and ui.store.saved[0][1] == [("scope_override", "rehab.parts_cost", 120), ("scope_override", "rehab.labor_hours", 4),
                                                  ("scope_override", "rehab.admin_hours", 0.5), ("scope_override", "rehab.required_skills", ["repair", "soldering"])]
    assert ui.store.saved[0][3] == "michael"


def test_scope_strict_validation(ui):
    for bad in ({"parts_cost": "-1"}, {"labor_hours": ""}, {"labor_hours": "5000"}, {"admin_hours": "x"}, {"required_skills": ""},
                {"required_skills": "<script>"}, {"required_skills": ",".join("ab" for _ in range(9))}, {"note": ""}, {"pin": "0000"}):
        assert scope(ui, **bad)[0] == 200, bad
    assert ui.store.saved == []


def test_hostile_text_is_escaped_and_refusals_keep_what_was_typed(ui):
    s, _, h = scope(ui, required_skills="<script>alert(1)</script>")
    assert s == 200 and "<script>alert(1)" not in h and "&lt;script&gt;" in h


def test_forms_fail_closed_without_a_pin_or_lane_d():
    item = {**SVC}
    h = inputs_view.render_inputs(item, {}, "csrf", False, True, "n")
    assert "MBOS_OPERATOR_PIN is not set" in h and "<form" not in h
    assert "lane D store" in inputs_view.render_inputs(item, {}, "csrf", True, False, "n") and inputs_view.render_inputs({**item, "state": "ARCHIVED"}, {}, "c", True, True, "n") == ""
