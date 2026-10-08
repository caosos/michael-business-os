"""F-29: the UI half of the operator audit (F-88 owner DSN + notice, F-89 FROZEN help, F-90 Confirm forms, F-92 truthful comp message,
F-94 mission legs + HOLD, F-95 one figure per concept, F-97 edit a campaign, F-98 Today header, F-100 hide unconfigured tabs)."""

from __future__ import annotations

import copy
import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from operator_ui import __main__ as cli
from operator_ui import attest_view, card_view, digest, mission_view as mv, wanted_view
from operator_ui.server import App, make_handler
from tests.conftest import PIN
from tests.test_operator_ui import req

ROOT = Path(__file__).resolve().parent.parent
PLAN = json.loads((ROOT / "docs/research/contracts/examples/mission/mission-plan.example.json").read_text())
SVC = {"item_id": "itm_" + "0" * 25 + "2", "state": "RESEARCHING", "category": "smart_home", "type": "service",
       "normalized": {"title": "Install video doorbell"},
       "scores": {"scorecard": {"evidence_search": {"items": ["customer_screened", "scope_verified", "sold_comp_count"]}}}}
CARD = {"item_id": SVC["item_id"], "item": {"title": "Install video doorbell", "category": "smart_home", "make_model": {"value": "x"}},
        "activity_trail": [{"why": "gaps: customer_screened"}]}


class Stub:
    lane = "lane_d"
    owner_login = False

    def __init__(self):
        self.state, self.attested = "RUNNING", []

    def item(self, i):
        return SVC if i == SVC["item_id"] else None

    def items_in_states(self, s):
        return [SVC] if SVC["state"] in s else []

    def action_requests(self, limit=200):
        return []

    def opportunity_card(self, i):
        return {"card": CARD, "errors": [], "areqs": []}

    def system_state(self):
        return self.state

    def record_attestation(self, item_id, key, note, by):
        self.attested.append((item_id, key, note, by))
        return {}

    def my_numbers(self):
        return {"mission": None, "ledger": None, "available": True}


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr(card_view, "render_item_card", lambda *a, **k: "<h1>card</h1>")
    monkeypatch.setattr(card_view, "render_followup_section", lambda *a, **k: "")
    monkeypatch.setattr(card_view, "render_note_section", lambda *a, **k: "")
    monkeypatch.setattr("operator_ui.server.render_outcome_card_section", lambda *a, **k: "")
    for v in ("MBOS_SOURCE_HEALTH_FILE", "MBOS_TELEMETRY_DIR", "MBOS_READY_QUEUE_FILE", "MBOS_INVENTORY_FILE", "MBOS_MISSION_PLAN_FILE"):
        monkeypatch.delenv(v, raising=False)
    app = App(Stub(), operator_pin=PIN, campaigns_file=str(tmp_path / "c.json"), comps_inbox=str(tmp_path / "in"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


# F-88
def test_owner_dsn_prefers_the_canonical_name_and_warns_on_the_old_one():
    assert cli.owner_dsn({"MBOS_OWNER_DATABASE_URL": "a", "MBOS_APPROVER_DATABASE_URL": "b"}) == ("a", None)
    dsn, warn = cli.owner_dsn({"MBOS_APPROVER_DATABASE_URL": "b"})
    assert dsn == "b" and "MBOS_OWNER_DATABASE_URL" in warn
    assert cli.owner_dsn({}) == (None, None)


def test_red_notice_when_owner_writes_would_run_on_the_worker_login(ui):
    h = req(ui, "GET", "/")[2]
    assert 'id="owner-login"' in h and "MBOS_OWNER_DATABASE_URL" in h and "refused" in h
    ui.store.owner_login = True
    assert 'id="owner-login"' not in req(ui, "GET", "/")[2]


# F-89
def test_frozen_banner_explains_and_names_the_release_command(ui):
    ui.store.state = "FROZEN"
    h = req(ui, "GET", "/")[2]
    assert 'id="frozen"' in h and "mbos panic off --reason" in h and "kill switch" in h
    ui.store.state = "RUNNING"
    assert 'id="frozen"' not in req(ui, "GET", "/")[2]


# F-100
def test_tabs_without_a_data_source_are_hidden(ui, tmp_path, monkeypatch):
    h = req(ui, "GET", "/")[2]
    assert 'href="/sources"' not in h and 'href="/usage"' not in h and 'href="/preview"' not in h and 'href="/mission"' in h
    monkeypatch.setenv("MBOS_SOURCE_HEALTH_FILE", str(tmp_path / "h.json"))
    assert 'href="/sources"' in req(ui, "GET", "/")[2]


# F-90
def attest(ui, **f):
    return req(ui, "POST", f"/item/{SVC['item_id']}/attest", {"csrf": ui.csrf, "pin": PIN, "nonce": "nonce12345678", "key": "customer_screened",
                                                              "note": "called Pat, 10 min", **f})


def test_a_confirm_form_per_requested_attestable_key(ui):
    h = req(ui, "GET", f"/item/{SVC['item_id']}")[2]
    assert h.count('action="/item/' + SVC["item_id"] + '/attest"') == 2          # customer_screened + scope_verified; sold_comp_count is not attestable
    assert 'value="customer_screened"' in h and 'value="scope_verified"' in h and "sold_comp_count\"" not in h.replace("sold_comp_count</", "")
    assert "not on a sold price" in h                                             # a service job is not asked for a price first


def test_confirm_calls_record_attestation_as_the_server_set_author(ui):
    s, loc, _ = attest(ui, author="mallory")
    assert s == 303 and "Confirmed" in loc and ui.store.attested == [(SVC["item_id"], "customer_screened", "called Pat, 10 min", "michael")]


def test_confirm_refuses_an_unrequested_key_a_wrong_pin_and_a_missing_note(ui):
    assert attest(ui, key="sold_comp_count")[0] == 200 and attest(ui, key="made_up")[0] == 200
    assert attest(ui, pin="0000")[0] == 200 and attest(ui, note=" ")[0] == 200
    assert req(ui, "POST", f"/item/{SVC['item_id']}/attest", {"pin": PIN, "key": "scope_verified", "note": "x y z", "nonce": "nonce12345678"})[0] == 200  # no csrf
    assert ui.store.attested == []


def test_requested_keys_skip_what_is_already_attested():
    done = {**SVC, "research": [{"field": "attestation:customer_screened", "basis": "FACT", "provenance_id": "prov_x"}]}
    assert attest_view.requested_keys(done) == ["scope_verified"]


# F-92
def test_saved_comp_message_says_the_worker_rechecks_it(ui):
    from operator_ui import comps_view

    m = comps_view.saved_message("itm_1", True)
    assert "worker" in m and "once a minute" in m and "cannot re-check" not in m


# F-94
def leg(**kw):
    return {**copy.deepcopy(PLAN["legs"][0]), **kw}


def test_mission_shows_titles_waiting_on_and_hold_wording():
    doc = copy.deepcopy(PLAN)
    doc["recommendation"] = "HOLD"
    doc["legs"] = [leg(title="Install video doorbell", verdict="MAYBE", waiting_on=["customer_screened", "scope_verified"])]
    h = mv.render_plan(doc, set(), {})
    assert "Install video doorbell" in h and "customer_screened" in h and "<b>HOLD.</b>" in h and "Nothing is ready to approve" in h
    assert "DEPLOY" not in h


def test_deploy_is_never_said_when_no_leg_can_be_approved():
    doc = copy.deepcopy(PLAN)
    doc["recommendation"] = "DEPLOY"
    doc["legs"] = [leg(title="A", verdict="MAYBE", waiting_on=["x"])]
    assert "<b>HOLD.</b>" in mv.render_plan(doc, set())
    doc["legs"] = [leg(title="A", verdict="YES", waiting_on=[])]
    h = mv.render_plan(doc, set())
    assert "<b>DEPLOY</b> capital to the 1 job marked YES" in h and "ready for your decision" in h


def test_stale_ids_show_titles():
    doc = copy.deepcopy(PLAN)
    doc["replace_if_stale"] = ["itm_zzz"]
    assert "Old trailer" in mv.render_plan(doc, set(), {"itm_zzz": "Old trailer"})


# F-98
def test_today_header_has_three_lines_and_never_invents():
    doc = copy.deepcopy(PLAN)
    doc["legs"] = [leg(title="TV flip", verdict="YES", waiting_on=[])]
    h = mv.today_header({"kind": "plan", "doc": doc, "errors": []})
    assert "Gap to target" in h and "Cash" in h and "Best next move" in h and "TV flip" in h and "available to deploy" in h
    u = mv.today_header({"kind": "none", "doc": None, "errors": ["x"]})
    assert u.count("UNKNOWN") >= 3


def test_today_page_renders_the_header(ui):
    assert "Best next move" in req(ui, "GET", "/")[2]


# F-95
def test_one_figure_per_concept():
    g = digest.figures({"rank_score": 11.98, "value_per_hour": 11.98, "ev_decision": 246.5, "ev_profit_per_hour": 79.84})
    assert g == {"priority": 11.98, "ev": 246.5, "ev_per_hour": 79.84}
    assert digest.dollars(g["priority"], "") == "11.98" and digest.dollars(None) == "UNKNOWN"


def test_digest_and_summary_do_not_call_the_rank_score_value_per_hour():
    from operator_ui import server, summary

    row = {"rank": 1, "bucket": "research_yes", "lane": "service", "category": "x", "title": "T", "action": "a", "reason": "r", "window": "later",
           "value_per_hour": 11.98, "rank_score": 11.98, "ev_decision": 246.5, "ev_profit_per_hour": 79.84, "item_id": "i", "refs": {}}
    html = summary.render_html_body({"local_date": "d", "as_of": "a", "summary_hash": "h", "top_n": 1, "digest": {"error": None, "rows": [row]},
                                     "holds": [], "outcomes": {"rows": [], "net_profit": 0}, "sources": {"error": "x", "rows": [], "stale": False}})
    assert "Value $/h" not in html and "Priority score" in html and "$246.5" in html and "$12" not in html


# F-97
def test_edit_a_campaign_keeps_must_have_and_nice_to_have(ui):
    f = {"csrf": ui.csrf, "pin": PIN, "nonce": "nonce00000001", "title": "5x8 trailer", "category": "trailer", "keywords": "5x8",
         "max_price_usd": "600", "must_have": "title, lights", "nice_to_have": "ramp", "level": "RECOMMEND"}
    assert req(ui, "POST", "/wanted/create", f)[0] == 303
    h = req(ui, "GET", "/wanted")[2]
    assert "must have: title, lights" in h and "nice to have: ramp" in h and "/edit'" in h
    cid = ui.campaigns.all()[0]["doc"]["campaign_id"]
    assert req(ui, "POST", f"/wanted/{cid}/edit", {**f, "nonce": "nonce00000002", "max_price_usd": "550", "must_have": "title"})[0] == 303
    [r] = ui.campaigns.all()
    assert r["doc"]["campaign_id"] == cid and r["doc"]["criteria"]["max_price_usd"] == 550.0 and r["doc"]["criteria"]["must_have"] == ["title"]
    assert r["doc"]["criteria"]["nice_to_have"] == [] or r["doc"]["criteria"]["nice_to_have"] == ["ramp"]
    assert r["doc"]["status"] == "ACTIVE" and len(r["history"]) == 2
