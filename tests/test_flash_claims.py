"""F-167 deterministic first-N flash deals and redemptions."""

import re
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import ThreadingHTTPServer

import pytest

from operator_ui import accounts, flash_claims, flash_claims_view
from operator_ui.ux import InputError


NOW = datetime(2026, 10, 13, 15, 0, tzinfo=timezone.utc)
BASE = {
    "vendor": "Conway Family Butcher",
    "title": "First three get half-price ground beef",
    "description": "Two pounds per redemption while the fixed claim inventory lasts.",
    "territory": "Conway, AR · pickup only",
    "eligibility": "One claim per verified person",
    "starts_at": (NOW - timedelta(minutes=1)).isoformat(),
    "claims_end_at": (NOW + timedelta(hours=1)).isoformat(),
    "redeem_by": (NOW + timedelta(hours=4)).isoformat(),
    "claim_limit": "3",
    "waitlist_limit": "2",
}


def definition(account=None, **changes):
    return flash_claims.parse_deal({**BASE, **changes}, deal_id="flash-beef", created_at=NOW, account=account)


def test_definition_is_fixed_first_n_with_no_payment_or_random_selection():
    row = definition()
    assert row["mode"] == "DETERMINISTIC_FIRST_N"
    assert row["payment_required"] is False and row["random_selection"] is False
    assert row["claim_limit"] == 3 and row["waitlist_limit"] == 2
    with pytest.raises(InputError, match="after the release"):
        definition(claims_end_at=BASE["starts_at"])
    with pytest.raises(InputError, match="cannot be before"):
        definition(redeem_by=(NOW - timedelta(hours=2)).isoformat())


def test_exact_inventory_never_overclaims_under_concurrency(tmp_path):
    store = flash_claims.Store(tmp_path / "flash.jsonl")
    store.create(definition())
    gate = threading.Barrier(40)

    def race(number):
        gate.wait()
        return store.claim("flash-beef", NOW, f"person-{number}")["status"]

    with ThreadPoolExecutor(max_workers=40) as pool:
        statuses = list(pool.map(race, range(40)))
    assert statuses.count("CLAIMED") == 3
    assert statuses.count("WAITLISTED") == 2
    assert statuses.count("CLAIMED_OUT") == 35
    deal = store.list(NOW)[0]
    assert (deal["claimed"], deal["waitlisted"], deal["remaining"], deal["state"]) == (3, 2, 0, "CLAIMED_OUT")
    tokens = [r["details"]["redemption_token"] for r in store.receipts() if r["event"] == "FLASH_CLAIM_AWARDED"]
    assert len(tokens) == len(set(tokens)) == 3
    assert store.verify() == (True, f"{len(store.receipts())} receipts verified")


def test_one_per_person_is_idempotent_and_does_not_consume_another_claim(tmp_path):
    store = flash_claims.Store(tmp_path / "flash.jsonl")
    store.create(definition())
    first = store.claim("flash-beef", NOW, "same-person")
    again = store.claim("flash-beef", NOW + timedelta(seconds=1), "same-person")
    assert first["status"] == again["status"] == "CLAIMED"
    assert again["idempotent"] is True
    assert again["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    assert store.list(NOW)[0]["remaining"] == 2


def test_schedule_expiration_waitlist_and_claimed_out_states(tmp_path):
    store = flash_claims.Store(tmp_path / "flash.jsonl")
    store.create(definition(claim_limit="1", waitlist_limit="1"))
    assert store.list(NOW - timedelta(hours=1))[0]["state"] == "SCHEDULED"
    assert store.claim("flash-beef", NOW - timedelta(hours=1), "early")["status"] == "SCHEDULED"
    assert store.claim("flash-beef", NOW, "winner")["status"] == "CLAIMED"
    assert store.claim("flash-beef", NOW, "backup")["status"] == "WAITLISTED"
    assert store.claim("flash-beef", NOW, "late")["status"] == "CLAIMED_OUT"
    assert store.list(NOW + timedelta(hours=2))[0]["state"] == "EXPIRED"


def test_vendor_confirmation_is_receipted_idempotent_and_expires(tmp_path):
    store = flash_claims.Store(tmp_path / "flash.jsonl")
    store.create(definition())
    won = store.claim("flash-beef", NOW, "person-1")
    confirmed = store.confirm(won["token"], NOW + timedelta(minutes=5))
    again = store.confirm(won["token"], NOW + timedelta(minutes=6))
    assert confirmed["status"] == again["status"] == "CONFIRMED"
    assert again["idempotent"] is True
    assert confirmed["receipt"]["event"] == "FLASH_REDEMPTION_CONFIRMED"

    store2 = flash_claims.Store(tmp_path / "expired.jsonl")
    store2.create(definition())
    other = store2.claim("flash-beef", NOW, "person-2")
    expired = store2.confirm(other["token"], NOW + timedelta(hours=5))
    assert expired["status"] == "EXPIRED"
    assert expired["receipt"]["event"] == "FLASH_REDEMPTION_DECLINED"


def test_journals_are_account_isolated(tmp_path):
    store = flash_claims.Store(tmp_path / "flash.jsonl")
    one = accounts.google_account("vendor-one", "one@example.com")
    two = accounts.google_account("vendor-two", "two@example.com")
    with accounts.use(one):
        store.create(definition(one))
        one_path = store.path
    with accounts.use(two):
        assert store.list(NOW) == [] and store.receipts() == []
        two_path = store.path
    assert one_path != two_path
    assert one_path.stat().st_mode & 0o077 == 0


def test_customer_and_vendor_views_show_real_states_and_no_chance_mode(tmp_path):
    store = flash_claims.Store(tmp_path / "flash.jsonl")
    store.create(definition(claim_limit="1", waitlist_limit="1"))
    claimed = store.claim("flash-beef", NOW, "winner")
    customer = flash_claims_view.customer_page(store.list(NOW), "csrf", claimed)
    store.claim("flash-beef", NOW, "backup")
    vendor = flash_claims_view.vendor_page(store.list(NOW), store.receipts(), "csrf")
    assert "Claim secured" in customer and claimed["token"] in customer
    assert "Join waitlist" in customer and "No random winner" in customer
    assert "1/1 claimed" in vendor and "1 waitlisted" in vendor
    assert "no random selection, payment, bid, or chance-based prize mode" in vendor


class StubStore:
    def system_state(self):
        return "RUNNING"


@pytest.fixture()
def ui(tmp_path):
    pytest.importorskip("dbos", reason="HTTP assembly dependency is supplied by the release workflow")
    from operator_ui.server import App, make_handler

    app = App(StubStore(), flash_claims_file=tmp_path / "flash-http.jsonl")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    yield app
    httpd.shutdown()
    httpd.server_close()


def test_http_create_claim_and_vendor_confirmation(ui):
    from tests.test_operator_ui import req

    now = datetime.now(timezone.utc)
    form = {**BASE,
            "starts_at": (now - timedelta(minutes=1)).isoformat(),
            "claims_end_at": (now + timedelta(hours=1)).isoformat(),
            "redeem_by": (now + timedelta(hours=2)).isoformat(),
            "csrf": ui.csrf}
    status, location, _ = req(ui, "POST", "/sell/deal/flash/create", form)
    assert status == 303 and location.startswith("/sell/deal/flash?msg=")
    status, _, customer = req(ui, "GET", "/market/flash")
    assert status == 200 and "First three get half-price ground beef" in customer
    assert "Claim this deal" in customer and "No random winner" in customer
    deal_id = ui.flash_claims.list(now)[0]["deal_id"]
    status, _, claimed = req(ui, "POST", f"/market/flash/{deal_id}/claim", {"csrf": ui.csrf})
    assert status == 200 and "Claim secured" in claimed
    token = re.search(r"flash-token.*?<code>([^<]+)</code>", claimed, re.S).group(1)
    status, location, _ = req(ui, "POST", "/sell/deal/flash/confirm", {"csrf": ui.csrf, "token": token})
    assert status == 303 and "Redemption confirmed" in location
    vendor = req(ui, "GET", "/sell/deal/flash")[2]
    assert "1/3 claimed" in vendor and "1 redeemed" in vendor
    assert "FLASH_REDEMPTION_CONFIRMED" in vendor
