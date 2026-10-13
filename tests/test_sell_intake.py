"""Sell/consignment intake: review-only, explicit permissions, append-only storage."""

import json
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from operator_ui import accounts, market_view, sell_intake
from operator_ui.server import App, make_handler
from operator_ui.ux import InputError
from tests.test_operator_ui import req


BASE = {
    "relationship": "scout",
    "name": "Michael",
    "email": "michael@example.com",
    "authority_attestation": "yes",
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
    assert row["submitter"]["contact_permission"]["scope"] == "THIS_SUBMISSION"
    assert row["authority"]["attested"] is True and row["authority"]["role"] == "scout"
    assert row["owner_contact_permission"] is False and row["owner_contact"] is None
    assert len(row["item"]["photo_urls"]) == 2


def test_permission_and_owner_contact_rules():
    for change, message in [({"authority_attestation": ""}, "ownership, authority, or scout-only"),
                            ({"contact_permission": ""}, "permission to contact you"),
                            ({"email": "", "phone": ""}, "email address or phone")]:
        with pytest.raises(InputError, match=message):
            sell_intake.parse({**BASE, **change}, "t", "sell-x")
    with pytest.raises(InputError, match="explicitly agreed"):
        sell_intake.parse({**BASE, "owner_contact": "Sam 501-555-0101"}, "t", "sell-x")
    with pytest.raises(InputError, match="safe http or https"):
        sell_intake.parse({**BASE, "photo_urls": "javascript:alert(1)"}, "t", "sell-x")
    with pytest.raises(InputError, match="public host"):
        sell_intake.parse({**BASE, "source_url": "http://127.0.0.1/private"}, "t", "sell-x")
    with pytest.raises(InputError, match="add the owner's contact"):
        sell_intake.parse({**BASE, "owner_contact_permission": "yes"}, "t", "sell-x")


def test_store_is_append_only(tmp_path):
    store = sell_intake.Store(tmp_path / "sell.jsonl")
    one = sell_intake.parse(BASE, "t1", "sell-1")
    two = sell_intake.parse({**BASE, "title": "Bush Hog mower"}, "t2", "sell-2")
    store.append(one)
    store.append(two)
    assert [r["submission_id"] for r in store.recent()] == ["sell-2", "sell-1"]
    assert store.recent(0) == []
    assert len((tmp_path / "sell.jsonl").read_text().splitlines()) == 2
    assert (tmp_path / "sell.jsonl").stat().st_mode & 0o077 == 0


def test_accounts_have_separate_journals_and_cannot_read_each_other(tmp_path):
    store = sell_intake.Store(tmp_path / "sell.jsonl")
    one = accounts.google_account("google-user-one", "one@example.com")
    two = accounts.google_account("google-user-two", "two@example.com")
    with accounts.use(one):
        store.append(sell_intake.parse(BASE, "t1", "sell-one"))
        one_path = store._path(one)
    with accounts.use(two):
        assert store.recent() == []
        store.append(sell_intake.parse({**BASE, "title": "Disc mower"}, "t2", "sell-two"))
        two_path = store._path(two)
        assert [r["submission_id"] for r in store.recent()] == ["sell-two"]
    assert one_path != two_path
    with accounts.use(one):
        assert [r["submission_id"] for r in store.recent()] == ["sell-one"]


def test_reviewer_changes_are_append_only_and_visible_in_history(tmp_path):
    store = sell_intake.Store(tmp_path / "sell.jsonl")
    store.append(sell_intake.parse(BASE, "2026-10-13T04:00:00Z", "sell-1"))
    event = store.append_review("sell-1", "NEEDS_INFORMATION", "reviewer:aria",
                                "Need a serial-number photo", "2026-10-13T04:05:00Z")
    current = store.get("sell-1")
    assert event["published"] is False and event["contact_attempted"] is False
    assert current["status"] == "NEEDS_INFORMATION"
    assert current["review_history"][-1]["note"] == "Need a serial-number photo"
    assert len((tmp_path / "sell.jsonl").read_text().splitlines()) == 2
    with pytest.raises(InputError, match="cannot move"):
        store.append_review("sell-1", "NEEDS_INFORMATION", "reviewer:aria", "Duplicate", "t3")


def test_trusted_upload_metadata_is_validated_but_browser_cannot_claim_it():
    receipt = {"provider": "future_store", "upload_id": "up-123", "original_name": "../tractor.jpg",
               "content_type": "image/jpeg", "size_bytes": 1234, "sha256": "a" * 64}
    browser_only = sell_intake.parse({**BASE, "photo_upload_metadata": json.dumps([receipt])}, "t", "sell-browser")
    assert browser_only["item"]["photo_uploads"] == []
    row = sell_intake.parse({**BASE, "photo_upload_metadata": "browser claim"}, "t", "sell-1",
                            upload_metadata=[receipt])
    assert row["item"]["photo_uploads"][0]["original_name"] == "tractor.jpg"
    assert row["item"]["photo_uploads"][0]["state"] == "RECEIPT_UNVERIFIED"
    with pytest.raises(InputError, match="15 MB"):
        sell_intake.parse(BASE, "t", "sell-2", upload_metadata=[{**receipt, "size_bytes": 16 * 1024 * 1024}])


def test_http_flow_is_visible_from_market_and_does_not_publish(sell_ui, tmp_path):
    assert "href='/sell'" in Path(market_view.__file__).read_text(encoding="utf-8")
    status, _, body = req(sell_ui, "GET", "/sell")
    assert status == 200 and "Review only" in body and "Send for human review" in body and "My submissions" in body
    assert "I confirm that I own this item" in body and "it does not authorize publication or owner contact" in body
    assert "id='product-header'" in body and "DRY-RUN · nothing leaves this machine" not in body and "Operator UI" not in body

    status, _, body = req(sell_ui, "POST", "/sell/submit", {"csrf": sell_ui.csrf, **BASE, "contact_permission": ""})
    assert status == 200 and "permission to contact you" in body and not (tmp_path / "sell.jsonl").exists()

    status, location, _ = req(sell_ui, "POST", "/sell/submit", {"csrf": sell_ui.csrf, **BASE})
    assert status == 303 and location.startswith("/sell?msg=Submitted for human review")
    saved = json.loads((tmp_path / "sell.jsonl").read_text())
    assert saved["published"] is False and saved["contact_attempted"] is False
    confirmation = req(sell_ui, "GET", "/sell?msg=Submitted%20for%20human%20review.%20Nothing%20was%20published%20and%20nobody%20was%20contacted.")[2]
    assert "Nothing was published and nobody was contacted" in confirmation and "REVIEW PENDING" in confirmation
    submissions = req(sell_ui, "GET", "/sell/submissions")[2]
    assert "My submissions" in submissions and "Ford 8N tractor" in submissions
    assert "Review history" in submissions and "not published" in submissions and "nobody contacted" in submissions
