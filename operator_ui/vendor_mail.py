"""Verified vendor/customer mail -> review-pending DealSniffer offers.

The provider-neutral pipeline accepts messages only after a mailbox adapter has
authenticated the envelope sender.  A sender must also be present in the
private verified-customer registry.  Accepted offers are appended to the
existing :mod:`vendor_deals` journal; they are never published directly.

The expected plain-text body starts with ``DEALSNIFFER DEAL`` and uses one
``Field: value`` per line.  Continuation lines are allowed for Description and
Terms.  This deliberate format keeps prices, units, dates, and availability
explicit instead of guessing them from advertising prose.
"""

from __future__ import annotations

import email.policy
import fcntl
import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import urlsplit

from . import accounts, vendor_deals
from .ux import InputError

REGISTRY_SCHEMA = "dealsniffer.vendor_customer_registry.v1"
QUARANTINE_SCHEMA = "dealsniffer.vendor_mail_quarantine.v1"
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_VENDOR = re.compile(r"^[a-z0-9][a-z0-9_-]{2,62}$")
_MESSAGE = re.compile(r"^<[^<>\r\n]{1,500}>$")
_ACCOUNT_KEY = re.compile(r"^[a-f0-9]{32}$")
_PROVIDER = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")
_LOCK = threading.Lock()

FIELD_MAP = {
    "title": "title", "product": "title", "category": "category",
    "deal price": "deal_price", "price": "deal_price", "unit": "unit",
    "regular price": "regular_price", "location": "location",
    "availability": "availability", "observed at": "observed_at",
    "starts on": "starts_on", "start date": "starts_on",
    "expires on": "expires_on", "expiration date": "expires_on",
    "description": "description", "terms": "terms",
    "original url": "source_url", "offer url": "source_url",
    "photo url": "photo_url", "image url": "photo_url",
}


class VendorMailError(ValueError):
    """A message cannot safely become a review-pending vendor offer."""


@dataclass(frozen=True)
class ImportResult:
    state: str
    reason: str | None
    vendor_id: str | None
    submission_id: str | None
    duplicate: bool = False


@dataclass(frozen=True)
class _AccountRoute:
    """Opaque route accepted by the existing account-scoped journal."""

    storage_key: str
    user_id: str = "verified-vendor-route"

    @property
    def audit_actor(self) -> str:
        return f"vendor:{self.storage_key}"


def _stamp(value: object, name: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError:
        raise VendorMailError(f"{name} must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise VendorMailError(f"{name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _address(value: object) -> str:
    out = str(value or "").strip().lower()
    if len(out) > 254 or not _EMAIL.fullmatch(out):
        raise VendorMailError("sender address is invalid")
    return out


def _public_url(value: str, name: str) -> str:
    if not value:
        return ""
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise VendorMailError(f"{name} must be a public http(s) URL")
    return value[:1000]


class VendorRegistry:
    """Private atomic registry: one approved sender -> one customer account."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("MBOS_VENDOR_REGISTRY_FILE") or
                         Path(__file__).resolve().parent.parent / "var" / "vendor_customers.json")

    def _load(self) -> dict:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema": REGISTRY_SCHEMA, "vendors": {}}
        except (OSError, json.JSONDecodeError) as exc:
            raise VendorMailError("vendor registry is unreadable") from exc
        if doc.get("schema") != REGISTRY_SCHEMA or not isinstance(doc.get("vendors"), dict):
            raise VendorMailError("vendor registry has an unsupported schema")
        return doc

    def _write(self, doc: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix=".vendor-registry-")
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, sort_keys=True, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            self.path.chmod(0o600)
        except BaseException:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    def register_verified(self, vendor_id: str, business_name: str, location: str,
                          sender: str, account: accounts.Account, *, verified_at: str,
                          proof_ref: str, authority_attested: bool,
                          contact_permission: bool, freshness_commitment: bool) -> dict:
        vendor_id = str(vendor_id or "").lower()
        if not _VENDOR.fullmatch(vendor_id):
            raise VendorMailError("vendor id must be a stable lowercase key")
        if not account.authenticated:
            raise VendorMailError("vendor must be linked to a verified customer account")
        sender = _address(sender)
        if not all((authority_attested, contact_permission, freshness_commitment)):
            raise VendorMailError("vendor authority, contact permission, and freshness commitment are required")
        verified_at = _stamp(verified_at, "verified at")
        proof_ref = " ".join(str(proof_ref or "").split())[:200]
        if not proof_ref:
            raise VendorMailError("verification proof reference is required")
        name = " ".join(str(business_name or "").split())[:160]
        place = " ".join(str(location or "").split())[:160]
        if not name or not place:
            raise VendorMailError("business name and location are required")
        with _LOCK:
            doc = self._load()
            for vid, current in doc["vendors"].items():
                for approved in current.get("senders", []):
                    if approved.get("email") == sender and (vid != vendor_id or current.get("account_key") != account.storage_key):
                        raise VendorMailError("sender is already assigned to another vendor/customer account")
            existing = doc["vendors"].get(vendor_id)
            if existing and existing.get("account_key") != account.storage_key:
                raise VendorMailError("vendor id is already assigned to another customer account")
            record = existing or {
                "vendor_id": vendor_id, "account_key": account.storage_key,
                "business_name": name, "location": place, "senders": [],
            }
            record.update({"business_name": name, "location": place})
            approved = {"email": sender, "state": "VERIFIED", "verified_at": verified_at,
                        "proof_ref": proof_ref, "authority_attested": True,
                        "contact_permission": True, "freshness_commitment": True}
            record["senders"] = [x for x in record.get("senders", []) if x.get("email") != sender] + [approved]
            doc["vendors"][vendor_id] = record
            self._write(doc)
            return json.loads(json.dumps(record))

    def lookup(self, sender: str) -> dict | None:
        try:
            sender = _address(sender)
        except VendorMailError:
            return None
        for record in self._load()["vendors"].values():
            for approved in record.get("senders", []):
                if approved.get("email") == sender and approved.get("state") == "VERIFIED":
                    if not _ACCOUNT_KEY.fullmatch(str(record.get("account_key") or "")):
                        raise VendorMailError("vendor registry contains an invalid account route")
                    return json.loads(json.dumps(record))
        return None


class QuarantineStore:
    """Append-only minimal evidence for mail that must never reach publishing."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or os.environ.get("MBOS_VENDOR_MAIL_QUARANTINE") or
                         Path(__file__).resolve().parent.parent / "var" / "vendor_mail_quarantine.jsonl")

    def append(self, *, reason: str, sender: str, message_id: str, received_at: str,
               provider: str, receipt_id: str, raw: bytes) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path.parent.chmod(0o700)
        row = {"schema": QUARANTINE_SCHEMA, "state": "QUARANTINED", "reason": reason,
               "sender": sender[:254] or None, "message_id": message_id[:500] or None,
               "received_at": received_at, "provider": provider[:40], "receipt_id": receipt_id[:200],
               "message_sha256": hashlib.sha256(raw).hexdigest(), "published": False}
        payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with _LOCK:
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(self.path, flags, 0o600)
            try:
                os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(fd, remaining)
                    if written <= 0:
                        raise OSError("vendor mail quarantine write did not make progress")
                    remaining = remaining[written:]
                os.fsync(fd)
            finally:
                os.close(fd)


def parse_body(body: str) -> dict:
    lines = body.replace("\r\n", "\n").split("\n")
    first = next((line.strip() for line in lines if line.strip()), "")
    if first.upper() != "DEALSNIFFER DEAL":
        raise VendorMailError("message must start with DEALSNIFFER DEAL")
    fields: dict[str, str] = {}
    current = None
    started = False
    for raw_line in lines:
        line = raw_line.strip()
        if not started:
            if line.upper() == "DEALSNIFFER DEAL":
                started = True
            continue
        if not line:
            continue
        if ":" in line:
            label, value = line.split(":", 1)
            key = FIELD_MAP.get(label.strip().lower())
            if key:
                fields[key], current = value.strip(), key
                continue
        if current in ("description", "terms"):
            fields[current] = (fields[current] + "\n" + line).strip()
        else:
            raise VendorMailError(f"unrecognized deal field: {line[:80]}")
    required = ("title", "category", "deal_price", "unit", "location", "availability",
                "observed_at", "starts_on", "expires_on")
    missing = [key.replace("_", " ") for key in required if not fields.get(key)]
    if missing:
        raise VendorMailError("missing required fields: " + ", ".join(missing))
    fields["source_url"] = _public_url(fields.get("source_url", ""), "original URL")
    fields["photo_url"] = _public_url(fields.get("photo_url", ""), "photo URL")
    fields["observed_at"] = _stamp(fields["observed_at"], "observed at")
    return fields


def _plain_body(message) -> str:
    part = message.get_body(preferencelist=("plain",))
    if part is None:
        raise VendorMailError("message requires a plain-text deal body")
    body = part.get_content()
    if not isinstance(body, str) or len(body.encode("utf-8")) > 128 * 1024:
        raise VendorMailError("message body is missing or too large")
    return body


def dkim_authenticated_sender(message, sender: str) -> bool:
    """Apply the existing alert-adapter trust rule to a registered vendor.

    The caller must read from DealSniffer's own mailbox so Authentication-
    Results is the receiving provider's evidence, not sender-supplied proof.
    """
    domain = sender.rsplit("@", 1)[-1].lower() if "@" in sender else ""
    if not domain:
        return False
    for header in message.get_all("Authentication-Results", []) or []:
        for match in re.finditer(r"dkim=(\w+)[^;]*?header\.d=([\w.\-]+)", str(header), re.IGNORECASE):
            signed = match.group(2).lower()
            if match.group(1).lower() == "pass" and (signed == domain or signed.endswith("." + domain)):
                return True
    return False


def _offer_identity(vendor_id: str, fields: dict) -> str:
    exact = {key: fields.get(key) for key in (
        "title", "category", "deal_price", "regular_price", "unit", "location",
        "availability", "observed_at", "starts_on", "expires_on", "terms", "source_url", "photo_url",
    )}
    payload = json.dumps([vendor_id, exact], sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


class VendorMailPipeline:
    def __init__(self, registry: VendorRegistry, offers: vendor_deals.Store,
                 quarantine: QuarantineStore):
        self.registry, self.offers, self.quarantine = registry, offers, quarantine

    def process(self, raw: bytes, *, received_at: str, provider: str, receipt_id: str,
                authenticated_sender: str | None) -> ImportResult:
        received_at = _stamp(received_at, "received at")
        if not _PROVIDER.fullmatch(str(provider or "")):
            raise VendorMailError("provider id is invalid")
        receipt_id = " ".join(str(receipt_id or "").split())[:200]
        if not receipt_id:
            raise VendorMailError("provider receipt id is required")
        if not isinstance(raw, bytes) or not raw or len(raw) > 512 * 1024:
            raise VendorMailError("mail must be 1..524288 bytes")
        message = BytesParser(policy=email.policy.default).parsebytes(raw)
        sender = (parseaddr(str(message.get("From") or ""))[1].lower()
                  if len(message.get_all("From", [])) == 1 else "")
        message_id = str(message.get("Message-ID") or "").strip()
        reason = None
        vendor = self.registry.lookup(sender)
        if not sender or authenticated_sender is None or sender != str(authenticated_sender).strip().lower():
            reason = "AUTHENTICATION_UNVERIFIED"
        elif vendor is None:
            reason = "UNKNOWN_OR_UNVERIFIED_SENDER"
        elif not _MESSAGE.fullmatch(message_id):
            reason = "MESSAGE_ID_MISSING_OR_INVALID"
        if reason:
            self.quarantine.append(reason=reason, sender=sender, message_id=message_id,
                                   received_at=received_at, provider=provider, receipt_id=receipt_id, raw=raw)
            return ImportResult("QUARANTINED", reason, vendor.get("vendor_id") if vendor else None, None)
        try:
            fields = parse_body(_plain_body(message))
            received_dt = datetime.fromisoformat(received_at.replace("Z", "+00:00"))
            observed_dt = datetime.fromisoformat(fields["observed_at"].replace("Z", "+00:00"))
            if observed_dt > received_dt:
                raise VendorMailError("observed at cannot be after mailbox receipt")
            if fields["expires_on"] < received_at[:10]:
                raise VendorMailError("expired offers cannot enter review")
            # vendor_deals owns category/unit/money/date validation.
            form = {**fields, "business_name": vendor["business_name"], "contact_name": "Verified vendor mailbox",
                    "email": sender, "phone": "", "location": fields["location"],
                    "authority_attestation": "yes", "contact_permission": "yes", "freshness_commitment": "yes"}
            message_key = hashlib.sha256(message_id.encode()).hexdigest()
            offer_identity = _offer_identity(vendor["vendor_id"], fields)
            submission_id = "mail-" + hashlib.sha256((vendor["vendor_id"] + "\0" + message_id).encode()).hexdigest()[:24]
            provenance = {"channel": "dedicated_vendor_mailbox", "provider": str(provider)[:40],
                          "receipt_id": str(receipt_id)[:200], "message_id": message_id,
                          "message_key": message_key, "message_sha256": hashlib.sha256(raw).hexdigest(),
                          "offer_identity": offer_identity, "authenticated_sender": sender,
                          "vendor_id": vendor["vendor_id"], "received_at": received_at}
            route = _AccountRoute(vendor["account_key"])
            record = vendor_deals.parse(form, received_at, submission_id, account=route, provenance=provenance)
            appended = self.offers.append_once(record, account=route)
            return ImportResult("REVIEW_PENDING" if appended else "DUPLICATE", None,
                                vendor["vendor_id"], submission_id, duplicate=not appended)
        except (VendorMailError, InputError, ValueError) as exc:
            self.quarantine.append(reason="MALFORMED_DEAL: " + str(exc)[:160], sender=sender, message_id=message_id,
                                   received_at=received_at, provider=provider, receipt_id=receipt_id, raw=raw)
            return ImportResult("QUARANTINED", "MALFORMED_DEAL", vendor["vendor_id"], None)

    def import_reader(self, reader, since: datetime, *, provider: str,
                      authentication, clock=lambda: datetime.now(timezone.utc)) -> list[ImportResult]:
        """Reuse the existing read-only mailbox reader interface; never send or mutate mail."""
        results = []
        for index, raw in enumerate(reader.messages(since)):
            message = BytesParser(policy=email.policy.default).parsebytes(raw)
            sender = parseaddr(str(message.get("From") or ""))[1].lower()
            authenticated = sender if authentication(message, sender) else None
            received = clock().astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
            receipt_id = f"{provider}:{hashlib.sha256(raw).hexdigest()}:{index}"
            results.append(self.process(raw, received_at=received, provider=provider,
                                        receipt_id=receipt_id, authenticated_sender=authenticated))
        return results


def reviewed_import_payload(record: dict, *, imported_at: str) -> dict:
    """Map an approved journal row into ``local_deal_sources.normalize`` input.

    Review code must still call ``local_deal_sources.normalize`` and append it;
    this function neither approves nor publishes anything.
    """
    if record.get("schema") != "dealsniffer.vendor_deal_submission.v1" or record.get("status") != "REVIEW_PENDING":
        raise VendorMailError("only a review-pending vendor submission can be reviewed")
    offer, business, provenance = record["offer"], record["business"], record.get("provenance") or {}
    if provenance.get("channel") != "dedicated_vendor_mailbox":
        raise VendorMailError("submission is not a verified mailbox import")
    starts = offer.get("starts_on") or offer["observed_at"][:10]
    category = {
        "Meat & groceries": "food_grocery", "Restaurants & prepared food": "restaurants",
        "Fuel": "fuel_auto", "Automotive & oil changes": "fuel_auto",
        "Entertainment & tickets": "entertainment", "Retail products": "retail_services",
        "Local services": "retail_services", "Liquidation & wholesale": "retail_services",
        "Tools & equipment": "retail_services", "Trailers & vehicles": "retail_services",
        "Other local deal": "retail_services",
    }[offer["category"]]
    return {"method": "vendor_submission", "source_id": provenance["vendor_id"],
            "source_name": business["name"], "source_class": "verified vendor customer",
            "geography": business["location"], "source_offer_id": record["submission_id"],
            "vendor_submission_id": record["submission_id"], "authority_attested": True,
            "title": offer["title"], "category": category, "description": offer.get("description"),
            "deal_price": offer["deal_price_usd"], "regular_price": offer.get("regular_price_usd"),
            "unit": offer["unit"], "location": business["location"], "availability": offer["availability"],
            "terms": offer.get("terms"), "observed_at": offer["observed_at"],
            "expires_at": offer["expires_on"] + "T23:59:59Z", "source_url": offer.get("source_url"),
            "starts_on": starts, "photo_url": offer.get("photo_url"), "reviewed_at": imported_at}
