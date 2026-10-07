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
from urllib.parse import urlsplit


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


class UrllibTransport:
    """Real network transport (stdlib). Only ever reached through ReadOnlyTransport."""

    def request(self, method, url, headers=None, body=None, timeout=20.0) -> HttpResponse:
        req = urllib.request.Request(url, data=body, method=method, headers=dict(headers or {}))
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
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
        self.log.append((method, url, resp.status))
        return resp


class CallbackTransport:
    """Offline transport: answers from a handler (fixtures, tests). Never touches the network."""

    def __init__(self, handler) -> None:
        self._handler = handler
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, headers=None, body=None, timeout=20.0) -> HttpResponse:
        self.calls.append((method, url))
        return self._handler(method, url, dict(headers or {}), body)
