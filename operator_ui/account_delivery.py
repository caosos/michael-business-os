"""Per-account DealSniffer mailbox aliases and notification preferences.

This is deliberately a provider-neutral storage boundary.  It does not log in
to Google, Facebook, an auction site, or an e-mail provider, and it has no
field in which source credentials can be stored.  A future inbound provider
routes the generated addresses to DealSniffer and records its own proven
receipt through :func:`record_inbound_receipt`.

Aliases are opaque HMACs of the application's stable account id.  They never
contain a user's e-mail address or Google subject.  The HMAC secret is read
from an environment variable named by ``MBOS_INTAKE_ALIAS_SECRET_ENV``; it is
never written to the account file.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

PURPOSES = ("alerts", "contact")
EVENTS = ("new_match", "bid_changed", "closing_soon", "seller_message")
CADENCES = ("instant", "daily")
DEFAULT_EVENTS = ("new_match", "bid_changed", "closing_soon", "seller_message")
_DOMAIN = re.compile(r"(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


@dataclass(frozen=True)
class AliasConfig:
    """Configuration only; domain presence is not evidence that mail works."""

    domain: str | None
    secret: str | None

    @classmethod
    def from_env(cls) -> "AliasConfig":
        domain = (os.environ.get("MBOS_INTAKE_MAIL_DOMAIN") or "").strip().lower() or None
        secret_env = (os.environ.get("MBOS_INTAKE_ALIAS_SECRET_ENV") or "").strip()
        return cls(domain, os.environ.get(secret_env) if secret_env else None)

    def usable(self) -> bool:
        return bool(self.domain and _DOMAIN.fullmatch(self.domain) and self.secret and len(self.secret) >= 32)


def store_path() -> Path:
    return Path(os.environ.get("MBOS_ACCOUNT_DELIVERY_FILE") or Path(__file__).resolve().parent.parent / "var" / "account_delivery.json")


def _empty() -> dict:
    return {"schema": 1, "accounts": {}}


def load(path: Path | None = None) -> dict:
    try:
        doc = json.loads((path or store_path()).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return _empty()
    if not isinstance(doc, dict) or not isinstance(doc.get("accounts"), dict):
        return _empty()
    return {"schema": 1, "accounts": doc["accounts"]}


def _write(doc: dict, path: Path | None = None) -> None:
    target = path or store_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=".account-delivery-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, sort_keys=True)
        os.replace(tmp, target)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _account_id(value: str) -> str:
    value = str(value or "")
    if not value or len(value) > 200 or any(ord(c) < 33 for c in value):
        raise ValueError("invalid account id")
    return value


def alias_for(account_id: str, purpose: str, config: AliasConfig | None = None) -> str | None:
    """Return a stable, non-identifying address, or ``None`` when unconfigured."""
    account_id = _account_id(account_id)
    if purpose not in PURPOSES:
        raise ValueError("unknown mailbox purpose")
    config = config or AliasConfig.from_env()
    if not config.usable():
        return None
    digest = hmac.new(config.secret.encode(), f"v1:{purpose}:{account_id}".encode(), hashlib.sha256).digest()
    token = base64.b32encode(digest[:12]).decode().rstrip("=").lower()
    return f"{purpose}-{token}@{config.domain}"


def ensure_account(account_id: str, path: Path | None = None, config: AliasConfig | None = None) -> dict:
    """Create/update the delivery record without claiming provider connectivity."""
    account_id = _account_id(account_id)
    doc = load(path)
    old = doc["accounts"].get(account_id) if isinstance(doc["accounts"].get(account_id), dict) else {}
    aliases = {purpose: alias_for(account_id, purpose, config) for purpose in PURPOSES}
    prefs = old.get("notifications") if isinstance(old.get("notifications"), dict) else {}
    record = {
        "aliases": aliases,
        "mailbox": old.get("mailbox") if isinstance(old.get("mailbox"), dict) else {},
        "notification_email": old.get("notification_email"),
        "notification_email_verified": bool(old.get("notification_email_verified")),
        "notifications": {
            "email_enabled": bool(prefs.get("email_enabled")) and bool(old.get("notification_email_verified")),
            "cadence": prefs.get("cadence") if prefs.get("cadence") in CADENCES else "instant",
            "events": [x for x in prefs.get("events", DEFAULT_EVENTS) if x in EVENTS],
        },
    }
    doc["accounts"][account_id] = record
    _write(doc, path)
    return record


def set_notification_preferences(account_id: str, email: str | None, enabled: bool,
                                 cadence: str = "instant", events=DEFAULT_EVENTS,
                                 path: Path | None = None) -> dict:
    """Save preferences. A changed address is unverified and therefore disabled."""
    if email is not None:
        email = email.strip().lower()
        if not _EMAIL.fullmatch(email) or len(email) > 254:
            raise ValueError("invalid notification e-mail")
    if cadence not in CADENCES:
        raise ValueError("invalid notification cadence")
    events = list(dict.fromkeys(events))
    if any(x not in EVENTS for x in events):
        raise ValueError("unknown notification event")
    doc = load(path)
    record = doc["accounts"].get(_account_id(account_id))
    if not isinstance(record, dict):
        record = ensure_account(account_id, path)
        doc = load(path)
    if email != record.get("notification_email"):
        record["notification_email_verified"] = False
    record["notification_email"] = email
    verified = bool(record.get("notification_email_verified"))
    record["notifications"] = {"email_enabled": bool(enabled and email and verified), "cadence": cadence, "events": events}
    doc["accounts"][account_id] = record
    _write(doc, path)
    return record


def record_email_verified(account_id: str, email: str, provider_receipt: str, verified_at: str,
                          path: Path | None = None) -> dict:
    """Persist external verification proof; the raw verification token is never stored."""
    doc = load(path)
    record = doc["accounts"].get(_account_id(account_id))
    if not isinstance(record, dict) or email.strip().lower() != record.get("notification_email"):
        raise ValueError("notification address does not match")
    if not provider_receipt or not verified_at:
        raise ValueError("verification provenance required")
    record["notification_email_verified"] = True
    record["email_verification"] = {"provider_receipt": str(provider_receipt)[:200], "verified_at": str(verified_at)[:40]}
    doc["accounts"][account_id] = record
    _write(doc, path)
    return record


def record_inbound_receipt(account_id: str, purpose: str, recipient: str, provider_receipt: str,
                           received_at: str, path: Path | None = None) -> dict:
    """Mark only one alias live after an actual provider-delivered message."""
    doc = load(path)
    record = doc["accounts"].get(_account_id(account_id))
    expected = (record or {}).get("aliases", {}).get(purpose) if purpose in PURPOSES else None
    if not expected or recipient.strip().lower() != expected.lower():
        raise ValueError("inbound recipient does not match this account alias")
    if not provider_receipt or not received_at:
        raise ValueError("inbound provenance required")
    record.setdefault("mailbox", {})[purpose] = {
        "last_provider_receipt": str(provider_receipt)[:200],
        "last_received_at": str(received_at)[:40],
    }
    doc["accounts"][account_id] = record
    _write(doc, path)
    return record


def status(account_id: str, purpose: str, path: Path | None = None,
           config: AliasConfig | None = None) -> dict:
    """Human-facing state. Configured DNS/domain alone never means connected."""
    if purpose not in PURPOSES:
        raise ValueError("unknown mailbox purpose")
    doc = load(path)
    record = doc["accounts"].get(_account_id(account_id)) or {}
    address = (record.get("aliases") or {}).get(purpose) or alias_for(account_id, purpose, config)
    proof = (record.get("mailbox") or {}).get(purpose)
    if proof and proof.get("last_provider_receipt") and proof.get("last_received_at"):
        state = "LIVE CONNECTED"
        detail = f"provider receipt at {proof['last_received_at']}"
    elif address:
        state = "NOT CONNECTED"
        detail = "address reserved; DNS/MX/provider routing has not produced a receipt"
    else:
        state = "NOT CONNECTED"
        detail = "mail domain and alias secret are not configured"
    return {"purpose": purpose, "address": address, "state": state, "detail": detail}

