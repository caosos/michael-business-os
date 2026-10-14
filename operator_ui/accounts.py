"""Account boundary for DealSniffer's transition from one local owner to many users.

This module owns DealSniffer's small OpenID Connect boundary: strict Google
configuration validation, signed state/nonce/PKCE flow data, token exchange,
cryptographic ID-token verification, opaque signed browser sessions, a
request-local account context, and an atomic profile store.  Provider access and
refresh tokens are never returned to callers or stored.

With no OAuth environment variables the existing local-owner behavior is unchanged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import tempfile
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from email.message import Message
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

LOCAL_OWNER_ID = "local-owner"
GOOGLE_SCOPES = ("openid", "email", "profile")
GOOGLE_SCOPE_ALIASES = {"https://www.googleapis.com/auth/userinfo.email": "email",
                        "https://www.googleapis.com/auth/userinfo.profile": "profile"}
_SUB = re.compile(r"^[A-Za-z0-9._:@+-]{1,255}$")
GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_JWKS_ENDPOINT = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = frozenset(("accounts.google.com", "https://accounts.google.com"))
_SHA256_DIGEST_INFO = bytes.fromhex("3031300d060960864801650304020105000420")


class AccountConfigError(ValueError):
    """The account feature was partly or unsafely configured."""


class InvalidSession(ValueError):
    """A browser session is malformed, expired, or has a bad signature."""


class OAuthError(ValueError):
    """The OAuth/OIDC response is invalid or could not be verified."""


@dataclass(frozen=True)
class Account:
    """A verified local identity.  ``user_id`` is never accepted from form data."""

    user_id: str
    provider: str
    authenticated: bool
    email: str | None = None
    display_name: str | None = None

    @property
    def storage_key(self) -> str:
        # A stable non-PII key also makes path traversal impossible.
        return hashlib.sha256(f"{self.provider}\0{self.user_id}".encode()).hexdigest()[:32]

    @property
    def audit_actor(self) -> str:
        return "michael" if self.user_id == LOCAL_OWNER_ID else f"user:{self.storage_key}"


LOCAL_OWNER = Account(LOCAL_OWNER_ID, "local", False, display_name="Michael")
ANONYMOUS = Account("anonymous", "none", False)
_CURRENT: ContextVar[Account] = ContextVar("dealsniffer_account", default=LOCAL_OWNER)


def current() -> Account:
    return _CURRENT.get()


@contextmanager
def use(account: Account):
    """Bind one verified account to the current request/thread and restore it after."""

    token = _CURRENT.set(account)
    try:
        yield account
    finally:
        _CURRENT.reset(token)


def google_account(subject: str, email: str | None = None, display_name: str | None = None) -> Account:
    """Build an account only from claims already verified against Google's ID token."""

    subject = str(subject or "")
    if not _SUB.fullmatch(subject):
        raise ValueError("Google subject is missing or invalid")
    if email is not None and (len(email) > 320 or "@" not in email):
        raise ValueError("Google email claim is invalid")
    name = " ".join(str(display_name or "").split())[:120] or None
    return Account(subject, "google", True, email=email, display_name=name)


OWNER_EMAIL_ENV = "MBOS_OWNER_GOOGLE_EMAIL"


def owner_google_email(env=None) -> str | None:
    """The owner's own Google address (host configuration, never form input). Unset = no Google login is linked to the owner."""
    env = os.environ if env is None else env
    value = str(env.get(OWNER_EMAIL_ENV) or "").strip().casefold()
    if not value:
        return None
    if len(value) > 320 or value.count("@") != 1 or any(ch.isspace() for ch in value):
        raise AccountConfigError(f"{OWNER_EMAIL_ENV} is not a single e-mail address")
    return value


def link_owner(account: Account, owner_email: str | None) -> Account:
    """A verified Google login whose verified e-mail equals the configured owner address opens the EXISTING owner data
    (filters, saved, hidden, bids) instead of a new empty account. Every other login keeps its own isolated account.
    Only Google-verified e-mails reach a profile (the callback requires email_verified), so this cannot be claimed by a form."""
    if (owner_email and account.authenticated and account.provider == "google" and account.email
            and account.email.strip().casefold() == owner_email):
        return Account(LOCAL_OWNER_ID, "local", True, email=account.email, display_name=account.display_name or "Michael")
    return account


def is_linked_owner(account: Account) -> bool:
    return account.authenticated and account.user_id == LOCAL_OWNER_ID


@dataclass(frozen=True)
class GoogleOAuthConfig:
    enabled: bool
    client_id: str | None = None
    client_secret: str | None = field(default=None, repr=False)
    redirect_uri: str | None = None
    session_secret: str | None = field(default=None, repr=False)
    scopes: tuple[str, ...] = GOOGLE_SCOPES

    def public_status(self) -> dict:
        """Safe to render or log; credentials and session material are omitted."""

        return {
            "provider": "google",
            "configured": self.enabled,
            "redirect_uri": self.redirect_uri if self.enabled else None,
            "scopes": list(self.scopes),
            "flow": "authorization_code_pkce" if self.enabled else None,
            "cookie_security": "secure" if self.enabled and urlparse(self.redirect_uri).scheme == "https" else
                               "loopback-development" if self.enabled else None,
            # Loading credentials proves only local configuration. DNS, TLS,
            # consent configuration, and a completed browser callback need
            # separate external evidence.
            "live_callback": "UNVERIFIED" if self.enabled else "NOT CONFIGURED",
        }


def google_oauth_config(env=None) -> GoogleOAuthConfig:
    """Load an all-or-nothing Google web OAuth configuration.

    Required variables when enabled:
      MBOS_GOOGLE_CLIENT_ID, MBOS_GOOGLE_CLIENT_SECRET,
      MBOS_GOOGLE_REDIRECT_URI, MBOS_SESSION_SECRET.

    An HTTP callback is accepted only on a loopback host for local development.
    Production callbacks must use HTTPS.  Gmail scopes are intentionally excluded:
    signing in and importing a user's vendor-alert mail are separate permissions.
    """

    env = os.environ if env is None else env
    names = ("MBOS_GOOGLE_CLIENT_ID", "MBOS_GOOGLE_CLIENT_SECRET", "MBOS_GOOGLE_REDIRECT_URI", "MBOS_SESSION_SECRET")
    vals = {name: str(env.get(name) or "").strip() for name in names}
    present = [name for name, value in vals.items() if value]
    if not present:
        return GoogleOAuthConfig(False)
    missing = [name for name, value in vals.items() if not value]
    if missing:
        raise AccountConfigError("Google sign-in is partially configured; missing " + ", ".join(missing))
    if len(vals["MBOS_SESSION_SECRET"].encode()) < 32:
        raise AccountConfigError("MBOS_SESSION_SECRET must contain at least 32 bytes")
    uri = urlparse(vals["MBOS_GOOGLE_REDIRECT_URI"])
    loopback = (uri.hostname or "").lower() in {"localhost", "127.0.0.1", "::1"}
    if uri.scheme not in ({"http", "https"} if loopback else {"https"}):
        raise AccountConfigError("Google redirect URI must use HTTPS (HTTP is allowed only on loopback)")
    if not uri.hostname or uri.username or uri.password or uri.fragment or uri.query:
        raise AccountConfigError("Google redirect URI must be an absolute URL without credentials, a query, or a fragment")
    if uri.path != "/auth/google/callback":
        raise AccountConfigError("Google redirect URI path must be /auth/google/callback")
    if any("\r" in value or "\n" in value for value in vals.values()):
        raise AccountConfigError("Google configuration contains an invalid newline")
    if len(vals["MBOS_GOOGLE_CLIENT_ID"]) > 512 or len(vals["MBOS_GOOGLE_CLIENT_SECRET"]) > 512:
        raise AccountConfigError("Google client configuration is too long")
    return GoogleOAuthConfig(True, vals["MBOS_GOOGLE_CLIENT_ID"], vals["MBOS_GOOGLE_CLIENT_SECRET"],
                             vals["MBOS_GOOGLE_REDIRECT_URI"], vals["MBOS_SESSION_SECRET"])


class SessionSigner:
    """Issue/verify compact HMAC sessions containing only the opaque account subject."""

    def __init__(self, secret: str | bytes, ttl_seconds: int = 12 * 60 * 60):
        self.secret = secret.encode() if isinstance(secret, str) else secret
        if len(self.secret) < 32:
            raise ValueError("session secret must contain at least 32 bytes")
        if not 300 <= ttl_seconds <= 30 * 24 * 60 * 60:
            raise ValueError("session lifetime must be between five minutes and 30 days")
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def _b64(data: bytes) -> str:
        return base64.urlsafe_b64encode(data).decode().rstrip("=")

    @staticmethod
    def _unb64(value: str) -> bytes:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

    def issue(self, account: Account, now: int | None = None) -> str:
        if not account.authenticated or account.provider != "google":
            raise ValueError("only a verified Google account may receive a browser session")
        issued = int(time.time() if now is None else now)
        body = json.dumps({"v": 1, "sub": account.user_id, "iat": issued, "exp": issued + self.ttl_seconds},
                          separators=(",", ":"), sort_keys=True).encode()
        payload = self._b64(body)
        signature = self._b64(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
        return payload + "." + signature

    def verify(self, token: str, now: int | None = None) -> str:
        try:
            payload, signature = token.split(".", 1)
            expected = self._b64(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise InvalidSession("invalid session signature")
            body = json.loads(self._unb64(payload))
            stamp = int(time.time() if now is None else now)
            if body.get("v") != 1 or not _SUB.fullmatch(str(body.get("sub") or "")):
                raise InvalidSession("invalid session payload")
            if not isinstance(body.get("iat"), int) or not isinstance(body.get("exp"), int):
                raise InvalidSession("invalid session timestamps")
            if body["iat"] > stamp + 60 or body["exp"] <= stamp or body["exp"] - body["iat"] != self.ttl_seconds:
                raise InvalidSession("expired or invalid session lifetime")
            return body["sub"]
        except InvalidSession:
            raise
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as ex:
            raise InvalidSession("malformed session") from ex

    @staticmethod
    def cookie(token: str, secure: bool = True) -> str:
        attrs = [f"ds_session={token}", "Path=/", "HttpOnly", "SameSite=Lax"]
        if secure:
            attrs.append("Secure")
        return "; ".join(attrs)

    @staticmethod
    def clear_cookie(secure: bool = True) -> str:
        attrs = ["ds_session=", "Path=/", "Max-Age=0", "HttpOnly", "SameSite=Lax"]
        if secure:
            attrs.append("Secure")
        return "; ".join(attrs)


class AccountCsrf:
    """Derive a CSRF token for one server-verified account, never form identity.

    The loopback UI has one random local-owner token. A public multi-user
    deployment must not render that same token to every signed-in account: one
    customer could otherwise reuse their token in a cross-account request.
    """

    def __init__(self, secret: str | bytes):
        self.secret = secret.encode() if isinstance(secret, str) else secret
        if len(self.secret) < 32:
            raise ValueError("CSRF secret must contain at least 32 bytes")

    def issue(self, account: Account) -> str:
        if not account.authenticated:
            raise ValueError("authenticated account required")
        message = ("dealsniffer-csrf-v1\0" + account.storage_key).encode()
        return SessionSigner._b64(hmac.new(self.secret, message, hashlib.sha256).digest())

    def verify(self, token: str, account: Account) -> bool:
        if not isinstance(token, str) or len(token) > 256:
            return False
        try:
            return hmac.compare_digest(token, self.issue(account))
        except ValueError:
            return False


@dataclass(frozen=True)
class OAuthFlow:
    state: str
    nonce: str
    code_verifier: str
    next_path: str


class OAuthFlowSigner:
    """Short-lived, tamper-evident state kept in an HttpOnly callback cookie."""

    def __init__(self, secret: str | bytes, ttl_seconds: int = 10 * 60):
        self.secret = secret.encode() if isinstance(secret, str) else secret
        if len(self.secret) < 32:
            raise ValueError("OAuth flow secret must contain at least 32 bytes")
        self.ttl_seconds = ttl_seconds

    def issue(self, flow: OAuthFlow, now: int | None = None) -> str:
        stamp = int(time.time() if now is None else now)
        body = json.dumps({"v": 1, "state": flow.state, "nonce": flow.nonce,
                           "verifier": flow.code_verifier, "next": flow.next_path,
                           "iat": stamp, "exp": stamp + self.ttl_seconds},
                          separators=(",", ":"), sort_keys=True).encode()
        payload = SessionSigner._b64(body)
        sig = SessionSigner._b64(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
        return payload + "." + sig

    def verify(self, token: str, state: str, now: int | None = None) -> OAuthFlow:
        try:
            payload, signature = token.split(".", 1)
            expected = SessionSigner._b64(hmac.new(self.secret, payload.encode(), hashlib.sha256).digest())
            if not hmac.compare_digest(signature, expected):
                raise OAuthError("invalid sign-in state")
            body = _strict_json(SessionSigner._unb64(payload))
            stamp = int(time.time() if now is None else now)
            if (body.get("v") != 1 or type(body.get("exp")) is not int or type(body.get("iat")) is not int or
                    body["exp"] <= stamp or body["iat"] > stamp + 60):
                raise OAuthError("expired sign-in state")
            if body["exp"] - body["iat"] != self.ttl_seconds:
                raise OAuthError("invalid sign-in state lifetime")
            if not hmac.compare_digest(str(body.get("state") or ""), str(state or "")):
                raise OAuthError("sign-in state did not match")
            flow = OAuthFlow(str(body["state"]), str(body["nonce"]), str(body["verifier"]),
                             safe_next_path(body.get("next")))
            if not all(20 <= len(x) <= 256 for x in (flow.state, flow.nonce, flow.code_verifier)):
                raise OAuthError("invalid sign-in state")
            return flow
        except OAuthError:
            raise
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as ex:
            raise OAuthError("malformed sign-in state") from ex

    @staticmethod
    def cookie(token: str, secure: bool) -> str:
        attrs = [f"ds_oauth={token}", "Path=/auth/google/callback", "Max-Age=600", "HttpOnly", "SameSite=Lax"]
        if secure:
            attrs.append("Secure")
        return "; ".join(attrs)

    @staticmethod
    def clear_cookie(secure: bool) -> str:
        attrs = ["ds_oauth=", "Path=/auth/google/callback", "Max-Age=0", "HttpOnly", "SameSite=Lax"]
        if secure:
            attrs.append("Secure")
        return "; ".join(attrs)


def safe_next_path(value, default="/market") -> str:
    """Accept a same-origin absolute path, never a scheme-relative/external URL."""

    value = str(value or "")
    try:
        parsed = urlparse(value)
    except ValueError:
        return default
    if (not value.startswith("/") or value.startswith("//") or parsed.scheme or parsed.netloc or
            "\\" in value or any(ord(c) < 32 for c in value) or len(value) > 512):
        return default
    return value


def cookie_value(header: str | None, name: str) -> str | None:
    if not header or len(header) > 8192:
        return None
    try:
        jar = SimpleCookie()
        jar.load(header)
        return jar[name].value if name in jar else None
    except Exception:  # malformed cookies are treated as absent, never as identity
        return None


def new_oauth_flow(next_path="/market") -> OAuthFlow:
    verifier = secrets.token_urlsafe(48)
    return OAuthFlow(new_oauth_nonce(), new_oauth_nonce(), verifier, safe_next_path(next_path))


def _strict_json(raw: bytes | str):
    def object_pairs(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise OAuthError("duplicate JSON member")
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=object_pairs)


def _max_age(headers: Message | dict | None, default=3600) -> int:
    value = headers.get("Cache-Control", "") if headers else ""
    match = re.search(r"(?:^|,)\s*max-age=(\d+)", value, re.I)
    return max(60, min(int(match.group(1)), 86400)) if match else default


class GoogleOAuthClient:
    """Minimal Google web-server OAuth client with local RS256/JWK verification."""

    def __init__(self, config: GoogleOAuthConfig, opener=None):
        if not config.enabled:
            raise AccountConfigError("Google sign-in is not configured")
        self.config = config
        self._open = opener or urlopen
        self._jwks: dict[str, dict] = {}
        self._jwks_until = 0
        self._lock = threading.Lock()

    @property
    def secure_cookies(self) -> bool:
        return urlparse(self.config.redirect_uri).scheme == "https"

    def authorization_url(self, flow: OAuthFlow) -> str:
        challenge = SessionSigner._b64(hashlib.sha256(flow.code_verifier.encode()).digest())
        params = {"client_id": self.config.client_id, "redirect_uri": self.config.redirect_uri,
                  "response_type": "code", "scope": " ".join(self.config.scopes),
                  "state": flow.state, "nonce": flow.nonce, "code_challenge": challenge,
                  "code_challenge_method": "S256"}
        return GOOGLE_AUTHORIZATION_ENDPOINT + "?" + urlencode(params)

    def authenticate(self, code: str, flow: OAuthFlow, now: int | None = None) -> Account:
        if not code or len(code) > 4096 or any(c in code for c in "\r\n"):
            raise OAuthError("Google did not return a valid authorization code")
        form = urlencode({"code": code, "client_id": self.config.client_id,
                          "client_secret": self.config.client_secret,
                          "redirect_uri": self.config.redirect_uri,
                          "grant_type": "authorization_code", "code_verifier": flow.code_verifier}).encode()
        req = Request(GOOGLE_TOKEN_ENDPOINT, data=form, method="POST",
                      headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
        token = self._json_request(req, "Google token exchange failed")
        if token.get("token_type", "").lower() != "bearer" or not isinstance(token.get("id_token"), str):
            raise OAuthError("Google token response was incomplete")
        # Google reports email/profile under their long names too ("…/auth/userinfo.email"); those are the same grants, not extras.
        granted = {GOOGLE_SCOPE_ALIASES.get(s, s) for s in str(token.get("scope") or " ".join(self.config.scopes)).split()}
        if "openid" not in granted or not granted.issubset(set(self.config.scopes)):
            raise OAuthError("Google granted unexpected permissions")
        claims = self.verify_id_token(token["id_token"], flow.nonce, now=now)
        email = claims.get("email")
        if not isinstance(email, str) or claims.get("email_verified") is not True:
            raise OAuthError("Google account email is not verified")
        return google_account(claims["sub"], email, claims.get("name"))

    def verify_id_token(self, token: str, nonce: str, now: int | None = None) -> dict:
        if len(token) > 16384:
            raise OAuthError("Google ID token is too large")
        try:
            h64, p64, s64 = token.split(".")
            header = _strict_json(SessionSigner._unb64(h64))
            claims = _strict_json(SessionSigner._unb64(p64))
            signature = SessionSigner._unb64(s64)
        except OAuthError:
            raise
        except Exception as ex:
            raise OAuthError("Google ID token is malformed") from ex
        if not isinstance(header, dict) or not isinstance(claims, dict):
            raise OAuthError("Google ID token is malformed")
        if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str) or header.get("crit"):
            raise OAuthError("Google ID token uses an unsupported signature")
        if header.get("typ") not in (None, "JWT"):
            raise OAuthError("Google ID token has an invalid type")
        jwk = self._key(header["kid"], int(time.time() if now is None else now))
        self._verify_rs256((h64 + "." + p64).encode(), signature, jwk)
        self._verify_claims(claims, nonce, int(time.time() if now is None else now))
        return claims

    def _key(self, kid: str, now: int) -> dict:
        with self._lock:
            if now >= self._jwks_until or kid not in self._jwks:
                req = Request(GOOGLE_JWKS_ENDPOINT, headers={"Accept": "application/json"})
                doc, headers = self._json_request(req, "Google signing keys are unavailable", with_headers=True)
                keys = doc.get("keys") if isinstance(doc, dict) else None
                if not isinstance(keys, list):
                    raise OAuthError("Google signing-key response was invalid")
                self._jwks = {k["kid"]: k for k in keys if isinstance(k, dict) and isinstance(k.get("kid"), str)}
                self._jwks_until = now + _max_age(headers)
            key = self._jwks.get(kid)
        if not key:
            raise OAuthError("Google ID token signing key was not found")
        return key

    def _json_request(self, request: Request, message: str, with_headers=False):
        try:
            with self._open(request, timeout=10) as response:
                raw = response.read(1024 * 1024 + 1)
                if len(raw) > 1024 * 1024:
                    raise OAuthError(message)
                if getattr(response, "status", 200) != 200:
                    raise OAuthError(message)
                doc = _strict_json(raw)
                if not isinstance(doc, dict):
                    raise OAuthError(message)
                return (doc, response.headers) if with_headers else doc
        except OAuthError:
            raise
        except (HTTPError, URLError, OSError, TimeoutError, UnicodeError, json.JSONDecodeError) as ex:
            raise OAuthError(message) from ex

    @staticmethod
    def _verify_rs256(message: bytes, signature: bytes, jwk: dict):
        try:
            if jwk.get("kty") != "RSA" or jwk.get("use", "sig") != "sig" or jwk.get("alg", "RS256") != "RS256":
                raise OAuthError("Google signing key is not valid for RS256")
            n = int.from_bytes(SessionSigner._unb64(jwk["n"]), "big")
            exponent = int.from_bytes(SessionSigner._unb64(jwk["e"]), "big")
            size = (n.bit_length() + 7) // 8
            representative = int.from_bytes(signature, "big")
            if (not 2048 <= n.bit_length() <= 8192 or exponent < 3 or exponent > 2 ** 32 or
                    not exponent & 1 or len(signature) != size or representative >= n):
                raise OAuthError("Google signing key is invalid")
            actual = pow(representative, exponent, n).to_bytes(size, "big")
            digest = _SHA256_DIGEST_INFO + hashlib.sha256(message).digest()
            padding = b"\xff" * (size - len(digest) - 3)
            expected = b"\x00\x01" + padding + b"\x00" + digest
            if len(padding) < 8 or not hmac.compare_digest(actual, expected):
                raise OAuthError("Google ID token signature did not verify")
        except OAuthError:
            raise
        except (KeyError, TypeError, ValueError) as ex:
            raise OAuthError("Google signing key is malformed") from ex

    def _verify_claims(self, claims: dict, nonce: str, now: int):
        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise OAuthError("Google ID token issuer did not match")
        aud = claims.get("aud")
        audiences = [aud] if isinstance(aud, str) else aud if isinstance(aud, list) else []
        if self.config.client_id not in audiences or any(not isinstance(v, str) for v in audiences):
            raise OAuthError("Google ID token audience did not match")
        if (len(audiences) > 1 or claims.get("azp") is not None) and claims.get("azp") != self.config.client_id:
            raise OAuthError("Google ID token authorized party did not match")
        if type(claims.get("exp")) is not int or claims["exp"] <= now - 60:
            raise OAuthError("Google ID token expired")
        if type(claims.get("iat")) is not int or claims["iat"] > now + 60:
            raise OAuthError("Google ID token issue time is invalid")
        if not hmac.compare_digest(str(claims.get("nonce") or ""), str(nonce or "")):
            raise OAuthError("Google ID token nonce did not match")
        if not _SUB.fullmatch(str(claims.get("sub") or "")):
            raise OAuthError("Google ID token subject is invalid")


class AccountStore:
    """Small atomic profile store.  OAuth/provider tokens are never accepted or saved."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("MBOS_ACCOUNT_DATA_DIR") or
                         Path(__file__).resolve().parent.parent / "var" / "accounts")

    def _profile_path(self, account: Account) -> Path:
        return self.root / account.storage_key / "profile.json"

    def save_google_profile(self, account: Account) -> Path:
        if not account.authenticated or account.provider != "google":
            raise ValueError("profile must be a verified Google account")
        data = {"version": 1, "provider": "google", "subject": account.user_id,
                "email": account.email, "display_name": account.display_name}
        path = self._profile_path(account)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # ``mkdir(mode=...)`` is filtered by umask and does not tighten an
        # already-created directory.  Authenticated account directories hold
        # profile data and must never inherit a group/world-readable mode.
        path.parent.chmod(0o700)
        fd, temp = tempfile.mkstemp(dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, separators=(",", ":"), sort_keys=True)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp, path)
            path.chmod(0o600)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise
        return path

    def load_google_profile(self, subject: str) -> Account | None:
        probe = google_account(subject)
        try:
            data = json.loads(self._profile_path(probe).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if data.get("version") != 1 or data.get("provider") != "google" or data.get("subject") != subject:
            return None
        try:
            return google_account(subject, data.get("email"), data.get("display_name"))
        except ValueError:
            return None


def preference_path(local_path: str | Path, account: Account | None = None) -> Path:
    """Return the existing owner file or an isolated authenticated-user file."""

    account = account or current()
    local = Path(local_path)
    if account.user_id == LOCAL_OWNER_ID:
        return local
    root = Path(os.environ.get("MBOS_ACCOUNT_DATA_DIR") or local.parent / "accounts")
    return root / account.storage_key / "market_prefs.json"


def account_file_path(local_path: str | Path, filename: str, account: Account | None = None) -> Path:
    """Keep a legacy owner file while placing authenticated data in its account directory.

    ``local_path`` may be an existing deployment override.  It remains exact
    for Michael's local-owner mode, so this migration never moves or rewrites
    his data.  Authenticated users never share that override: only the
    server-derived :func:`current` account selects their opaque directory.
    """

    account = account or current()
    local = Path(local_path)
    if account.user_id == LOCAL_OWNER_ID:
        return local
    if not filename or Path(filename).name != filename:
        raise ValueError("account filename must be a plain filename")
    root = Path(os.environ.get("MBOS_ACCOUNT_DATA_DIR") or local.parent / "accounts")
    return root / account.storage_key / filename


def new_oauth_nonce() -> str:
    """A high-entropy state/nonce input for the future OAuth authorization route."""

    return secrets.token_urlsafe(32)
