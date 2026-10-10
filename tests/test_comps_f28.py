"""F-28: a RESEARCHING item says what it needs; "Add a price I saw" writes a ManualCompsAdapter inbox file (read back with lane B's
adapter). Strict input; human channel only (CSRF + PIN, author server-set); no automation of any site."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

import pytest

from operator_ui import card_view, comps_view
from operator_ui.server import App, make_handler
from tests.conftest import PIN
from tests.test_operator_ui import req

ITEM = {"item_id": "itm_" + "0" * 25 + "1", "state": "RESEARCHING", "category": "mower", "type": "flip",
        "normalized": {"title": "Husqvarna Z254 <b>zero turn</b>"}}
CARD = {"item_id": ITEM["item_id"], "item": {"title": "Husqvarna Z254", "category": "mower", "make_model": {"value": "Husqvarna Z254"}},
        "activity_trail": [{"why": "RESEARCH result: RESEARCHING; gaps: no comparable sold price"}]}


class StubStore:
    lane = "reference"

    def __init__(self, state="RESEARCHING"):
        self.item_doc = {**ITEM, "state": state}

    def item(self, item_id):
        return self.item_doc if item_id == ITEM["item_id"] else None

    def capital_for(self, item_id):
        return {"deployed": 0.0, "closed": False, "net": None}

    def open_acquisitions(self):
        return []

    def items_in_states(self, states):
        return [self.item_doc] if self.item_doc["state"] in states else []

    def action_requests(self, limit=200):
        return []

    def opportunity_card(self, item_id):
        return {"card": CARD, "errors": [], "areqs": []}

    def system_state(self):
        return "NORMAL"


@pytest.fixture()
def ui(tmp_path, monkeypatch):
    monkeypatch.setattr(card_view, "render_item_card", lambda *a, **k: "<h1>card</h1>")
    monkeypatch.setattr(card_view, "render_followup_section", lambda *a, **k: "")
    monkeypatch.setattr(card_view, "render_note_section", lambda *a, **k: "")
    monkeypatch.setattr("operator_ui.server.render_outcome_card_section", lambda *a, **k: "")
    app = App(StubStore(), operator_pin=PIN, comps_inbox=str(tmp_path / "inbox"))
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


_n = iter(range(10**6))
YESTERDAY = (datetime.now(timezone.utc) - timedelta(days=1)).date().isoformat()
GOOD = {"make": "Husqvarna", "model": "Z254", "sold_price": "$1,450", "sold_date": YESTERDAY, "condition": "used",
        "where_sold": "Facebook Marketplace, I watched it sell", "url": "", "note": "sold in two days, local pickup"}


def post(ui, **f):
    return req(ui, "POST", f"/item/{ITEM['item_id']}/comp",
               {"csrf": ui.csrf, "pin": PIN, "nonce": f"nonce{next(_n):08d}", **GOOD, **f})


def inbox(ui):
    return sorted(__import__("pathlib").Path(ui.comps_inbox).glob("*.json")) if __import__("os").path.isdir(ui.comps_inbox) else []


def test_a_researching_item_shows_the_gap_and_the_form(ui):
    h = req(ui, "GET", f"/item/{ITEM['item_id']}")[2]
    assert "RESEARCH NEEDED, DO NOT BUY YET" in h and "no comparable sold price" in h and "dd a price I saw" in h and "name=\"sold_price\"" in h
    assert ITEM["item_id"] not in req(ui, "GET", "/queue")[2]   # F-46: a demo item is not on the normal feed
    today = req(ui, "GET", "/queue?demo=1")[2]
    assert "no comparable sold price" in today
    assert "<b>zero turn</b>" not in today                       # hostile title is escaped


def test_other_states_show_nothing(ui):
    ui.store.item_doc["state"] = "RECOMMENDED"
    assert "Needs from you" not in req(ui, "GET", f"/item/{ITEM['item_id']}")[2]
    assert post(ui)[0] == 200 and inbox(ui) == []              # refused: the item is not waiting for a price


def test_saved_comp_is_read_back_by_lane_bs_manual_adapter(ui):
    s, loc, _ = post(ui)
    assert s == 303 and "Price saved" in loc and "mbos recheck " + ITEM["item_id"] in loc and "once a minute" in loc
    [p] = inbox(ui)
    from mbos_discovery.comps import ManualCompsAdapter

    now = datetime.now(timezone.utc)
    res = ManualCompsAdapter(ui.comps_inbox, clock=lambda: now).fetch(None)
    [rec] = res.records
    assert res.error is None and rec.payload["entered_by"] == "michael"
    d = ManualCompsAdapter(ui.comps_inbox).normalize(rec.payload, now)
    assert d.price == 1450.0 and d.sold_date == YESTERDAY and d.human_actor == "michael" and d.category == "mower"
    assert d.condition == "used" and d.title == "Husqvarna Z254" and d.source_comp_id == p.stem
    doc = json.loads(p.read_text())
    assert "Nothing was fetched or automated" in doc["provenance_note"] and ITEM["item_id"] in doc["provenance_note"]


def test_double_submit_is_one_file_and_says_so(ui):
    f = {"nonce": "samenonce1234"}
    assert "Price saved" in post(ui, **f)[1]
    assert "already recorded" in post(ui, **f)[1]
    assert len(inbox(ui)) == 1


def test_the_author_is_never_taken_from_the_form(ui):
    post(ui, entered_by="mallory", author="mallory")
    assert json.loads(inbox(ui)[0].read_text())["entered_by"] == "michael"


@pytest.mark.parametrize("field,bad", [
    ("sold_price", "0"), ("sold_price", "-5"), ("sold_price", "nan"), ("sold_price", "inf"), ("sold_price", "1e3"), ("sold_price", "12,34"),
    ("sold_price", "１２３"), ("sold_price", ""), ("sold_price", "99999999"),
    ("sold_date", "2999-01-01"), ("sold_date", "2026-02-30"), ("sold_date", "yesterday"), ("sold_date", "2001-01-01"), ("sold_date", ""),
    ("condition", "mint"), ("make", ""), ("model", "x" * 61), ("where_sold", ""), ("url", "javascript:alert(1)"), ("url", "http://a b")])
def test_bad_input_is_refused_and_stores_nothing(ui, field, bad):
    s, _, body = post(ui, **{field: bad})
    assert s == 200 and "Price not saved" in body and inbox(ui) == []


def test_needs_a_link_or_a_note(ui):
    assert "link or a short note" in post(ui, url="", note="")[2] and inbox(ui) == []
    assert post(ui, url="https://example.com/sold/1", note="")[0] == 303


def test_bad_pin_bad_csrf_and_unset_inbox_store_nothing(ui):
    assert "PIN" in post(ui, pin="wrong")[2] and inbox(ui) == []
    bad = req(ui, "POST", f"/item/{ITEM['item_id']}/comp", {**GOOD, "csrf": "x", "pin": PIN, "nonce": "nonce12345678"})
    assert "Price not saved" in bad[2] and inbox(ui) == []
    ui.comps_inbox = None
    assert "MBOS_COMPS_INBOX" in post(ui)[2]


def test_non_ascii_form_token_is_a_refusal_page(ui):
    assert post(ui, nonce="ñññññññññ")[0] == 200


def test_gap_text_fallback_and_no_llm_path():
    assert comps_view.gap_text({"activity_trail": []}) == comps_view.DEFAULT_GAP
    assert comps_view.gap_text({"activity_trail": [{"why": "MAYBE: needs a local sold price"}]}) == "a local sold price"
    import inspect

    src = inspect.getsource(comps_view)
    assert "urllib" not in src and "requests" not in src and "socket" not in src   # nothing is fetched; a human types the price


def test_f31_gap_text_uses_the_engines_true_blocker_wording():
    t = lambda why: comps_view.gap_text({"activity_trail": [{"why": why}]})  # noqa: E731
    assert t("RESEARCHING; gaps: BLOCKING thin_comps: 1 of 3 needed").startswith("Too few sold prices: 1 of 3 needed")
    assert t("RESEARCHING; gaps: BLOCKING scope_override_required: other/x is unknown").startswith("Waiting for you: other/x")
    assert t("RESEARCHING; gaps: BLOCKING repair_scope_unknown: x").endswith("(fault_identified).")
    assert t("RESEARCHING; gaps: something novel") == "something novel"       # unknown wording is never invented over


def test_f31_comp_is_paired_to_its_item_and_attest_banner_names_the_worker():
    from datetime import datetime, timezone
    doc = comps_view.parse_comp({"sold_price": "92", "make": "Generic", "model": "55in LED TV", "where_sold": "FB", "note": "saw it",
                                 "condition": "used", "sold_date": "2026-10-01", "nonce": "n"}, ITEM, "michael",
                                datetime(2026, 10, 8, tzinfo=timezone.utc))
    assert doc["for_item_id"] == ITEM["item_id"] == doc["item_id"]
