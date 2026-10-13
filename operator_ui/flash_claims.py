"""Deterministic, account-scoped first-N flash claims.

This module deliberately has no random prize, payment, bid, messaging, or
outreach path.  A JSONL journal is locked across processes and every state
change is a hash-linked receipt.  The journal is derived into current deal
state rather than updated in place.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import secrets
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import accounts
from .ux import InputError

SCHEMA = "dealsniffer.flash_claim_receipt.v1"
LOCAL_TZ = ZoneInfo("America/Chicago")
_ZERO_HASH = "sha256:" + "0" * 64
_LOCK = threading.Lock()


def default_path(account: accounts.Account | None = None) -> Path:
    account = account or accounts.current()
    local = Path(os.environ.get("MBOS_FLASH_CLAIMS_FILE") or
                 Path(__file__).resolve().parent.parent / "var" / "flash_claims.jsonl")
    return accounts.account_file_path(local, "flash_claims.jsonl", account)


def parse_time(value, field="time") -> datetime:
    """Parse a timestamp; browser-local values are interpreted in Conway time."""

    if isinstance(value, datetime):
        stamp = value
    else:
        raw = str(value or "").strip().replace("Z", "+00:00")
        try:
            stamp = datetime.fromisoformat(raw)
        except ValueError:
            raise InputError(f"{field} must be a real date and time") from None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=LOCAL_TZ)
    return stamp


def iso_time(value, field="time") -> str:
    return parse_time(value, field).isoformat(timespec="seconds")


def _whole(form: dict, key: str, low: int, high: int) -> int:
    try:
        value = int(str(form.get(key) or ""))
    except ValueError:
        raise InputError(f"{key.replace('_', ' ')} must be a whole number") from None
    if not low <= value <= high:
        raise InputError(f"{key.replace('_', ' ')} must be between {low} and {high}")
    return value


def _text(form: dict, key: str, limit: int, required=True) -> str:
    value = " ".join(str(form.get(key) or "").split())[:limit]
    if required and not value:
        raise InputError(f"{key.replace('_', ' ')} is required")
    return value


def parse_deal(form: dict, *, deal_id: str, created_at, account: accounts.Account | None = None) -> dict:
    """Validate a deterministic flash deal definition; randomness is absent."""

    account = account or accounts.current()
    starts = parse_time(form.get("starts_at"), "release time")
    ends = parse_time(form.get("claims_end_at"), "claim expiration")
    redeem = parse_time(form.get("redeem_by"), "redemption expiration")
    if not starts < ends:
        raise InputError("claim expiration must be after the release time")
    if redeem < ends:
        raise InputError("redemption expiration cannot be before claim expiration")
    return {
        "deal_id": _text({"deal_id": deal_id}, "deal_id", 100),
        "account_key": account.storage_key,
        "vendor": _text(form, "vendor", 160),
        "title": _text(form, "title", 180),
        "description": str(form.get("description") or "").strip()[:1500],
        "territory": _text(form, "territory", 180),
        "eligibility": _text(form, "eligibility", 300),
        "starts_at": starts.isoformat(timespec="seconds"),
        "claims_end_at": ends.isoformat(timespec="seconds"),
        "redeem_by": redeem.isoformat(timespec="seconds"),
        "claim_limit": _whole(form, "claim_limit", 1, 100_000),
        "waitlist_limit": _whole(form, "waitlist_limit", 0, 100_000),
        "created_at": iso_time(created_at, "created at"),
        "mode": "DETERMINISTIC_FIRST_N",
        "payment_required": False,
        "random_selection": False,
    }


def _hash(row: dict) -> str:
    body = {k: v for k, v in row.items() if k != "row_hash"}
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class Store:
    """Locked append-only receipt journal for one account at a time."""

    def __init__(self, path=None):
        self._local_path = Path(path) if path else None

    def _path(self, account: accounts.Account) -> Path:
        if self._local_path is None:
            return default_path(account)
        return accounts.account_file_path(self._local_path, self._local_path.name, account)

    @property
    def path(self) -> Path:
        return self._path(accounts.current())

    @contextmanager
    def _locked(self, account: accounts.Account, exclusive=True):
        path = self._path(account)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        with _LOCK:
            fd = os.open(path, flags, 0o600)
            try:
                os.fchmod(fd, 0o600)
                fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
                os.lseek(fd, 0, os.SEEK_SET)
                raw = b""
                while True:
                    part = os.read(fd, 65536)
                    if not part:
                        break
                    raw += part
                rows = []
                for line in raw.decode("utf-8", "replace").splitlines():
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if row.get("schema") == SCHEMA and row.get("account_key") == account.storage_key:
                        rows.append(row)
                yield fd, rows
            finally:
                os.close(fd)

    @staticmethod
    def _emit(fd: int, rows: list[dict], event: str, deal_id: str, actor: str,
              occurred_at, account: accounts.Account, details: dict) -> dict:
        row = {
            "schema": SCHEMA,
            "receipt_id": "flashrcpt_" + secrets.token_hex(12),
            "event": event,
            "deal_id": deal_id,
            "account_key": account.storage_key,
            "actor": actor,
            "occurred_at": iso_time(occurred_at, "event time"),
            "details": details,
            "prev_hash": rows[-1]["row_hash"] if rows else _ZERO_HASH,
        }
        row["row_hash"] = _hash(row)
        payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
        os.lseek(fd, 0, os.SEEK_END)
        view = memoryview(payload)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("flash claim journal write did not make progress")
            view = view[written:]
        os.fsync(fd)
        rows.append(row)
        return row

    @staticmethod
    def _definition(rows: list[dict], deal_id: str) -> dict | None:
        event = next((r for r in rows if r["event"] == "FLASH_DEAL_CREATED" and r["deal_id"] == deal_id), None)
        return dict(event["details"]) if event else None

    @staticmethod
    def _deal(rows: list[dict], definition: dict, now) -> dict:
        deal_id = definition["deal_id"]
        events = [r for r in rows if r["deal_id"] == deal_id]
        awards = [r for r in events if r["event"] == "FLASH_CLAIM_AWARDED"]
        waiting = [r for r in events if r["event"] == "FLASH_CLAIM_WAITLISTED"]
        confirmations = [r for r in events if r["event"] == "FLASH_REDEMPTION_CONFIRMED"]
        stamp = parse_time(now)
        if stamp < parse_time(definition["starts_at"]):
            state = "SCHEDULED"
        elif stamp >= parse_time(definition["claims_end_at"]):
            state = "EXPIRED"
        elif len(awards) < definition["claim_limit"]:
            state = "OPEN"
        elif len(waiting) < definition["waitlist_limit"]:
            state = "WAITLIST"
        else:
            state = "CLAIMED_OUT"
        return {**definition, "state": state, "claimed": len(awards), "remaining": max(0, definition["claim_limit"] - len(awards)),
                "waitlisted": len(waiting), "confirmed": len(confirmations)}

    def create(self, definition: dict, account: accounts.Account | None = None) -> dict:
        account = account or accounts.current()
        if definition.get("account_key") != account.storage_key or definition.get("mode") != "DETERMINISTIC_FIRST_N":
            raise ValueError("flash deal does not belong to the active account")
        with self._locked(account) as (fd, rows):
            if self._definition(rows, definition["deal_id"]):
                raise InputError("that flash deal ID already exists")
            return self._emit(fd, rows, "FLASH_DEAL_CREATED", definition["deal_id"], account.audit_actor,
                              definition["created_at"], account, definition)

    def list(self, now, account: accounts.Account | None = None) -> list[dict]:
        account = account or accounts.current()
        with self._locked(account, exclusive=False) as (_, rows):
            definitions = [r["details"] for r in rows if r["event"] == "FLASH_DEAL_CREATED"]
            return [self._deal(rows, d, now) for d in reversed(definitions)]

    def claim(self, deal_id: str, now, person_key: str, account: accounts.Account | None = None) -> dict:
        account = account or accounts.current()
        person = str(person_key or "").strip()
        if not person or len(person) > 160:
            raise InputError("a verified claimant identity is required")
        with self._locked(account) as (fd, rows):
            definition = self._definition(rows, deal_id)
            if not definition:
                raise InputError("flash deal not found")
            prior = next((r for r in rows if r["deal_id"] == deal_id and r["event"] in
                          ("FLASH_CLAIM_AWARDED", "FLASH_CLAIM_WAITLISTED") and
                          r["details"].get("person_key") == person), None)
            if prior:
                return {"status": "CLAIMED" if prior["event"].endswith("AWARDED") else "WAITLISTED",
                        "receipt": prior, "idempotent": True}
            deal = self._deal(rows, definition, now)
            if deal["state"] in ("SCHEDULED", "EXPIRED", "CLAIMED_OUT"):
                receipt = self._emit(fd, rows, "FLASH_CLAIM_DECLINED", deal_id, person, now, account,
                                     {"person_key": person, "reason": deal["state"]})
                return {"status": deal["state"], "receipt": receipt, "idempotent": False}
            if deal["state"] == "WAITLIST":
                receipt = self._emit(fd, rows, "FLASH_CLAIM_WAITLISTED", deal_id, person, now, account,
                                     {"person_key": person, "position": deal["waitlisted"] + 1})
                return {"status": "WAITLISTED", "receipt": receipt, "idempotent": False}
            used = {r["details"].get("redemption_token") for r in rows if r["event"] == "FLASH_CLAIM_AWARDED"}
            token = secrets.token_urlsafe(18)
            while token in used:
                token = secrets.token_urlsafe(18)
            receipt = self._emit(fd, rows, "FLASH_CLAIM_AWARDED", deal_id, person, now, account,
                                 {"person_key": person, "redemption_token": token,
                                  "redemption_expires_at": definition["redeem_by"]})
            return {"status": "CLAIMED", "token": token, "receipt": receipt, "idempotent": False}

    def confirm(self, token: str, now, account: accounts.Account | None = None) -> dict:
        account = account or accounts.current()
        code = str(token or "").strip()
        with self._locked(account) as (fd, rows):
            award = next((r for r in rows if r["event"] == "FLASH_CLAIM_AWARDED" and
                          secrets.compare_digest(str(r["details"].get("redemption_token") or ""), code)), None)
            if not award:
                raise InputError("redemption token was not found")
            prior = next((r for r in rows if r["event"] == "FLASH_REDEMPTION_CONFIRMED" and
                          r["details"].get("claim_receipt_id") == award["receipt_id"]), None)
            if prior:
                return {"status": "CONFIRMED", "receipt": prior, "idempotent": True}
            if parse_time(now) >= parse_time(award["details"]["redemption_expires_at"]):
                receipt = self._emit(fd, rows, "FLASH_REDEMPTION_DECLINED", award["deal_id"],
                                     account.audit_actor, now, account,
                                     {"claim_receipt_id": award["receipt_id"], "reason": "EXPIRED"})
                return {"status": "EXPIRED", "receipt": receipt, "idempotent": False}
            receipt = self._emit(fd, rows, "FLASH_REDEMPTION_CONFIRMED", award["deal_id"],
                                 account.audit_actor, now, account,
                                 {"claim_receipt_id": award["receipt_id"], "person_key": award["details"]["person_key"]})
            return {"status": "CONFIRMED", "receipt": receipt, "idempotent": False}

    def receipts(self, account: accounts.Account | None = None) -> list[dict]:
        account = account or accounts.current()
        with self._locked(account, exclusive=False) as (_, rows):
            return list(rows)

    def verify(self, account: accounts.Account | None = None) -> tuple[bool, str]:
        rows = self.receipts(account)
        previous = _ZERO_HASH
        for row in rows:
            if row.get("prev_hash") != previous or row.get("row_hash") != _hash(row):
                return False, row.get("receipt_id") or "unknown receipt"
            previous = row["row_hash"]
        return True, f"{len(rows)} receipts verified"
