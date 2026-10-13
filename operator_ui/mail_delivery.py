"""Provider-neutral mail routing and receipt evidence for DealSniffer.

This module is the boundary between a future mail provider adapter and the
application.  It deliberately makes no provider or DNS calls.  Provider
adapters must normalize webhook events into the small JSON envelope documented
by :class:`SignedReceiptVerifier`, then sign the *raw* envelope bytes.

Security properties:

* public aliases and delivery tokens are opaque and never contain account ids;
* raw mail, webhook signatures, shared secrets, and delivery tokens are never
  persisted;
* a mailbox remains ``NOT CONNECTED`` until a valid signed inbound receipt is
  accepted;
* notifications remain ``NOT ACTIVE`` until a valid signed successful delivery
  receipt is accepted for a registered delivery attempt; and
* receipt replays are idempotent.

The account key accepted here is ``accounts.Account.storage_key``: an already
opaque, non-PII application key.  It is returned only to trusted application
code after route resolution and is never included in public status results.
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


PURPOSES = ("alerts", "contact")
EVENTS = ("inbound.received", "delivery.delivered", "delivery.failed")
_ACCOUNT_KEY = re.compile(r"^[a-f0-9]{32}$")
_PROVIDER = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_RECEIPT_ID = re.compile(r"^[A-Za-z0-9._:@/+\-=]{1,200}$")
_ALIAS = re.compile(r"^(alerts|contact)-([a-z2-7]{20})@([a-z0-9.-]+)$")
_DELIVERY_TOKEN = re.compile(r"^dlv_[A-Za-z0-9_-]{32,120}$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class ReceiptError(ValueError):
    """A receipt is malformed, unauthenticated, expired, or unroutable."""


@dataclass(frozen=True)
class MailConfig:
    """Runtime secrets and limits.  ``repr`` never exposes secret material."""

    alias_domain: str
    alias_secret: bytes
    receipt_secret: bytes
    receipt_tolerance_seconds: int = 300

    def __post_init__(self) -> None:
        domain = self.alias_domain.strip().lower()
        if not re.fullmatch(r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", domain):
            raise ValueError("invalid mail alias domain")
        if len(self.alias_secret) < 32 or len(self.receipt_secret) < 32:
            raise ValueError("mail secrets must contain at least 32 bytes")
        if not 30 <= self.receipt_tolerance_seconds <= 3600:
            raise ValueError("receipt tolerance must be between 30 and 3600 seconds")
        object.__setattr__(self, "alias_domain", domain)

    def __repr__(self) -> str:
        return (f"MailConfig(alias_domain={self.alias_domain!r}, alias_secret=<redacted>, "
                f"receipt_secret=<redacted>, receipt_tolerance_seconds={self.receipt_tolerance_seconds})")

    @classmethod
    def from_env(cls, env=None) -> "MailConfig":
        env = os.environ if env is None else env
        domain = str(env.get("MBOS_INTAKE_MAIL_DOMAIN") or "").strip()
        alias_name = str(env.get("MBOS_INTAKE_ALIAS_SECRET_ENV") or "").strip()
        receipt_name = str(env.get("MBOS_MAIL_RECEIPT_SECRET_ENV") or "").strip()
        if not domain or not alias_name or not receipt_name:
            raise ValueError("mail domain and named alias/receipt secret variables are required")
        alias = str(env.get(alias_name) or "").encode()
        receipt = str(env.get(receipt_name) or "").encode()
        return cls(domain, alias, receipt)


@dataclass(frozen=True)
class DeliveryRequest:
    """One-time material handed to a future provider adapter."""

    delivery_token: str
    destination: str
    test: bool
    created_at: str


@dataclass(frozen=True)
class AcceptedReceipt:
    """Minimal trusted result.  No raw payload or account id is exposed."""

    event: str
    duplicate: bool
    route_ref: str
    occurred_at: str
    test: bool


def _iso(value: object) -> str:
    text = str(value or "")
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ReceiptError("receipt occurred_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ReceiptError("receipt occurred_at must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_address(value: object) -> str:
    address = str(value or "").strip().lower()
    if len(address) > 254 or not _EMAIL.fullmatch(address):
        raise ValueError("invalid e-mail address")
    return address


def _account_key(value: object) -> str:
    key = str(value or "")
    if not _ACCOUNT_KEY.fullmatch(key):
        raise ValueError("account key must be an opaque storage key")
    return key


def _token_digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _receipt_key(provider: str, receipt_id: str) -> str:
    return hashlib.sha256(f"{provider}\0{receipt_id}".encode()).hexdigest()


def _address_fingerprint(address: str) -> str:
    return hashlib.sha256(address.encode()).hexdigest()


def _route_ref(account_key: str, config: MailConfig) -> str:
    digest = hmac.new(config.alias_secret, f"account:v1:{account_key}".encode(), hashlib.sha256).digest()
    return "acct_" + base64.urlsafe_b64encode(digest[:12]).decode().rstrip("=")


def alias_for(account_key: str, purpose: str, config: MailConfig) -> str:
    """Return a stable opaque alias containing no account identifier."""

    key = _account_key(account_key)
    if purpose not in PURPOSES:
        raise ValueError("unknown mailbox purpose")
    digest = hmac.new(config.alias_secret, f"alias:v1:{purpose}:{key}".encode(), hashlib.sha256).digest()
    token = base64.b32encode(digest[:12]).decode().rstrip("=").lower()
    return f"{purpose}-{token}@{config.alias_domain}"


class SignedReceiptVerifier:
    """Verify normalized provider events before any routing or persistence.

    Signature format is ``v1=<lowercase hex HMAC-SHA256>`` over
    ``<unix timestamp>.<raw body>``.  A provider-specific adapter can implement
    its own native signature verification first, then emit this internal signed
    envelope.  The signing timestamp prevents delayed replay; persistent receipt
    deduplication prevents in-window replay.
    """

    def __init__(self, config: MailConfig):
        self.config = config

    def sign_for_test(self, body: bytes, timestamp: int) -> str:
        """Deterministic helper for adapter contract tests; it sends no mail."""

        mac = hmac.new(self.config.receipt_secret, str(timestamp).encode() + b"." + body, hashlib.sha256)
        return "v1=" + mac.hexdigest()

    def verify(self, body: bytes, timestamp: str | int, signature: str,
               now: int | None = None) -> dict:
        if not isinstance(body, bytes) or not body or len(body) > 64 * 1024:
            raise ReceiptError("receipt body must be 1..65536 bytes")
        try:
            stamp = int(timestamp)
        except (TypeError, ValueError) as exc:
            raise ReceiptError("invalid receipt timestamp") from exc
        current = int(time.time() if now is None else now)
        if abs(current - stamp) > self.config.receipt_tolerance_seconds:
            raise ReceiptError("receipt timestamp is outside the acceptance window")
        if not re.fullmatch(r"v1=[a-f0-9]{64}", str(signature or "")):
            raise ReceiptError("invalid receipt signature format")
        expected = self.sign_for_test(body, stamp)
        if not hmac.compare_digest(signature, expected):
            raise ReceiptError("invalid receipt signature")
        try:
            event = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReceiptError("receipt body must be a JSON object") from exc
        if not isinstance(event, dict):
            raise ReceiptError("receipt body must be a JSON object")
        allowed = {"version", "event", "provider", "receipt_id", "occurred_at", "recipient",
                   "delivery_token", "test"}
        if set(event) - allowed:
            raise ReceiptError("receipt contains unsupported fields")
        if event.get("version") != 1 or event.get("event") not in EVENTS:
            raise ReceiptError("unsupported receipt version or event")
        provider = str(event.get("provider") or "")
        receipt_id = str(event.get("receipt_id") or "")
        if not _PROVIDER.fullmatch(provider) or not _RECEIPT_ID.fullmatch(receipt_id):
            raise ReceiptError("invalid provider or receipt id")
        event["provider"] = provider
        event["receipt_id"] = receipt_id
        event["occurred_at"] = _iso(event.get("occurred_at"))
        if not isinstance(event.get("test"), bool):
            raise ReceiptError("receipt test flag must be boolean")
        if event["event"] == "inbound.received":
            if "delivery_token" in event:
                raise ReceiptError("inbound receipt cannot contain a delivery token")
            try:
                event["recipient"] = _canonical_address(event.get("recipient"))
            except ValueError as exc:
                raise ReceiptError(str(exc)) from exc
        else:
            if "recipient" in event:
                raise ReceiptError("delivery receipt cannot contain a recipient")
            if not _DELIVERY_TOKEN.fullmatch(str(event.get("delivery_token") or "")):
                raise ReceiptError("delivery receipt requires an opaque delivery token")
        return event


class MailDeliveryStore:
    """Atomic local evidence store for aliases, attempts, and receipts."""

    def __init__(self, path: str | Path, config: MailConfig):
        self.path = Path(path)
        self.config = config
        self.verifier = SignedReceiptVerifier(config)

    @staticmethod
    def _empty() -> dict:
        return {"schema": 1, "routes": {}, "attempts": {}, "receipts": {}}

    def _load(self) -> dict:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._empty()
        if (not isinstance(doc, dict) or doc.get("schema") != 1 or
                any(not isinstance(doc.get(k), dict) for k in ("routes", "attempts", "receipts"))):
            raise ValueError("invalid mail delivery store")
        return doc

    def _write(self, doc: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temp = tempfile.mkstemp(prefix=".mail-delivery-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, separators=(",", ":"), sort_keys=True)
            os.replace(temp, self.path)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    def register_account(self, account_key: str) -> dict:
        """Register both aliases without claiming either one is connected."""

        key = _account_key(account_key)
        doc = self._load()
        addresses = {}
        for purpose in PURPOSES:
            address = alias_for(key, purpose, self.config)
            match = _ALIAS.fullmatch(address)
            assert match is not None
            token = match.group(2)
            old = doc["routes"].get(token) or {}
            doc["routes"][token] = {
                "account_key": key,
                "purpose": purpose,
                "address": address,
                "last_inbound": old.get("last_inbound"),
            }
            addresses[purpose] = address
        self._write(doc)
        return {"route_ref": _route_ref(key, self.config), "aliases": addresses,
                "state": "NOT CONNECTED"}

    def mailbox_status(self, account_key: str, purpose: str) -> dict:
        key = _account_key(account_key)
        if purpose not in PURPOSES:
            raise ValueError("unknown mailbox purpose")
        address = alias_for(key, purpose, self.config)
        route = self._load()["routes"].get(_ALIAS.fullmatch(address).group(2)) or {}
        proof = route.get("last_inbound") if route.get("account_key") == key else None
        connected = bool(proof and proof.get("receipt_key") and proof.get("occurred_at"))
        return {
            "purpose": purpose,
            "address": address,
            "state": "LIVE CONNECTED" if connected else "NOT CONNECTED",
            "last_proven_at": proof.get("occurred_at") if connected else None,
            "test": proof.get("test") if connected else None,
        }

    def create_delivery_attempt(self, account_key: str, destination: str, *, test: bool = True,
                                now: str | None = None, token: str | None = None) -> DeliveryRequest:
        """Register an attempt.  No send occurs and state remains ``NOT ACTIVE``."""

        key = _account_key(account_key)
        destination = _canonical_address(destination)
        created_at = _iso(now or datetime.now(timezone.utc).isoformat())
        token = token or "dlv_" + secrets.token_urlsafe(32)
        if not _DELIVERY_TOKEN.fullmatch(token):
            raise ValueError("invalid delivery token")
        digest = _token_digest(token)
        doc = self._load()
        if digest in doc["attempts"]:
            raise ValueError("delivery token already registered")
        doc["attempts"][digest] = {
            "account_key": key,
            "route_ref": _route_ref(key, self.config),
            "destination_fingerprint": _address_fingerprint(destination),
            "test": bool(test),
            "created_at": created_at,
            "state": "PENDING",
            "last_receipt": None,
        }
        self._write(doc)
        return DeliveryRequest(token, destination, bool(test), created_at)

    def notification_status(self, account_key: str) -> dict:
        key = _account_key(account_key)
        attempts = [a for a in self._load()["attempts"].values() if a.get("account_key") == key]
        delivered = [a for a in attempts if a.get("state") == "DELIVERED" and a.get("last_receipt")]
        newest = max(delivered, key=lambda a: a["last_receipt"]["occurred_at"]) if delivered else None
        return {
            "state": "ACTIVE" if newest else "NOT ACTIVE",
            "last_proven_at": newest["last_receipt"]["occurred_at"] if newest else None,
            "test": newest.get("test") if newest else None,
        }

    def accept_signed_receipt(self, body: bytes, timestamp: str | int, signature: str,
                              *, now: int | None = None) -> tuple[AcceptedReceipt, str]:
        """Validate, deduplicate, persist minimal proof, and return trusted routing.

        The second return value is the opaque account storage key for trusted
        application routing.  It must not be returned to the provider or placed
        in logs.  Receipt ids are stored only as SHA-256 keys.
        """

        event = self.verifier.verify(body, timestamp, signature, now)
        doc = self._load()
        receipt_key = _receipt_key(event["provider"], event["receipt_id"])
        event_fingerprint = hashlib.sha256(body).hexdigest()
        prior = doc["receipts"].get(receipt_key)
        if prior:
            if prior.get("event_fingerprint") != event_fingerprint:
                raise ReceiptError("provider receipt id was reused for a different event")
            result = AcceptedReceipt(prior["event"], True, prior["route_ref"],
                                     prior["occurred_at"], bool(prior["test"]))
            return result, prior["account_key"]

        if event["event"] == "inbound.received":
            match = _ALIAS.fullmatch(event["recipient"])
            if not match or match.group(3) != self.config.alias_domain:
                raise ReceiptError("receipt recipient is not a DealSniffer alias")
            route = doc["routes"].get(match.group(2))
            if not route or route.get("address") != event["recipient"] or route.get("purpose") != match.group(1):
                raise ReceiptError("receipt alias is not registered")
            account_key = route["account_key"]
            route_ref = _route_ref(account_key, self.config)
            route["last_inbound"] = {"receipt_key": receipt_key, "occurred_at": event["occurred_at"],
                                     "provider": event["provider"], "test": event["test"]}
        else:
            digest = _token_digest(event["delivery_token"])
            attempt = doc["attempts"].get(digest)
            if not attempt:
                raise ReceiptError("delivery token is not registered")
            if event["test"] != bool(attempt["test"]):
                raise ReceiptError("delivery receipt test flag does not match the attempt")
            account_key = attempt["account_key"]
            route_ref = attempt["route_ref"]
            attempt["state"] = "DELIVERED" if event["event"] == "delivery.delivered" else "FAILED"
            attempt["last_receipt"] = {"receipt_key": receipt_key, "occurred_at": event["occurred_at"],
                                       "provider": event["provider"], "event": event["event"]}

        doc["receipts"][receipt_key] = {
            "account_key": account_key,
            "route_ref": route_ref,
            "event": event["event"],
            "occurred_at": event["occurred_at"],
            "test": event["test"],
            "event_fingerprint": event_fingerprint,
        }
        self._write(doc)
        return AcceptedReceipt(event["event"], False, route_ref, event["occurred_at"], event["test"]), account_key
