"""Sell/consignment intake: review-only, explicit permissions, append-only storage."""

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from operator_ui import market_view, sell_intake
from operator_ui.server import App, make_handler
from operator_ui.ux import InputError
from tests.test_operator_ui import req


BASE = {
    "relationship": "scout",
    "name": "Michael",
    "email": "michael@example.com",
    "contact_permission": "yes",
    "title": "Ford 8N tractor",
    "category": "Farm equipment",
    "location": "Conway, AR 72032",
    "condition": "needs repair",
    "known_issues": "rear tire is flat",
    "desired_outcome": "Either / not sure",
    "photo_urls": "https://images.example.com/one.jpg\nhttps://images.example.com/two.jpg",
}


class StubStore:
    def system_state(self):
        return "RUNNING"


@pytest.fixture()
def sell_ui(tmp_path):
    app = App(StubStore(), sell_intake_file=tmp_path / "sell.jsonl")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


def test_parse_is_review_only_and_keeps_permission_separate():
    row = sell_intake.parse(BASE, "2026-10-13T04:00:00Z", "sell-1")
    assert row["status"] == "REVIEW_PENDING"
    assert row["published"] is False and row["contact_attempted"] is False
    assert row["basis"] == "SUBMITTER_STATED"
    assert row["submitter"]["contact_permission"] is True
    assert row["owner_contact_permission"] is False and row["owner_contact"] is None
    assert len(row["item"]["photo_urls"]) == 2


def test_permission_and_owner_contact_rules():
    for change, message in [({"contact_permission": ""}, "permission to contact you"), ({"email": "", "phone": ""}, "email address or phone")]:
        with pytest.raises(InputError, match=message):
            sell_intake.parse({**BASE, **change}, "t", "sell-x")
    with pytest.raises(InputError, match="explicitly agreed"):
        sell_intake.parse({**BASE, "owner_contact": "Sam 501-555-0101"}, "t", "sell-x")
    with pytest.raises(InputError, match="http or https"):
        sell_intake.parse({**BASE, "photo_urls": "javascript:alert(1)"}, "t", "sell-x")


def test_store_is_append_only(tmp_path):
    store = sell_intake.Store(tmp_path / "sell.jsonl")
    one = sell_intake.parse(BASE, "t1", "sell-1")
    two = sell_intake.parse({**BASE, "title": "Bush Hog mower"}, "t2", "sell-2")
    store.append(one)
    store.append(two)
    assert [r["submission_id"] for r in store.recent()] == ["sell-2", "sell-1"]
    assert len((tmp_path / "sell.jsonl").read_text().splitlines()) == 2


def test_http_flow_is_visible_from_market_and_does_not_publish(sell_ui, tmp_path):
    assert "href='/sell'" in Path(market_view.__file__).read_text(encoding="utf-8")
    status, _, body = req(sell_ui, "GET", "/sell")
    assert status == 200 and "Review only" in body and "Send for human review" in body
    assert "id='product-header'" in body and "DRY-RUN · nothing leaves this machine" not in body and "Operator UI" not in body

    status, _, body = req(sell_ui, "POST", "/sell/submit", {"csrf": sell_ui.csrf, **BASE, "contact_permission": ""})
    assert status == 200 and "permission to contact you" in body and not (tmp_path / "sell.jsonl").exists()

    status, location, _ = req(sell_ui, "POST", "/sell/submit", {"csrf": sell_ui.csrf, **BASE})
    assert status == 303 and location.startswith("/sell?msg=Submitted for human review")
    saved = json.loads((tmp_path / "sell.jsonl").read_text())
    assert saved["published"] is False and saved["contact_attempted"] is False
    confirmation = req(sell_ui, "GET", "/sell?msg=Submitted%20for%20human%20review.%20Nothing%20was%20published%20and%20nobody%20was%20contacted.")[2]
    assert "Nothing was published and nobody was contacted" in confirmation and "REVIEW PENDING" in confirmation
