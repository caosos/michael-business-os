"""Reviewed local-deal import seam used by the Marketplace.

This module does not fetch, scrape, publish a vendor submission, or contact a
business.  A trusted reviewer/import job may append an already-authorized
public or vendor-submitted offer.  The resulting records are always labelled
IMPORTED; only a separate, receipt-backed connector may ever claim LIVE.
"""

from __future__ import annotations

import fcntl
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import accounts, gazetteer, market_search as ms
from mbos_discovery.normalize import haversine_miles

SCHEMA = "dealsniffer.local_deal_import.v1"
SOURCE_KEY = "local_deals"
SOURCE_NAME = "Authorized local deals"
CATEGORIES = {
    "food_grocery": "Meat & Groceries",
    "restaurants": "Restaurants & Prepared Food",
    "fuel_auto": "Fuel & Automotive",
    "entertainment": "Entertainment & Tickets",
    "retail_services": "Retail & Local Services",
}
METHODS = ("vendor_submission", "public_offer")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,119}$")
_SOURCE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
_LOCK = threading.Lock()


def default_path(account: accounts.Account | None = None) -> Path:
    account = account or accounts.current()
    local = Path(os.environ.get("MBOS_LOCAL_DEALS_FILE") or
                 Path(__file__).resolve().parent.parent / "var" / "local_deals.jsonl")
    return accounts.account_file_path(local, "local_deals.jsonl", account)


def _text(value, name: str, limit: int, required: bool = True) -> str:
    out = " ".join(str(value or "").split())[:limit]
    if required and not out:
        raise ValueError(f"{name} is required")
    return out


def _stamp(value, name: str) -> tuple[str, datetime]:
    raw = _text(value, name, 40)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(f"{name} must be an ISO-8601 timestamp") from None
    if dt.tzinfo is None:
        raise ValueError(f"{name} must include a timezone")
    dt = dt.astimezone(timezone.utc)
    return dt.isoformat().replace("+00:00", "Z"), dt


def _url(value, name: str, required: bool = True) -> str | None:
    raw = _text(value, name, 1000, required)
    if not raw:
        return None
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https") or not parts.hostname or parts.username or parts.password:
        raise ValueError(f"{name} must be one public http(s) URL without credentials")
    return raw


def _money(value, name: str, required: bool = False) -> float | None:
    raw = _text(value, name, 30, required)
    if not raw:
        return None
    try:
        amount = float(raw.replace("$", "").replace(",", ""))
    except ValueError:
        raise ValueError(f"{name} must be a number") from None
    if not 0 <= amount <= 100_000_000:
        raise ValueError(f"{name} is outside the supported range")
    return round(amount, 2)


def normalize(payload: dict, imported_at: str, import_id: str,
              *, account: accounts.Account | None = None) -> dict:
    """Validate one reviewer-supplied offer and return its append-only record."""
    account = account or accounts.current()
    if not _ID.fullmatch(str(import_id or "")):
        raise ValueError("import id is invalid")
    imported_s, imported_dt = _stamp(imported_at, "imported at")
    observed_s, observed_dt = _stamp(payload.get("observed_at"), "observed at")
    expires_s, expires_dt = _stamp(payload.get("expires_at"), "expires at")
    if observed_dt > imported_dt:
        raise ValueError("observed at cannot be after imported at")
    if expires_dt <= imported_dt:
        raise ValueError("expired offers cannot be imported")
    method = str(payload.get("method") or "")
    if method not in METHODS:
        raise ValueError("method must be vendor_submission or public_offer")
    category = str(payload.get("category") or "")
    if category not in CATEGORIES:
        raise ValueError("category is not an everyday local-deal category")
    source_id = str(payload.get("source_id") or "")
    if not _SOURCE.fullmatch(source_id):
        raise ValueError("source id must be a lowercase stable key")
    source_url = _url(payload.get("source_url"), "source URL", method == "public_offer")
    vendor_submission_id = _text(payload.get("vendor_submission_id"), "vendor submission id", 120, method == "vendor_submission") or None
    if method == "vendor_submission" and payload.get("authority_attested") is not True:
        raise ValueError("vendor submissions require recorded authority attestation")
    deal_price = _money(payload.get("deal_price"), "deal price", True)
    regular_price = _money(payload.get("regular_price"), "regular price")
    if regular_price is not None and regular_price < deal_price:
        raise ValueError("regular price cannot be lower than deal price")
    return {
        "schema": SCHEMA,
        "import_id": import_id,
        "account_key": account.storage_key,
        "state": "IMPORTED",
        "imported_at": imported_s,
        "source": {
            "id": source_id,
            "name": _text(payload.get("source_name"), "source name", 160),
            "class": _text(payload.get("source_class"), "source class", 80),
            "geography": _text(payload.get("geography"), "geography", 160),
            "retrieval_path": "vendor submission" if method == "vendor_submission" else "authorized public offer",
        },
        "offer": {
            "source_offer_id": _text(payload.get("source_offer_id"), "source offer id", 160),
            "title": _text(payload.get("title"), "title", 180),
            "category": category,
            "description": str(payload.get("description") or "").strip()[:3000],
            "deal_price_usd": deal_price,
            "regular_price_usd": regular_price,
            "unit": _text(payload.get("unit"), "unit", 60),
            "location": _text(payload.get("location"), "location", 160),
            "availability": _text(payload.get("availability"), "availability", 300),
            "terms": str(payload.get("terms") or "").strip()[:1500],
            "observed_at": observed_s,
            "expires_at": expires_s,
        },
        "provenance": {
            "method": method,
            "original_url": source_url,
            "vendor_submission_id": vendor_submission_id,
            "authority_attested": True if method == "vendor_submission" else None,
            "recorded_at": imported_s,
            "recorded_by": account.audit_actor,
        },
    }


class Store:
    """Account-scoped append-only journal of reviewed imports."""

    def __init__(self, path=None):
        self._local_path = Path(path) if path else None

    def _path(self, account: accounts.Account) -> Path:
        if self._local_path is None:
            return default_path(account)
        return accounts.account_file_path(self._local_path, self._local_path.name, account)

    @property
    def path(self) -> Path:
        return self._path(accounts.current())

    def append(self, record: dict, account: accounts.Account | None = None) -> None:
        account = account or accounts.current()
        if record.get("schema") != SCHEMA or record.get("account_key") != account.storage_key or record.get("state") != "IMPORTED":
            raise ValueError("local deal import does not belong to the active account")
        path = self._path(account)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        payload = (json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n").encode()
        with _LOCK:
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(path, flags, 0o600)
            try:
                os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX)
                remaining = memoryview(payload)
                while remaining:
                    written = os.write(fd, remaining)
                    if written <= 0:
                        raise OSError("local deal journal write did not make progress")
                    remaining = remaining[written:]
                os.fsync(fd)
            finally:
                os.close(fd)

    def rows(self, account: accounts.Account | None = None) -> list[dict]:
        account = account or accounts.current()
        try:
            lines = self._path(account).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("schema") == SCHEMA and row.get("account_key") == account.storage_key and row.get("state") == "IMPORTED":
                out.append(row)
        return out

    def active(self, now: datetime, account: accounts.Account | None = None) -> list[dict]:
        now = now.astimezone(timezone.utc)
        out = []
        for row in self.rows(account):
            try:
                expiry = datetime.fromisoformat(row["offer"]["expires_at"].replace("Z", "+00:00"))
            except (KeyError, TypeError, ValueError):
                continue
            if expiry > now:
                out.append(row)
        return out


def probe(now: datetime, store: Store | None = None) -> dict:
    store = store or Store()
    rows, active = store.rows(), store.active(now)
    latest = max((r.get("imported_at") for r in rows), default=None)
    age = ms._age_h(latest, now) if latest else None
    return {"status": "imported" if active else "offline", "as_of": latest,
            "age_h": round(age, 1) if age is not None else None, "stale": False,
            "n": len(active), "expired": len(rows) - len(active)}


def card(row: dict, origin=None) -> dict:
    offer, source = row["offer"], row["source"]
    zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\b", offer.get("location") or "")
    zip_code = zip_match.group(1) if zip_match else None
    point = gazetteer.locate(zip_code) or gazetteer.locate(offer.get("location"))
    title = offer["title"]
    desc = " · ".join(x for x in (source.get("name"), offer.get("description"), offer.get("availability")) if x)
    loc = offer.get("location") or ""
    state_match = re.search(r"(?:,|\s)\s*([A-Za-z]{2})(?:\s+\d{5})?$", loc)
    state = state_match.group(1).upper() if state_match and state_match.group(1).upper() in ms.US_STATES else None
    provenance = row.get("provenance") or {}
    return {"id": f"local:{row['import_id']}", "title": title, "description": desc, "text": f"{title} {desc}".lower(),
            "url": provenance.get("original_url"), "image": None, "bid": None, "price": offer["deal_price_usd"], "price_type": "fixed",
            "bidders": None, "closes": offer["expires_at"][:10], "closes_at": offer["expires_at"], "city": loc, "state": state,
            "zip": zip_code, "posted": offer["observed_at"][:10], "distance": haversine_miles(origin, point) if origin and point else None,
            "category": CATEGORIES[offer["category"]], "condition": None, "labels": ms.auction_labels({}), "source": SOURCE_NAME,
            "source_key": SOURCE_KEY, "fetched_at": row["imported_at"], "kind": "fixed", "stale": False,
            "provenance": provenance, "business_name": source.get("name"), "availability": offer.get("availability"),
            "terms": offer.get("terms"), "unit": offer.get("unit"), "regular_price": offer.get("regular_price_usd")}


def load(now: datetime, origin=None, store: Store | None = None) -> dict:
    store = store or Store()
    pr = probe(now, store)
    cards = [card(row, origin) for row in store.active(now)]
    return {"name": SOURCE_NAME, "status": pr["status"], "as_of": pr["as_of"], "age_h": pr["age_h"], "stale": False,
            "in_scope": len(cards), "in_file": pr["n"] + pr["expired"], "cards": cards,
            "message": "Reviewed imports only; no vendor feed is connected.", "fixture": False}
