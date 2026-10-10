"""Read-only HTTP boundary.

Adapters never get a raw HTTP client. They get a `ReadOnlyTransport` that only permits
GET to allow-listed hosts, plus POST to explicitly allow-listed *token* endpoints (OAuth
client-credentials is a POST but has no external side effect). Anything else — a POST to
a listing, a PUT, a DELETE, an unknown host — raises `SideEffectRefused` before a byte
leaves the box. This is the structural guarantee behind "no side effects".
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Mapping, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class SideEffectRefused(Exception):
    """A request that could change state at a source was attempted and blocked."""


class TransportError(Exception):
    """Network-level failure (DNS, connect, timeout, TLS)."""


@dataclass(frozen=True)
class HttpResponse:
    status: int
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


class Transport(Protocol):
    def request(self, method: str, url: str, headers: Mapping[str, str] | None = None,
                body: bytes | None = None, timeout: float = 20.0) -> HttpResponse: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None          # surface 3xx to the caller so every hop passes the host allow-list


class UrllibTransport:
    """Real network transport (stdlib). Only ever reached through ReadOnlyTransport."""

    def __init__(self, follow_redirects: bool = True) -> None:
        self._opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirect)

    def request(self, method, url, headers=None, body=None, timeout=20.0) -> HttpResponse:
        req = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                return HttpResponse(resp.status, resp.read(), dict(resp.headers.items()))
        except urllib.error.HTTPError as e:
            return HttpResponse(e.code, e.read() or b"", dict(e.headers.items()) if e.headers else {})
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise TransportError(str(e)) from e


class ReadOnlyTransport:
    def __init__(self, inner: Transport, allowed_get_hosts: frozenset[str],
                 allowed_token_urls: frozenset[str] = frozenset()) -> None:
        self._inner = inner
        self._get_hosts = allowed_get_hosts
        self._token_urls = allowed_token_urls
        self.log: list[tuple[str, str, int]] = []

    def request(self, method, url, headers=None, body=None, timeout=20.0) -> HttpResponse:
        method = method.upper()
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise SideEffectRefused(f"non-https request refused: {url}")
        if method == "GET":
            if parts.hostname not in self._get_hosts:
                raise SideEffectRefused(f"GET to non-allow-listed host refused: {parts.hostname}")
        elif method == "POST":
            if f"{parts.scheme}://{parts.netloc}{parts.path}" not in self._token_urls:
                raise SideEffectRefused(f"POST refused (only OAuth token endpoints may be POSTed): {url}")
        else:
            raise SideEffectRefused(f"{method} refused: discovery is read-only")
        resp = self._inner.request(method, url, headers, body, timeout)
        self.log.append((method, redact(url), resp.status))
        return resp


class CallbackTransport:
    """Offline transport: answers from a handler (fixtures, tests). Never touches the network."""

    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, headers=None, body=None, timeout=20.0) -> HttpResponse:
        self.calls.append((method, url))
        return self._handler(method, url, dict(headers or {}), body)


SECRET_PARAMS = frozenset({"api_key", "apikey", "key", "token", "access_token", "client_secret"})


def redact(url: str) -> str:
    """URL safe to put in provenance, logs and receipts: secret query parameters removed."""
    p = urlsplit(url)
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if k.lower() not in SECRET_PARAMS]
    return urlunsplit((p.scheme, p.netloc, p.path, urlencode(q), p.fragment))


def status_error(r: HttpResponse, who: str):
    """Map an HTTP response to a SourceError (None when OK). 403/429/CAPTCHA are block signals."""
    from .adapter import SourceError
    if r.status < 300:
        if b"captcha" in r.body[:4096].lower() and not r.body.lstrip().startswith((b"{", b"[")):
            return SourceError("captcha", "CAPTCHA/challenge page returned instead of JSON", r.status)
        return None
    snippet = r.body[:300].decode("utf-8", "replace")
    if r.status == 429:
        return SourceError("rate_limited", f"429 from {who}: {snippet}", 429)
    if r.status == 403:
        return SourceError("blocked", f"403 from {who}: {snippet}", 403)
    if r.status in (401, 400):
        return SourceError("auth", f"{r.status} from {who}: {snippet}", r.status)
    return SourceError("http", f"HTTP {r.status}: {snippet}", r.status)
