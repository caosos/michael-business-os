"""Public deployment (dealsniffers.com, MBOS_PUBLIC_DEPLOYMENT=1): no local owner, no database, customer pages only.

Runs the real HTTP handler on loopback with the PublicStore. Google's token exchange is faked; nothing reaches a network."""
from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from operator_ui import accounts
from operator_ui.public_store import PublicModeRefused, PublicStore
from operator_ui.server import App, make_handler
from tests.test_google_oauth_public import ENV, request

PUBLIC = {**ENV, "MBOS_GOOGLE_REDIRECT_URI": "https://dealsniffers.com/auth/google/callback", "MBOS_PUBLIC_DEPLOYMENT": "1"}
HOST = "dealsniffers.com"


class FakeGoogle:
    secure_cookies = True

    def __init__(self, real):
        self.real = real

    def authorization_url(self, flow):
        return self.real.authorization_url(flow)

    def authenticate(self, code, flow):
        return accounts.google_account("public-user-1", "visitor@example.com", "Visitor")


@pytest.fixture()
def site(tmp_path, monkeypatch):
    for k, v in PUBLIC.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "owner-prefs.json"))
    monkeypatch.setenv("MBOS_GSA_CACHE", str(tmp_path / "gsa.json"))            # no cache yet: Marketplace says offline, nothing is fetched
    monkeypatch.setenv("MBOS_FACEBOOK_CACHE", str(tmp_path / "facebook.json"))
    app = App(PublicStore(), sell_intake_file=tmp_path / "sell.jsonl")
    app.oauth_client = FakeGoogle(app.oauth_client)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield app, httpd.server_address[1], tmp_path
    httpd.shutdown()
    httpd.server_close()


def sign_in(port):
    _, location, headers, _ = request(port, "GET", "/auth/google/start?next=/market", HOST)
    state = parse_qs(urlparse(location).query)["state"][0]
    flow = next(v.split(";", 1)[0] for k, v in headers if k.lower() == "set-cookie" and v.startswith("ds_oauth="))
    status, location, headers, _ = request(port, "GET", "/auth/google/callback?" + urlencode({"code": "c", "state": state}), HOST, cookie=flow)
    assert status == 303 and location == "/market"
    return next(v.split(";", 1)[0] for k, v in headers if k.lower() == "set-cookie" and v.startswith("ds_session=") and "Max-Age=0" not in v)


def test_loopback_and_unexpected_hosts_are_rejected_so_nobody_becomes_the_local_owner(site):
    _, port, _ = site
    for host in ("127.0.0.1", f"127.0.0.1:{port}", "localhost", "[::1]", "www.dealsniffers.com", "evil.example", ""):
        for method, path in (("GET", "/market"), ("GET", "/queue"), ("GET", "/market/bids"), ("POST", "/market/bid")):
            status, _, _, body = request(port, method, path, host, {} if method == "POST" else None)
            assert status == 403 and "forbidden host" in body, (host, path, status)


def test_public_pages_and_sign_in_redirect_use_the_exact_https_callback(site):
    _, port, _ = site
    for path, words in (("/home", "Continue with Google"), ("/privacy", "Privacy"), ("/terms", "Terms")):
        status, _, _, body = request(port, "GET", path, HOST)
        assert status == 200 and words in body, path
    status, location, _, _ = request(port, "GET", "/", HOST)
    assert status == 200 or (status in (302, 303) and location.startswith("/home"))
    status, location, headers, _ = request(port, "GET", "/auth/google/start", HOST)
    q = parse_qs(urlparse(location).query)
    assert status == 302 and location.startswith(accounts.GOOGLE_AUTHORIZATION_ENDPOINT)
    assert q["redirect_uri"] == ["https://dealsniffers.com/auth/google/callback"] and q["scope"] == ["openid email profile"]
    assert all("Secure" in v and "HttpOnly" in v for k, v in headers if k.lower() == "set-cookie")


def test_signed_out_visitors_are_sent_to_sign_in_and_operator_pages_never_open(site):
    _, port, _ = site
    for path in ("/market", "/market/bids", "/settings", "/sell", "/queue", "/numbers", "/item/x", "/areq/x"):
        status, location, _, _ = request(port, "GET", path, HOST)
        assert status == 303 and location.startswith("/home?next="), path
    cookie = sign_in(port)
    for path in ("/queue", "/numbers", "/inputs", "/mission", "/item/x", "/areq/x", "/static/../queue"):
        status, _, _, body = request(port, "GET", path, HOST, cookie=cookie)
        assert status == 404 and body == "not found", path
    for path in ("/areq/x/decide", "/item/x/note", "/wanted/save"):
        status, _, _, body = request(port, "POST", path, HOST, {"csrf": "x"}, cookie)
        assert status == 404, path


def test_signed_in_customer_pages_work_without_any_database(site):
    _, port, _ = site
    cookie = sign_in(port)
    for path in ("/market", "/market/bids", "/market/flash", "/settings", "/sell", "/sell/submissions", "/market?source=gsa&radius=50&cat=all"):
        status, _, _, body = request(port, "GET", path, HOST, cookie=cookie)
        assert status == 200, (path, status, body[:200])
        assert "Signed in as" in body or path != "/settings"


def test_visitors_get_their_own_files_never_the_owner_file(site):
    _, port, tmp = site
    cookie = sign_in(port)
    request(port, "GET", "/market?source=gsa&base=72032&radius=25&cat=all", HOST, cookie=cookie)
    assert not (tmp / "owner-prefs.json").exists()
    assert list((tmp / "accounts").glob("*/market_prefs.json"))


def test_public_mode_refuses_to_start_without_https_google_settings(tmp_path, monkeypatch):
    for k, v in PUBLIC.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MBOS_GOOGLE_REDIRECT_URI", "http://127.0.0.1:8766/auth/google/callback")
    with pytest.raises(SystemExit):
        App(PublicStore(), sell_intake_file=tmp_path / "sell.jsonl")
    for k in ENV:
        monkeypatch.delenv(k)
    with pytest.raises(SystemExit):
        App(PublicStore(), sell_intake_file=tmp_path / "sell.jsonl")


def test_public_store_refuses_operator_calls():
    s = PublicStore()
    assert s.system_state() == "RUNNING" and s.campaign_records() == []
    for name in ("decide", "item", "items_in_states", "capital_move", "set_campaign"):
        with pytest.raises(PublicModeRefused):
            getattr(s, name)


def test_saving_a_search_is_refused_plainly_and_nothing_is_shared(site):
    app, port, tmp = site
    cookie = sign_in(port)
    _, _, _, settings = request(port, "GET", "/settings", HOST, cookie=cookie)
    csrf = settings.split("name='csrf' value='", 1)[1].split("'", 1)[0]
    status, _, _, body = request(port, "POST", "/market/save", HOST, {"csrf": csrf, "keywords": "trailer", "title": "x"}, cookie)
    assert status in (200, 303, 400) and "Traceback" not in body
    assert app.campaign_records() == [] and not (tmp / "campaigns.json").exists()
