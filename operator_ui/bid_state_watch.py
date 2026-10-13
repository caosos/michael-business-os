"""Source-neutral, receipt-backed live state for items in My Bids.

Adapters provide *observations* from either an authenticated source alert e-mail
or a user-authorized session.  This module deliberately has no sign-in, password,
cookie, bid-placement, or HTTP code.  An adapter can read an already authorized
session, but it must normalize its result before calling :meth:`BidWatchStore.apply`.

Material changes are append-only receipts and create an immediate notification
outbox receipt.  "Queued" is not "delivered"; a delivery adapter must separately
prove delivery.  Replaying the same source evidence is idempotent.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Iterable, Protocol

from . import accounts

STATES = ("WINNING", "OUTBID", "ENDED_WON", "ENDED_LOST", "UNKNOWN")
EVIDENCE_KINDS = ("AUTHENTICATED_EMAIL", "AUTHORIZED_SESSION")
ENDED = frozenset(("ENDED_WON", "ENDED_LOST"))
_ID = re.compile(r"^[A-Za-z0-9._:@/+-]{1,240}$")
_URL = re.compile(r"^https?://", re.I)


def _iso(value: object, field: str) -> str:
    text = str(value or "").strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _money(value: object, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value).replace("$", "").replace(",", "").strip()).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be a non-negative amount") from exc
    if amount < 0 or amount >= Decimal("1000000000"):
        raise ValueError(f"{field} must be a non-negative amount")
    return format(amount, "f")


@dataclass(frozen=True)
class BidObservation:
    listing_id: str
    source: str
    title: str
    url: str
    state: str
    observed_at: str
    evidence_kind: str
    evidence_id: str
    current_bid: object = None
    user_max_bid: object = None
    next_required_bid: object = None
    closes_at: str | None = None
    adapter: str = ""

    def normalized(self) -> dict:
        listing_id = str(self.listing_id or "").strip()
        evidence_id = str(self.evidence_id or "").strip()
        if not _ID.fullmatch(listing_id) or not _ID.fullmatch(evidence_id):
            raise ValueError("listing_id and evidence_id must be stable source identifiers")
        source, title = str(self.source or "").strip()[:80], str(self.title or "").strip()[:200]
        url = str(self.url or "").strip()[:500]
        if not source or not title or not _URL.match(url):
            raise ValueError("source, title, and an http(s) original link are required")
        if self.state not in STATES or self.evidence_kind not in EVIDENCE_KINDS:
            raise ValueError("unsupported bid state or evidence kind")
        if not str(self.adapter or "").strip():
            raise ValueError("adapter provenance is required")
        return {
            "listing_id": listing_id, "source": source, "title": title, "url": url,
            "state": self.state, "observed_at": _iso(self.observed_at, "observed_at"),
            "evidence_kind": self.evidence_kind, "evidence_id": evidence_id,
            "current_bid": _money(self.current_bid, "current_bid"),
            "user_max_bid": _money(self.user_max_bid, "user_max_bid"),
            "next_required_bid": _money(self.next_required_bid, "next_required_bid"),
            "closes_at": _iso(self.closes_at, "closes_at") if self.closes_at else None,
            "adapter": str(self.adapter).strip()[:100],
        }


class BidObservationAdapter(Protocol):
    """Contract for a pre-authorized reader.  No credential arguments exist."""

    adapter_name: str

    def observations(self, watches: dict, now: datetime) -> Iterable[BidObservation]: ...


def authenticated_email_observation(event: dict, *, user_max_bid=None, next_required_bid=None) -> BidObservation:
    """Normalize an event emitted by an authenticated source-email parser.

    The parser must have already authenticated the sender (for example DKIM plus
    a source allowlist).  An unverified message is rejected, not downgraded.
    """
    if event.get("authenticated") is not True:
        raise ValueError("source alert e-mail is not authenticated")
    state = {
        "winning": "WINNING", "outbid": "OUTBID", "won": "ENDED_WON",
        "lost": "ENDED_LOST", "closed_lost": "ENDED_LOST",
    }.get(str(event.get("event") or "").lower(), "UNKNOWN")
    provenance = event.get("provenance") if isinstance(event.get("provenance"), dict) else {}
    return BidObservation(
        listing_id=str(event.get("listing_id") or ""), source=str(event.get("source") or ""),
        title=str(event.get("title") or ""), url=str(event.get("url") or ""), state=state,
        observed_at=str(event.get("observed_at") or event.get("email_date") or ""),
        evidence_kind="AUTHENTICATED_EMAIL",
        evidence_id=str(provenance.get("message_id") or event.get("message_id") or ""),
        current_bid=event.get("current_bid"), user_max_bid=user_max_bid,
        next_required_bid=next_required_bid or event.get("next_required_bid"),
        closes_at=event.get("closes_at"), adapter=str(event.get("adapter") or "source_alert_email"),
    )


@dataclass(frozen=True)
class PollPolicy:
    interval_seconds: int | None
    priority: str
    reason: str


def poll_policy(watch: dict, now: datetime) -> PollPolicy:
    """Final fifteen minutes are high priority; ended items do not poll."""
    if watch.get("state") in ENDED:
        return PollPolicy(None, "NONE", "auction ended")
    raw = watch.get("closes_at")
    if not raw:
        return PollPolicy(300, "NORMAL", "closing time unknown")
    close = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    left = (close - now.astimezone(timezone.utc)).total_seconds()
    if left <= 0:
        return PollPolicy(15, "HIGH", "close passed; confirm final state")
    if left <= 120:
        return PollPolicy(15, "HIGH", "final two minutes")
    if left <= 900:
        return PollPolicy(30, "HIGH", "final fifteen minutes")
    if left <= 3600:
        return PollPolicy(120, "NORMAL", "closes within one hour")
    return PollPolicy(300, "NORMAL", "more than one hour remains")


def store_path() -> Path:
    base = Path(os.environ.get("MBOS_BID_STATE_FILE") or Path(__file__).resolve().parent.parent / "var" / "bid_state.json")
    return accounts.preference_path(base)


class BidWatchStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else store_path()

    @staticmethod
    def _empty() -> dict:
        return {"schema": 1, "watches": {}, "receipts": [], "seen_evidence": []}

    def load(self) -> dict:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self._empty()
        if doc.get("schema") != 1 or not isinstance(doc.get("watches"), dict) or not isinstance(doc.get("receipts"), list):
            raise ValueError("invalid bid-state store")
        doc.setdefault("seen_evidence", [])
        return doc

    def _write(self, doc: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temp = tempfile.mkstemp(prefix=".bid-state-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, separators=(",", ":"), sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except BaseException:
            try:
                os.unlink(temp)
            except OSError:
                pass
            raise

    @staticmethod
    def _receipt(doc: dict, event: str, at: str, listing_id: str, evidence: dict, details: dict) -> dict:
        seq = len(doc["receipts"]) + 1
        raw = json.dumps([seq, event, at, listing_id, evidence, details], separators=(",", ":"), sort_keys=True)
        receipt = {
            "receipt_id": "bidrcpt_" + hashlib.sha256(raw.encode()).hexdigest()[:20],
            "seq": seq, "event": event, "occurred_at": at, "listing_id": listing_id,
            "evidence": evidence, "details": details,
        }
        doc["receipts"].append(receipt)
        return receipt

    def apply(self, observation: BidObservation) -> dict:
        item = observation.normalized()
        doc = self.load()
        evidence_key = f"{item['evidence_kind']}:{item['source']}:{item['evidence_id']}"
        if evidence_key in doc["seen_evidence"]:
            return {"duplicate": True, "watch": doc["watches"].get(item["listing_id"]), "receipts": []}
        old = doc["watches"].get(item["listing_id"])
        if old and item["observed_at"] < old.get("last_verified_at", ""):
            raise ValueError("observation is older than the last verified state")
        watch = {
            "listing_id": item["listing_id"], "source": item["source"], "title": item["title"], "url": item["url"],
            "state": item["state"], "current_bid": item["current_bid"], "user_max_bid": item["user_max_bid"],
            "next_required_bid": item["next_required_bid"], "closes_at": item["closes_at"],
            "last_verified_at": item["observed_at"], "last_evidence_kind": item["evidence_kind"],
            "last_evidence_id": item["evidence_id"], "adapter": item["adapter"],
        }
        evidence = {"kind": item["evidence_kind"], "id": item["evidence_id"], "adapter": item["adapter"]}
        changed = [] if not old else [k for k in ("state", "current_bid", "user_max_bid", "next_required_bid", "closes_at") if old.get(k) != watch.get(k)]
        receipts = []
        event = "BID_WATCH_STARTED" if old is None else "BID_STATE_OBSERVED"
        if old and old.get("state") != watch["state"]:
            event = "BID_STATE_CHANGED"
        elif old and old.get("closes_at") and watch.get("closes_at") and watch["closes_at"] > old["closes_at"]:
            event = "BID_SOFT_CLOSE_EXTENDED"
        elif changed:
            event = "BID_SNAPSHOT_CHANGED"
        receipts.append(self._receipt(doc, event, item["observed_at"], item["listing_id"], evidence,
                                      {"before": old.get("state") if old else None, "after": watch["state"], "changed": changed}))
        material = old is None or bool(changed)
        if material:
            policy = poll_policy(watch, datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00")))
            receipts.append(self._receipt(doc, "BID_NOTIFICATION_QUEUED", item["observed_at"], item["listing_id"], evidence,
                                          {"delivery": "IMMEDIATE", "delivery_state": "QUEUED_NOT_DELIVERED",
                                           "priority": "HIGH" if watch["state"] in ("OUTBID", "ENDED_WON", "ENDED_LOST") else policy.priority,
                                           "state": watch["state"], "current_bid": watch["current_bid"],
                                           "next_required_bid": watch["next_required_bid"], "closes_at": watch["closes_at"]}))
        doc["watches"][item["listing_id"]] = watch
        doc["seen_evidence"].append(evidence_key)
        doc["seen_evidence"] = doc["seen_evidence"][-5000:]
        self._write(doc)
        return {"duplicate": False, "watch": watch, "receipts": receipts, "poll": asdict(poll_policy(watch, datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00"))))}

    def poll_adapter(self, adapter: BidObservationAdapter, now: datetime) -> list[dict]:
        """Run a bounded already-authorized adapter and apply its observations."""
        if now.tzinfo is None:
            raise ValueError("poll time must include a timezone")
        return [self.apply(observation) for observation in adapter.observations(self.load()["watches"], now)]
