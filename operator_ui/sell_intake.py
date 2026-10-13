"""Review-only, account-scoped owner/scout intake for DealSniffer.

The journal in this module records proposals and reviewer state changes. It has
no publication, messaging, auction, payment, or seller-contact effector.
"""

from __future__ import annotations

import fcntl
import hashlib
import html
import ipaddress
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from . import accounts
from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

ROLES = {
    "owner": "I own this item",
    "representative": "I am authorized by the owner",
    "scout": "I found a possible item (the owner has not signed up)",
}
AUTHORITY_STATEMENTS = {
    "owner": "I confirm that I own this item and may submit it for review.",
    "representative": "I confirm that the owner authorized me to submit this item for review.",
    "scout": "I understand this is only a lead; it does not authorize publication or owner contact.",
}
CONDITIONS = ("running/working", "needs repair", "not running", "unknown")
CATEGORIES = ("Farm equipment", "Tractor/implement", "Trailer", "Tools", "Lawn equipment", "Vehicle", "Machinery", "Other")
OUTCOMES = ("Auction", "Consignment", "Either / not sure")
REVIEW_STATES = ("REVIEW_PENDING", "NEEDS_INFORMATION", "ACCEPTED_FOR_DISCUSSION", "DECLINED", "WITHDRAWN")
_TRANSITIONS = {
    "REVIEW_PENDING": {"NEEDS_INFORMATION", "ACCEPTED_FOR_DISCUSSION", "DECLINED", "WITHDRAWN"},
    "NEEDS_INFORMATION": {"REVIEW_PENDING", "ACCEPTED_FOR_DISCUSSION", "DECLINED", "WITHDRAWN"},
    "ACCEPTED_FOR_DISCUSSION": {"NEEDS_INFORMATION", "DECLINED", "WITHDRAWN"},
    "DECLINED": set(),
    "WITHDRAWN": set(),
}
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE = re.compile(r"^[0-9+().\-\s]{7,30}$")
_UPLOAD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,199}$")
_PROVIDER = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_LOCK = threading.Lock()


def default_path(account: accounts.Account | None = None) -> Path:
    """Resolve storage at operation time so an authenticated account is isolated."""
    account = account or accounts.current()
    local = Path(os.environ.get("MBOS_SELL_INTAKE_FILE") or
                 Path(__file__).resolve().parent.parent / "var" / "sell_intake.jsonl")
    return accounts.account_file_path(local, "sell_intake.jsonl", account)


def _text(form: dict, key: str, limit: int, required: bool = False) -> str:
    value = " ".join(str(form.get(key) or "").split())[:limit]
    if required and not value:
        raise InputError(f"{key.replace('_', ' ')} is required")
    return value


def _url(value: str, label: str) -> str:
    """Validate a display-only public web link; the application never fetches it."""
    value = str(value or "").strip()
    if not value:
        return ""
    if len(value) > 1000 or any(ord(ch) < 32 for ch in value) or "\\" in value:
        raise InputError(f"{label} must be a safe http or https link")
    try:
        p = urlsplit(value)
        host = p.hostname
        port = p.port  # force invalid ports to fail here
    except ValueError:
        raise InputError(f"{label} must be a safe http or https link") from None
    if p.scheme.lower() not in ("http", "https") or not host or p.username or p.password:
        raise InputError(f"{label} must be a safe http or https link")
    host = host.rstrip(".").lower()
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".local", ".internal", ".localhost")):
        raise InputError(f"{label} must use a public host")
    try:
        ip = ipaddress.ip_address(host.strip("[]"))
    except ValueError:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except UnicodeError:
            raise InputError(f"{label} has an invalid host") from None
        if "." not in ascii_host or any(not part for part in ascii_host.split(".")):
            raise InputError(f"{label} must use a public host")
    else:
        if not ip.is_global:
            raise InputError(f"{label} must use a public host")
        ascii_host = f"[{host}]" if ip.version == 6 else host
    netloc = ascii_host + (f":{port}" if port is not None else "")
    return urlunsplit((p.scheme.lower(), netloc, p.path or "", p.query or "", p.fragment or ""))


def validate_upload_metadata(rows) -> list[dict]:
    """Validate receipts supplied by a future trusted upload adapter.

    This is a separate argument to :func:`parse`; browser form fields cannot
    claim that a storage provider accepted an upload.
    """
    if rows in (None, ""):
        return []
    if not isinstance(rows, list) or len(rows) > 12:
        raise InputError("photo upload metadata must be a list of at most 12 receipts")
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            raise InputError("each photo upload receipt must be an object")
        provider = str(row.get("provider") or "")
        upload_id = str(row.get("upload_id") or "")
        digest = str(row.get("sha256") or "").lower()
        content_type = str(row.get("content_type") or "").lower()
        name = Path(str(row.get("original_name") or "photo")).name[:160]
        try:
            size = int(row.get("size_bytes"))
        except (TypeError, ValueError):
            raise InputError("photo upload size is invalid") from None
        if not _PROVIDER.fullmatch(provider) or not _UPLOAD_ID.fullmatch(upload_id):
            raise InputError("photo upload receipt identity is invalid")
        if not _SHA256.fullmatch(digest):
            raise InputError("photo upload receipt requires a SHA-256 digest")
        if content_type not in {"image/jpeg", "image/png", "image/webp", "image/heic"}:
            raise InputError("photo upload type is not supported")
        if not 1 <= size <= 15 * 1024 * 1024:
            raise InputError("each uploaded photo must be 15 MB or smaller")
        clean.append({"provider": provider, "upload_id": upload_id, "original_name": name,
                      "content_type": content_type, "size_bytes": size, "sha256": digest,
                      "state": "RECEIPT_UNVERIFIED"})
    return clean


def parse(form: dict, created_at: str, submission_id: str, *, account: accounts.Account | None = None,
          upload_metadata=None) -> dict:
    """Validate one submission. Every claim remains submitter-stated and unverified."""
    account = account or accounts.current()
    role = str(form.get("relationship") or "")
    if role not in ROLES:
        raise InputError("choose whether you are the owner, an authorized representative, or a scout")
    if str(form.get("authority_attestation") or "") != "yes":
        raise InputError("confirm your ownership, authority, or scout-only role")
    if str(form.get("contact_permission") or "") != "yes":
        raise InputError("permission to contact you is required so we can respond about this submission")

    email = _text(form, "email", 254)
    phone = _text(form, "phone", 30)
    if not email and not phone:
        raise InputError("enter an email address or phone number")
    if email and not _EMAIL.match(email):
        raise InputError("email address does not look valid")
    if phone and not _PHONE.match(phone):
        raise InputError("phone number does not look valid")

    condition = str(form.get("condition") or "")
    if condition not in CONDITIONS:
        raise InputError("choose the item's condition")
    category = str(form.get("category") or "")
    if category not in CATEGORIES:
        raise InputError("choose an item category")
    outcome = str(form.get("desired_outcome") or "")
    if outcome not in OUTCOMES:
        raise InputError("choose auction, consignment, or not sure")

    photo_urls = []
    for raw in str(form.get("photo_urls") or "").splitlines():
        raw = raw.strip()
        if raw:
            photo_urls.append(_url(raw, "each photo"))
    photo_urls = list(dict.fromkeys(photo_urls))
    if len(photo_urls) > 8:
        raise InputError("add at most 8 photo links")

    asking = _text(form, "asking_price", 20)
    if asking:
        try:
            amount = float(asking.replace("$", "").replace(",", ""))
        except ValueError:
            raise InputError("asking price must be a number") from None
        if amount < 0 or amount > 100_000_000:
            raise InputError("asking price must be between $0 and $100,000,000")
        asking_price = round(amount, 2)
    else:
        asking_price = None

    owner_contact_permission = str(form.get("owner_contact_permission") or "") == "yes"
    owner_contact = _text(form, "owner_contact", 300)
    if owner_contact and not owner_contact_permission:
        raise InputError("only add an owner's contact details if that owner explicitly agreed to be contacted")
    if owner_contact_permission and not owner_contact:
        raise InputError("add the owner's contact details or clear the owner-contact permission box")

    return {
        "schema": "dealsniffer.sell_submission.v2",
        "submission_id": submission_id,
        "account_key": account.storage_key,
        "created_at": created_at,
        "updated_at": created_at,
        "status": "REVIEW_PENDING",
        "basis": "SUBMITTER_STATED",
        "published": False,
        "contact_attempted": False,
        "submitter": {
            "name": _text(form, "name", 120, required=True),
            "relationship": role,
            "email": email or None,
            "phone": phone or None,
            "contact_permission": {"granted": True, "scope": "THIS_SUBMISSION", "recorded_at": created_at},
        },
        "authority": {"attested": True, "role": role, "statement": AUTHORITY_STATEMENTS[role],
                      "recorded_at": created_at},
        "owner_contact_permission": owner_contact_permission,
        "owner_contact": owner_contact or None,
        "item": {
            "title": _text(form, "title", 160, required=True),
            "category": category,
            "description": str(form.get("description") or "").strip()[:3000],
            "condition": condition,
            "known_issues": str(form.get("known_issues") or "").strip()[:1500],
            "location": _text(form, "location", 160, required=True),
            "asking_price_usd": asking_price,
            "source_url": _url(_text(form, "source_url", 1000), "source link"),
            "photo_urls": photo_urls,
            "photo_uploads": validate_upload_metadata(upload_metadata),
        },
        "desired_outcome": outcome,
        "notes": str(form.get("notes") or "").strip()[:1500],
        "review_history": [{"at": created_at, "from": None, "to": "REVIEW_PENDING",
                            "actor": "system:intake", "note": "Submitted for human review"}],
    }


class Store:
    """Append-only per-account journal for submissions and review transitions."""

    def __init__(self, path=None):
        self._local_path = Path(path) if path else None

    def _path(self, account: accounts.Account) -> Path:
        if self._local_path is None:
            return default_path(account)
        return accounts.account_file_path(self._local_path, self._local_path.name, account)

    @property
    def path(self) -> Path:
        """Compatibility view of the active account's journal path."""
        return self._path(accounts.current())

    @staticmethod
    def _write(path: Path, row: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.parent.chmod(0o700)
        payload = (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
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
                        raise OSError("sell journal write did not make progress")
                    remaining = remaining[written:]
                os.fsync(fd)
            finally:
                os.close(fd)

    def append(self, record: dict, account: accounts.Account | None = None) -> None:
        account = account or accounts.current()
        if record.get("schema") != "dealsniffer.sell_submission.v2" or record.get("account_key") != account.storage_key:
            raise ValueError("submission does not belong to the active account")
        self._write(self._path(account), record)

    def _rows(self, account: accounts.Account) -> list[dict]:
        path = self._path(account)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(row, dict):
                continue
            # v1 rows predate accounts and are local-owner records only.
            if row.get("schema") == "dealsniffer.sell_intake.v1" and account.user_id == accounts.LOCAL_OWNER_ID:
                rows.append(row)
            elif row.get("account_key") == account.storage_key:
                rows.append(row)
        return rows

    def recent(self, limit=20, account: accounts.Account | None = None) -> list[dict]:
        account = account or accounts.current()
        count = max(0, min(int(limit), 1000))
        if count == 0:
            return []
        submissions: dict[str, dict] = {}
        order = []
        for row in self._rows(account):
            schema = row.get("schema")
            sid = row.get("submission_id")
            if not sid:
                continue
            if schema in {"dealsniffer.sell_submission.v2", "dealsniffer.sell_intake.v1"}:
                submissions[sid] = json.loads(json.dumps(row))
                order.append(sid)
            elif schema == "dealsniffer.sell_submission_event.v1" and sid in submissions:
                item = submissions[sid]
                item["status"] = row["to"]
                item["updated_at"] = row["created_at"]
                item.setdefault("review_history", []).append({k: row[k] for k in ("at", "from", "to", "actor", "note")})
        return [submissions[sid] for sid in reversed(order[-count:])]

    def get(self, submission_id: str, account: accounts.Account | None = None) -> dict | None:
        return next((row for row in self.recent(1000, account) if row.get("submission_id") == submission_id), None)

    def append_review(self, submission_id: str, to_state: str, reviewer: str, note: str, created_at: str,
                      account: accounts.Account | None = None) -> dict:
        account = account or accounts.current()
        current = self.get(submission_id, account)
        if current is None:
            raise InputError("submission was not found for this account")
        old = current.get("status")
        if to_state not in REVIEW_STATES or to_state not in _TRANSITIONS.get(old, set()):
            raise InputError(f"review state cannot move from {old} to {to_state}")
        actor = " ".join(str(reviewer or "").split())[:120]
        reason = " ".join(str(note or "").split())[:500]
        if not actor or not reason:
            raise InputError("reviewer and review note are required")
        row = {"schema": "dealsniffer.sell_submission_event.v1", "event_id": "sell-event-" + hashlib.sha256(
               f"{account.storage_key}\0{submission_id}\0{created_at}\0{to_state}\0{actor}\0{reason}".encode()).hexdigest()[:16],
               "account_key": account.storage_key, "submission_id": submission_id, "created_at": created_at,
               "at": created_at, "from": old, "to": to_state, "actor": actor, "note": reason,
               "published": False, "contact_attempted": False}
        self._write(self._path(account), row)
        return row


def _options(values, chosen="") -> str:
    return "".join(f"<option{' selected' if x == chosen else ''}>{e(x)}</option>" for x in values)


def render_form(csrf: str, values: dict | None = None) -> str:
    v = values or {}
    val = lambda key: e(v.get(key, ""))  # noqa: E731
    role = "".join(f"<label><input type='radio' name='relationship' value='{k}'{' checked' if v.get('relationship') == k else ''} required> {e(lbl)}<br><span class='small mut'>{e(AUTHORITY_STATEMENTS[k])}</span></label>" for k, lbl in ROLES.items())
    return f"""<style>
.sell-wrap{{max-width:920px;margin:auto}}.sell-hero{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.sell-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}}.sell-grid .wide{{grid-column:1/-1}}.sell-form fieldset{{border:1px solid var(--line);border-radius:8px;margin:0 0 14px;padding:12px}}.sell-form button{{background:var(--acc);max-width:280px}}.sell-note{{background:var(--warn);padding:10px;border-radius:8px}}.sell-card{{margin:12px 0}}.sell-state{{display:inline-block;padding:3px 8px;border:1px solid var(--line);border-radius:999px}}@media(max-width:650px){{.sell-grid{{grid-template-columns:1fr}}.sell-grid .wide{{grid-column:auto}}}}
</style><div class='sell-wrap'><div class='sell-hero'><div><h1>Sell with DealSniffer</h1><p>Tell us about equipment or other items that may be a fit for auction or consignment.</p></div><div><a href='/sell/submissions'>My submissions</a> · <a href='/market'>Marketplace</a></div></div>
<p class='sell-note'><b>Review only.</b> This form does not publish a listing, contact an owner, promise a sale, or start an auction. A person reviews every submission first.</p>
<form method='post' action='/sell/submit' class='sell-form'><input type='hidden' name='csrf' value='{e(csrf)}'>
<fieldset><legend><b>Who is submitting?</b></legend><div class='sell-grid'><div class='wide'>{role}</div><label>Your name<input name='name' maxlength='120' value='{val('name')}' required></label><label>Email<input type='email' name='email' maxlength='254' value='{val('email')}'></label><label>Phone<input type='tel' name='phone' maxlength='30' value='{val('phone')}'></label><label>How should we respond?<input value='Email or phone—whichever you provide' disabled></label><label class='wide'><input type='checkbox' name='authority_attestation' value='yes'{' checked' if v.get('authority_attestation') == 'yes' else ''} required> I confirm the ownership, authority, or scout-only statement that matches my selection above.</label><label class='wide'><input type='checkbox' name='contact_permission' value='yes'{' checked' if v.get('contact_permission') == 'yes' else ''} required> DealSniffer may contact me about this submission.</label></div></fieldset>
<fieldset><legend><b>Item</b></legend><div class='sell-grid'><label>Item name<input name='title' maxlength='160' value='{val('title')}' placeholder='Example: John Deere 4020 tractor' required></label><label>Category<select name='category' required><option value=''>Choose one</option>{_options(CATEGORIES, v.get('category', ''))}</select></label><label>City, state or ZIP<input name='location' maxlength='160' value='{val('location')}' placeholder='Conway, AR 72032' required></label><label>Condition<select name='condition' required><option value=''>Choose one</option>{_options(CONDITIONS, v.get('condition', ''))}</select></label><label>Asking price, if known<input inputmode='decimal' name='asking_price' maxlength='20' value='{val('asking_price')}' placeholder='2500'></label><label>What are you considering?<select name='desired_outcome' required><option value=''>Choose one</option>{_options(OUTCOMES, v.get('desired_outcome', ''))}</select></label><label class='wide'>Description<textarea name='description' maxlength='3000' placeholder='Make, model, year, hours, included attachments'>{val('description')}</textarea></label><label class='wide'>Known problems or missing parts<textarea name='known_issues' maxlength='1500' placeholder='Say “none known” or “unknown” if that is all you know'>{val('known_issues')}</textarea></label><label class='wide'>Public photo links, one per line (up to 8)<textarea name='photo_urls' maxlength='8000' placeholder='https://...'>{val('photo_urls')}</textarea><span class='small mut'>File uploads are not connected yet. Links are recorded for review and are never fetched automatically.</span></label><label class='wide'>Public listing or source link, if there is one<input type='url' name='source_url' maxlength='1000' value='{val('source_url')}'></label></div></fieldset>
<fieldset><legend><b>Owner permission</b></legend><p class='small mut'>A scout lead can be submitted without the owner's contact information. DealSniffer will not contact anyone automatically.</p><label><input type='checkbox' name='owner_contact_permission' value='yes'{' checked' if v.get('owner_contact_permission') == 'yes' else ''}> The owner explicitly agreed that DealSniffer may contact them.</label><label>Owner contact details (only when that box is checked)<textarea name='owner_contact' maxlength='300'>{val('owner_contact')}</textarea></label><label>Anything else for the reviewer?<textarea name='notes' maxlength='1500'>{val('notes')}</textarea></label></fieldset>
<button type='submit'>Send for human review</button></form></div>"""


def render_submissions(rows: list[dict], *, compact: bool = False) -> str:
    if not rows:
        return "<div class='sell-wrap' id='my-submissions'><h2>My submissions</h2><p>No submissions yet.</p></div>"
    cards = []
    for row in rows[:5 if compact else 50]:
        item = row.get("item") or {}
        history = row.get("review_history") or []
        state_label = str(row.get("status") or "UNKNOWN").replace("_", " ")
        hist = "" if compact else "<details><summary>Review history</summary><ol>" + "".join(
            f"<li><b>{e(h.get('to'))}</b> · {e(h.get('at'))}<br><span class='small mut'>{e(h.get('note'))}</span></li>" for h in history) + "</ol></details>"
        source = item.get("source_url")
        source_link = f" · <a href='{e(source)}' rel='noopener noreferrer'>source</a>" if source else ""
        cards.append(f"<article class='card sell-card'><h3>{e(item.get('title'))}</h3><p><span class='sell-state'>{e(state_label)}</span> · {e(item.get('location'))} · {e(row.get('desired_outcome'))}</p><p class='small mut'>Submission {e(row.get('submission_id'))} · submitted {e(row.get('created_at'))} · updated {e(row.get('updated_at') or row.get('created_at'))}{source_link}<br>{len(item.get('photo_urls') or [])} photo links · {len(item.get('photo_uploads') or [])} upload receipts · not published · nobody contacted</p>{hist}</article>")
    more = "<p><a href='/sell/submissions'>See all of my submissions</a></p>" if compact and len(rows) > 5 else ""
    return f"<div class='sell-wrap' id='my-submissions'><h2>My submissions</h2>{''.join(cards)}{more}</div>"


def render_recent(rows: list[dict]) -> str:
    """Compatibility wrapper used by the existing /sell route."""
    return render_submissions(rows, compact=True) if rows else ""
