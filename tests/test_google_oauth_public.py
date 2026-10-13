"""Public pages and Google OIDC flow; all provider traffic is deterministic and local."""

from __future__ import annotations

import hashlib
import http.client
import json
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import pytest

from operator_ui import accounts, sell_intake
from operator_ui.server import App, make_handler


ENV = {
    "MBOS_GOOGLE_CLIENT_ID": "client.apps.googleusercontent.com",
    "MBOS_GOOGLE_CLIENT_SECRET": "provider-secret",
    "MBOS_GOOGLE_REDIRECT_URI": "https://deals.example/auth/google/callback",
    "MBOS_SESSION_SECRET": "s" * 32,
}

# A test-only RSA key. Production keys are fetched from Google's fixed JWKS URL.
N = 19470742645992718674606075470541487898166911989846396062058319069496238227437380791326053574154597755215852906758672541295941520532944462927502175729774850530077470561264857815585248865417507320364185103544491425806752089177140474702265040347698371995573256924459030887060091301477532128582481544444566539616396864339584351153437669811686775594182106127611114003565127383077485203756719658455438197900753339416318163738468574659585761607538286643850233491392246374546671247791091722712509552753292821367537026716082158845388101045554953541281221126603765158774148041173719173882775461222557200971110217787925597935733
D = 2337843872641663537398343040995025226523573408122149176989134576771379504885862176281256627172780715256931909048079622617113444696488090373018518101493786697913844329868519556141421232616237623082316440785992691604335446995360153736547654035064749519098615419359569617929961067051081073589202241073504952931004186367374172957901571543790671803776630566269700858944024590532542834874251115669708364236042681982552718905049937444020558310646499791064328903852934617912666869166795860039832085891790627650479704154620976058772814194348285615256751716283336033069254153296013641946961803357407062641726684046696776771969
E = 65537


def b64(raw: bytes) -> str:
    return accounts.SessionSigner._b64(raw)


def b64int(value: int) -> str:
    return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))


def jwt(claims: dict, corrupt=False) -> str:
    head = b64(json.dumps({"alg": "RS256", "kid": "test-key", "typ": "JWT"}, separators=(",", ":")).encode())
    body = b64(json.dumps(claims, separators=(",", ":")).encode())
    message = (head + "." + body).encode()
    digest = accounts._SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
    encoded = b"\x00\x01" + b"\xff" * (256 - len(digest) - 3) + b"\x00" + digest
    signature = pow(int.from_bytes(encoded, "big"), D, N).to_bytes(256, "big")
    if corrupt:
        signature = signature[:-1] + bytes((signature[-1] ^ 1,))
    return head + "." + body + "." + b64(signature)


class Response:
    def __init__(self, doc, headers=None):
        self.data = json.dumps(doc, separators=(",", ":")).encode()
        self.headers = headers or {}
        self.status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def read(self, limit):
        return self.data


def test_google_client_uses_pkce_minimal_scopes_and_verifies_signed_claims():
    cfg = accounts.google_oauth_config(ENV)
    flow = accounts.OAuthFlow("state-value-1234567890", "nonce-value-1234567890",
                              "v" * 64, "/settings")
    claims = {"iss": "https://accounts.google.com", "aud": cfg.client_id, "sub": "google-sub-1",
              "email": "owner@example.com", "email_verified": True, "name": "Owner",
              "nonce": flow.nonce, "iat": 1_700_000_000, "exp": 1_700_003_600}
    calls = []

    def opener(request, timeout):
        calls.append((request.full_url, request.data))
        if request.full_url == accounts.GOOGLE_TOKEN_ENDPOINT:
            return Response({"token_type": "Bearer", "scope": "openid email profile",
                             "access_token": "must-not-be-stored", "id_token": jwt(claims)})
        assert request.full_url == accounts.GOOGLE_JWKS_ENDPOINT
        return Response({"keys": [{"kid": "test-key", "kty": "RSA", "use": "sig", "alg": "RS256",
                                    "n": b64int(N), "e": b64int(E)}]}, {"Cache-Control": "public, max-age=3600"})

    client = accounts.GoogleOAuthClient(cfg, opener=opener)
    auth = parse_qs(urlparse(client.authorization_url(flow)).query)
    assert auth["scope"] == ["openid email profile"] and "gmail" not in str(auth).lower()
    assert auth["nonce"] == [flow.nonce] and auth["state"] == [flow.state]
    assert auth["code_challenge_method"] == ["S256"]
    account = client.authenticate("one-time-code", flow, now=1_700_000_010)
    assert account.email == "owner@example.com" and account.authenticated
    posted = parse_qs(calls[0][1].decode())
    assert posted["code_verifier"] == [flow.code_verifier]
    assert "access_token" not in account.__dict__ and len(calls) == 2

    broken = dict(claims, nonce="wrong")
    client._jwks_until = 1_800_000_000
    with pytest.raises(accounts.OAuthError, match="nonce"):
        client.verify_id_token(jwt(broken), flow.nonce, now=1_700_000_010)
    with pytest.raises(accounts.OAuthError, match="signature"):
        client.verify_id_token(jwt(claims, corrupt=True), flow.nonce, now=1_700_000_010)


def test_flow_cookie_is_signed_expires_and_rejects_external_next():
    flow = accounts.new_oauth_flow("https://attacker.example/")
    assert flow.next_path == "/market"
    assert accounts.safe_next_path("/\\attacker.example/") == "/market"
    signer = accounts.OAuthFlowSigner("x" * 32)
    token = signer.issue(flow, now=100)
    assert signer.verify(token, flow.state, now=699) == flow
    with pytest.raises(accounts.OAuthError):
        signer.verify(token, "different-state-value-123456789", now=101)
    with pytest.raises(accounts.OAuthError, match="expired"):
        signer.verify(token, flow.state, now=700)
    cookie = signer.cookie(token, True)
    assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=Lax" in cookie


def test_default_sell_inbox_is_account_scoped(monkeypatch, tmp_path):
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    store = sell_intake.Store()
    first = accounts.google_account("sell-user-1", "one@example.com")
    second = accounts.google_account("sell-user-2", "two@example.com")
    with accounts.use(first):
        record = {"schema": "dealsniffer.sell_submission.v2", "submission_id": "one",
                  "account_key": first.storage_key}
        store.append(record)
        first_path = store.path
    with accounts.use(second):
        assert store.recent() == []
        second_path = store.path
    assert first_path != second_path


class Store:
    def system_state(self):
        return "RUNNING"


class FakeOAuth:
    secure_cookies = True

    def __init__(self, real):
        self.real = real
        self.finished = []

    def authorization_url(self, flow):
        return self.real.authorization_url(flow)

    def authenticate(self, code, flow):
        self.finished.append((code, flow))
        return accounts.google_account("browser-user-1", "browser@example.com", "Browser User")


def request(port, method, path, host, body=None, cookie=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": host}
    if body is not None:
        body = urlencode(body)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    if cookie:
        headers["Cookie"] = cookie
    conn.request(method, path, body=body, headers=headers)
    response = conn.getresponse()
    data = response.read().decode()
    return response.status, response.getheader("Location"), response.getheaders(), data


def test_public_pages_complete_browser_flow_and_keep_accounts_out_of_operator_routes(monkeypatch, tmp_path):
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("MBOS_ACCOUNT_DATA_DIR", str(tmp_path / "accounts"))
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "owner-prefs.json"))
    app = App(Store(), sell_intake_file=tmp_path / "sell.jsonl")
    app.oauth_client = FakeOAuth(app.oauth_client)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        status, _, _, home = request(port, "GET", "/", "deals.example")
        assert status == 200 and "Continue with Google" in home and "openid email profile" not in home
        for path, words in (("/privacy", "does not request Gmail access"), ("/terms", "does not bid, buy, pay")):
            status, _, _, body = request(port, "GET", path, "deals.example")
            assert status == 200 and words in body and "Privacy" in body and "Terms" in body

        status, location, headers, _ = request(port, "GET", "/market", "deals.example")
        assert status == 303 and location.startswith("/home?next=")
        status, location, headers, _ = request(port, "GET", "/auth/google/start?next=/settings", "deals.example")
        assert status == 302 and location.startswith(accounts.GOOGLE_AUTHORIZATION_ENDPOINT)
        auth_query = parse_qs(urlparse(location).query)
        flow_cookie = next(value.split(";", 1)[0] for key, value in headers if key.lower() == "set-cookie" and value.startswith("ds_oauth="))
        status, location, headers, _ = request(port, "GET", "/auth/google/callback?" + urlencode({
            "code": "browser-code", "state": auth_query["state"][0]}), "deals.example", cookie=flow_cookie)
        assert status == 303 and location == "/settings"
        cookies = [value for key, value in headers if key.lower() == "set-cookie"]
        assert any(value.startswith("ds_oauth=") and "Max-Age=0" in value for value in cookies)
        session_cookie = next(value.split(";", 1)[0] for value in cookies if value.startswith("ds_session=") and "Max-Age=0" not in value)
        assert all("Secure" in value and "HttpOnly" in value for value in cookies)

        status, _, _, settings = request(port, "GET", "/settings", "deals.example", cookie=session_cookie)
        assert status == 200 and "Signed in as Browser User" in settings and "CONNECTED — identity verified by Google" in settings
        status, _, _, body = request(port, "GET", "/queue", "deals.example", cookie=session_cookie)
        assert status == 404 and body == "not found"
        status, location, headers, _ = request(port, "POST", "/auth/logout", "deals.example",
                                               {"csrf": app.csrf}, session_cookie)
        assert status == 303 and location.startswith("/home")
        assert any(key.lower() == "set-cookie" and value.startswith("ds_session=") and "Max-Age=0" in value
                   for key, value in headers)
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def test_not_configured_is_explicit_and_local_owner_mode_still_opens_market(monkeypatch, tmp_path):
    for key in ENV:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    app = App(Store(), sell_intake_file=tmp_path / "sell.jsonl")
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        port = httpd.server_address[1]
        status, location, _, _ = request(port, "GET", "/", f"127.0.0.1:{port}")
        assert status == 303 and location == "/market"
        status, _, _, body = request(port, "GET", "/home", f"127.0.0.1:{port}")
        assert status == 200 and "Google sign-in is not configured yet" in body
        status, _, _, body = request(port, "GET", "/auth/google/start", f"127.0.0.1:{port}")
        assert status == 503 and "Google sign-in is not configured yet" in body
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)
