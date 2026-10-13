"""Account boundary for DealSniffer's transition from one local owner to many users.

This module deliberately does not perform an OAuth callback or token exchange.  It
provides the security-sensitive primitives that those routes need: strict Google
configuration validation, opaque signed browser sessions, a request-local account
context, and an atomic profile store that never stores provider access tokens.

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
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

LOCAL_OWNER_ID = "local-owner"
GOOGLE_SCOPES = ("openid", "email", "profile")
_SUB = re.compile(r"^[A-Za-z0-9._:@+-]{1,255}$")


class AccountConfigError(ValueError):
    """The account feature was partly or unsafely configured."""


class InvalidSession(ValueError):
    """A browser session is malformed, expired, or has a bad signature."""


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
    if not uri.hostname or uri.username or uri.password or uri.fragment:
        raise AccountConfigError("Google redirect URI must be an absolute URL without credentials or a fragment")
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
        fd, temp = tempfile.mkstemp(dir=path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, separators=(",", ":"), sort_keys=True)
            os.replace(temp, path)
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


def new_oauth_nonce() -> str:
    """A high-entropy state/nonce input for the future OAuth authorization route."""

    return secrets.token_urlsafe(32)
