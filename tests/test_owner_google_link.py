"""The owner's own Google login opens the EXISTING owner data; every other Google login stays isolated.

Deterministic: the Google exchange is faked (as in test_google_oauth_public); no network."""
from __future__ import annotations

import threading
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from operator_ui import accounts, market_prefs as mp
from operator_ui.server import App, make_handler
from tests.test_google_oauth_public import ENV, Store, request

OWNER = "michael.owner@example.com"


class LoginAs:
    secure_cookies = True

    def __init__(self, real, sub, email, name):
        self.real, self.sub, self.email, self.name = real, sub, email, name

    def authorization_url(self, flow):
        return self.real.authorization_url(flow)

    def authenticate(self, code, flow):
        return accounts.google_account(self.sub, self.email, self.name)


def test_link_owner_rules():
    owner = accounts.google_account("sub-owner-1", "Michael.Owner@Example.com", "Michael")
    other = accounts.google_account("sub-other-1", "someone@example.com", "Someone")
    linked = accounts.link_owner(owner, accounts.owner_google_email({accounts.OWNER_EMAIL_ENV: OWNER}))
    assert linked.user_id == accounts.LOCAL_OWNER_ID and linked.authenticated and accounts.is_linked_owner(linked)
    assert linked.storage_key == accounts.LOCAL_OWNER.storage_key and linked.audit_actor == "michael"
    assert accounts.link_owner(other, OWNER) is other
    assert accounts.link_owner(owner, None) is owner                      # nothing configured: never linked
    assert accounts.link_owner(accounts.LOCAL_OWNER, OWNER) is accounts.LOCAL_OWNER
    for bad in ("two@a.com three@b.com", "no-at-sign", "a@b@c"):
        with pytest.raises(accounts.AccountConfigError):
            accounts.owner_google_email({accounts.OWNER_EMAIL_ENV: bad})


def test_linked_owner_reads_and_writes_the_owner_file_and_keeps_its_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "owner.json"))
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    d = mp.load()
    d["hidden"] = {"lot-1": "Old trailer"}
    mp._store(d)
    linked = accounts.link_owner(accounts.google_account("sub-owner-1", OWNER, "Michael"), OWNER)
    with accounts.use(linked):
        assert mp.path() == tmp_path / "owner.json"
        assert mp.load()["hidden"] == {"lot-1": "Old trailer"}
        assert "home" not in mp.load()["ui"]                              # the owner's Conway default is not blanked
    with accounts.use(accounts.google_account("sub-other-1", "someone@example.com")):
        assert mp.path() != tmp_path / "owner.json" and mp.load()["hidden"] == {}


def _sign_in(port, app, host, sub, email):
    app.oauth_client = LoginAs(app.oauth_client.real if isinstance(app.oauth_client, LoginAs) else app.oauth_client, sub, email, "Name")
    _, location, headers, _ = request(port, "GET", "/auth/google/start?next=/settings", host)
    state = parse_qs(urlparse(location).query)["state"][0]
    flow = next(v.split(";", 1)[0] for k, v in headers if k.lower() == "set-cookie" and v.startswith("ds_oauth="))
    _, _, headers, _ = request(port, "GET", "/auth/google/callback?" + urlencode({"code": "c", "state": state}), host, cookie=flow)
    return next(v.split(";", 1)[0] for k, v in headers if k.lower() == "set-cookie" and v.startswith("ds_session=") and "Max-Age=0" not in v)


def test_browser_sign_in_as_owner_sees_owner_data_and_another_login_does_not(tmp_path, monkeypatch):
    for key, value in {**ENV, "MBOS_GOOGLE_REDIRECT_URI": "http://127.0.0.1:8766/auth/google/callback"}.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(accounts.OWNER_EMAIL_ENV, OWNER.upper())
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "owner.json"))
    d = mp.load()
    d["bids"] = {"manual:abc": {"title": "Owner log splitter", "source": "HiBid", "url": "https://hibid.com/lot/1", "status": "outbid",
                                "closes": "", "closes_at": "", "bid": 800.0, "bidders": None, "max_bid": None, "marked_at": "", "origin": "MANUAL"}}
    mp._store(d)
    app = App(Store(), sell_intake_file=tmp_path / "sell.jsonl")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        port = httpd.server_address[1]
        host = f"127.0.0.1:{port}"
        owner_cookie = _sign_in(port, app, host, "sub-owner-1", OWNER)
        _, _, _, settings = request(port, "GET", "/settings", host, cookie=owner_cookie)
        assert "linked to the owner account" in settings
        _, _, _, bids = request(port, "GET", "/market/bids", host, cookie=owner_cookie)
        assert "Owner log splitter" in bids
        other_cookie = _sign_in(port, app, host, "sub-other-1", "someone@example.com")
        _, _, _, bids = request(port, "GET", "/market/bids", host, cookie=other_cookie)
        assert "Owner log splitter" not in bids
        _, _, _, settings = request(port, "GET", "/settings", host, cookie=other_cookie)
        assert "linked to the owner account" not in settings
        _, _, _, bids = request(port, "GET", "/market/bids", host)                 # no cookie on loopback: local owner, as before
        assert "Owner log splitter" in bids
    finally:
        httpd.shutdown()
        httpd.server_close()
