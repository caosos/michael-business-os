"""Review-only local-business deal intake and broader Marketplace categories."""

import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from operator_ui import accounts, market_search, vendor_deals
from operator_ui.server import App, make_handler
from operator_ui.ux import InputError
from tests.test_operator_ui import req


BASE = {
    "business_name": "Conway Family Butcher",
    "contact_name": "Sam",
    "email": "sam@example.com",
    "location": "Conway, AR 72032",
    "title": "Fresh ground beef",
    "category": "Meat & groceries",
    "deal_price": "1.99",
    "regular_price": "4.99",
    "unit": "per pound",
    "availability": "First 100 pounds while supplies last",
    "starts_on": "2026-10-14",
    "expires_on": "2026-10-14",
    "source_url": "https://example.com/specials/beef",
    "authority_attestation": "yes",
    "contact_permission": "yes",
    "freshness_commitment": "yes",
}


class StubStore:
    def system_state(self):
        return "RUNNING"


@pytest.fixture()
def ui(tmp_path):
    app = App(StubStore(), vendor_deals_file=tmp_path / "vendor-deals.jsonl")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


def test_vendor_deal_stays_unpublished_and_captures_unit_freshness():
    row = vendor_deals.parse(BASE, "2026-10-13T16:00:00Z", "deal-1")
    assert row["status"] == "REVIEW_PENDING"
    assert row["published"] is False and row["verified"] is False
    assert row["offer"]["deal_price_usd"] == 1.99
    assert row["offer"]["unit"] == "per pound"
    assert row["offer"]["expires_on"] == "2026-10-14"
    assert row["permissions"]["freshness_commitment"] is True


def test_vendor_deal_validation_refuses_misleading_or_stale_shape():
    for change, message in [
        ({"authority_attestation": ""}, "authorized"),
        ({"freshness_commitment": ""}, "kept current"),
        ({"deal_price": "bad"}, "must be a number"),
        ({"regular_price": "1.00"}, "cannot be lower"),
        ({"starts_on": "2026-10-15"}, "on or after"),
    ]:
        with pytest.raises(InputError, match=message):
            vendor_deals.parse({**BASE, **change}, "t", "deal-x")


def test_vendor_store_is_account_isolated_and_append_only(tmp_path):
    store = vendor_deals.Store(tmp_path / "vendor-deals.jsonl")
    one = accounts.google_account("one", "one@example.com")
    two = accounts.google_account("two", "two@example.com")
    with accounts.use(one):
        store.append(vendor_deals.parse(BASE, "t1", "deal-one"))
        one_path = store.path
    with accounts.use(two):
        assert store.recent() == []
        store.append(vendor_deals.parse({**BASE, "title": "Half-price oil change"}, "t2", "deal-two"))
        two_path = store.path
    assert one_path != two_path
    assert one_path.stat().st_mode & 0o077 == 0


def test_http_deal_submission_is_visible_but_not_published(ui, tmp_path):
    status, _, page = req(ui, "GET", "/sell/deal")
    assert status == 200 and "Advertise a local deal" in page
    assert "Review only" in page and "ground beef per pound" in page
    status, location, _ = req(ui, "POST", "/sell/deal/submit", {"csrf": ui.csrf, **BASE})
    assert status == 303 and location.startswith("/sell/deal?msg=Deal submitted")
    saved = json.loads((tmp_path / "vendor-deals.jsonl").read_text())
    assert saved["published"] is False and saved["verified"] is False
    confirmation = req(ui, "GET", location)[2]
    assert "not published or verified yet" in confirmation
    assert "Fresh ground beef" in confirmation and "REVIEW PENDING" in confirmation


def test_broad_deal_categories_are_selectable_but_do_not_replace_owner_defaults():
    q = market_search.parse_query({"cat": ["food_grocery", "fuel_auto", "entertainment"]})
    assert q["cats"] == ["food_grocery", "fuel_auto", "entertainment"]
    default = market_search.parse_query({})
    assert "trailers" in default["cats"] and "food_grocery" not in default["cats"]
    all_cats = market_search.parse_query({"cat": ["all"]})
    assert all(x in all_cats["cats"] for x in ("food_grocery", "restaurants", "fuel_auto", "entertainment", "retail_services"))
