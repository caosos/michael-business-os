"""Account-scoped, review-only intake for local-business deal offers.

Submitting an offer never publishes it.  A future reviewer/verification path may
promote an accepted offer into the Marketplace, but this module has no publish,
payment, messaging, or advertising effector.
"""

from __future__ import annotations

import fcntl
import html
import json
import os
import re
import threading
from datetime import date
from pathlib import Path

from . import accounts
from .sell_intake import _url
from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

CATEGORIES = (
    "Meat & groceries", "Restaurants & prepared food", "Fuel", "Automotive & oil changes",
    "Entertainment & tickets", "Retail products", "Local services", "Tools & equipment",
    "Trailers & vehicles", "Liquidation & wholesale", "Other local deal",
)
UNITS = ("each", "per pound", "per gallon", "per service", "per ticket", "per meal", "per lot", "other")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE = re.compile(r"^[0-9+().\-\s]{7,30}$")
_LOCK = threading.Lock()


def default_path(account: accounts.Account | None = None) -> Path:
    account = account or accounts.current()
    local = Path(os.environ.get("MBOS_VENDOR_DEALS_FILE") or
                 Path(__file__).resolve().parent.parent / "var" / "vendor_deals.jsonl")
    return accounts.account_file_path(local, "vendor_deals.jsonl", account)


def _text(form: dict, key: str, limit: int, required: bool = False) -> str:
    value = " ".join(str(form.get(key) or "").split())[:limit]
    if required and not value:
        raise InputError(f"{key.replace('_', ' ')} is required")
    return value


def _money(form: dict, key: str, required: bool = False) -> float | None:
    raw = _text(form, key, 30)
    if not raw and not required:
        return None
    try:
        amount = float(raw.replace("$", "").replace(",", ""))
    except ValueError:
        raise InputError(f"{key.replace('_', ' ')} must be a number") from None
    if amount < 0 or amount > 100_000_000:
        raise InputError(f"{key.replace('_', ' ')} is outside the supported range")
    return round(amount, 2)


def _date(form: dict, key: str, required: bool = False) -> str | None:
    raw = _text(form, key, 10)
    if not raw and not required:
        return None
    try:
        return date.fromisoformat(raw).isoformat()
    except ValueError:
        raise InputError(f"{key.replace('_', ' ')} must be a real date") from None


def parse(form: dict, created_at: str, submission_id: str,
          *, account: accounts.Account | None = None) -> dict:
    """Validate a submitter-stated offer.  It remains unpublished and unverified."""
    account = account or accounts.current()
    if str(form.get("authority_attestation") or "") != "yes":
        raise InputError("confirm that you are authorized to submit this business offer")
    if str(form.get("contact_permission") or "") != "yes":
        raise InputError("permission to contact you about this offer is required")
    if str(form.get("freshness_commitment") or "") != "yes":
        raise InputError("confirm that the price and availability will be kept current")
    email, phone = _text(form, "email", 254), _text(form, "phone", 30)
    if not email and not phone:
        raise InputError("enter an email address or phone number")
    if email and not _EMAIL.fullmatch(email):
        raise InputError("email address does not look valid")
    if phone and not _PHONE.fullmatch(phone):
        raise InputError("phone number does not look valid")
    category, unit = str(form.get("category") or ""), str(form.get("unit") or "")
    if category not in CATEGORIES:
        raise InputError("choose a deal category")
    if unit not in UNITS:
        raise InputError("choose a price unit")
    starts, expires = _date(form, "starts_on"), _date(form, "expires_on", required=True)
    if starts and expires and starts > expires:
        raise InputError("expiration date must be on or after the start date")
    price, regular = _money(form, "deal_price", required=True), _money(form, "regular_price")
    if regular is not None and regular < price:
        raise InputError("regular price cannot be lower than the deal price")
    return {
        "schema": "dealsniffer.vendor_deal_submission.v1",
        "submission_id": submission_id,
        "account_key": account.storage_key,
        "created_at": created_at,
        "status": "REVIEW_PENDING",
        "basis": "SUBMITTER_STATED",
        "published": False,
        "verified": False,
        "contact_attempted": False,
        "business": {
            "name": _text(form, "business_name", 160, required=True),
            "contact_name": _text(form, "contact_name", 120, required=True),
            "email": email or None,
            "phone": phone or None,
            "location": _text(form, "location", 160, required=True),
        },
        "offer": {
            "title": _text(form, "title", 180, required=True),
            "category": category,
            "description": str(form.get("description") or "").strip()[:3000],
            "deal_price_usd": price,
            "regular_price_usd": regular,
            "unit": unit,
            "starts_on": starts,
            "expires_on": expires,
            "availability": _text(form, "availability", 300, required=True),
            "terms": str(form.get("terms") or "").strip()[:1500],
            "source_url": _url(_text(form, "source_url", 1000), "offer link"),
        },
        "permissions": {
            "authority_attested": True,
            "contact_permission": True,
            "freshness_commitment": True,
            "scope": "THIS_OFFER",
            "recorded_at": created_at,
        },
    }


class Store:
    """Private append-only journal; it is not the public Marketplace feed."""

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
        if record.get("schema") != "dealsniffer.vendor_deal_submission.v1" or record.get("account_key") != account.storage_key:
            raise ValueError("offer does not belong to the active account")
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
                        raise OSError("vendor deal journal write did not make progress")
                    remaining = remaining[written:]
                os.fsync(fd)
            finally:
                os.close(fd)

    def recent(self, limit=20, account: accounts.Account | None = None) -> list[dict]:
        account = account or accounts.current()
        count = max(0, min(int(limit), 100))
        if count == 0:
            return []
        try:
            lines = self._path(account).read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        rows = []
        for line in lines:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("schema") == "dealsniffer.vendor_deal_submission.v1" and row.get("account_key") == account.storage_key:
                rows.append(row)
        return list(reversed(rows[-count:]))


def _options(values, chosen="") -> str:
    return "".join(f"<option{' selected' if x == chosen else ''}>{e(x)}</option>" for x in values)


def render_form(csrf: str, values: dict | None = None) -> str:
    v = values or {}
    val = lambda key: e(v.get(key, ""))  # noqa: E731
    return f"""<style>
.vendor-wrap{{max-width:920px;margin:auto}}.vendor-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}}.vendor-grid .wide{{grid-column:1/-1}}.vendor-form fieldset{{border:1px solid var(--line);border-radius:8px;margin:0 0 14px;padding:12px}}.vendor-note{{background:var(--warn);padding:10px;border-radius:8px}}@media(max-width:650px){{.vendor-grid{{grid-template-columns:1fr}}.vendor-grid .wide{{grid-column:auto}}}}
</style><div class='vendor-wrap'><p><a href='/sell'>Sell an item</a> · <a href='/market'>Browse deals</a></p><h1>Advertise a local deal</h1>
<p>Submit a current special for review. Examples: ground beef per pound, an oil change, pizza, movie tickets, fuel, tools, or a liquidation lot.</p>
<p class='vendor-note'><b>Review only.</b> Submitting does not publish or advertise the offer. DealSniffer must verify the business, price, dates, and availability first.</p>
<form method='post' action='/sell/deal/submit' class='vendor-form'><input type='hidden' name='csrf' value='{e(csrf)}'>
<fieldset><legend><b>Business and contact</b></legend><div class='vendor-grid'><label>Business name<input name='business_name' maxlength='160' value='{val('business_name')}' required></label><label>Your name<input name='contact_name' maxlength='120' value='{val('contact_name')}' required></label><label>Email<input type='email' name='email' maxlength='254' value='{val('email')}'></label><label>Phone<input type='tel' name='phone' maxlength='30' value='{val('phone')}'></label><label class='wide'>Business location<input name='location' maxlength='160' value='{val('location')}' placeholder='Street, city, state or ZIP' required></label></div></fieldset>
<fieldset><legend><b>The deal</b></legend><div class='vendor-grid'><label>Offer title<input name='title' maxlength='180' value='{val('title')}' placeholder='Example: Fresh ground beef' required></label><label>Category<select name='category' required><option value=''>Choose one</option>{_options(CATEGORIES, v.get('category', ''))}</select></label><label>Deal price<input name='deal_price' inputmode='decimal' value='{val('deal_price')}' placeholder='1.99' required></label><label>Price unit<select name='unit' required><option value=''>Choose one</option>{_options(UNITS, v.get('unit', ''))}</select></label><label>Regular price, if known<input name='regular_price' inputmode='decimal' value='{val('regular_price')}'></label><label>Available quantity or window<input name='availability' maxlength='300' value='{val('availability')}' placeholder='While supplies last; 200 lb available' required></label><label>Starts on<input type='date' name='starts_on' value='{val('starts_on')}'></label><label>Expires on<input type='date' name='expires_on' value='{val('expires_on')}' required></label><label class='wide'>Description<textarea name='description' maxlength='3000'>{val('description')}</textarea></label><label class='wide'>Terms or limits<textarea name='terms' maxlength='1500'>{val('terms')}</textarea></label><label class='wide'>Official offer or business link<input type='url' name='source_url' maxlength='1000' value='{val('source_url')}'></label></div></fieldset>
<fieldset><legend><b>Permission and freshness</b></legend><label><input type='checkbox' name='authority_attestation' value='yes'{' checked' if v.get('authority_attestation') == 'yes' else ''} required> I am authorized by this business to submit this offer.</label><label><input type='checkbox' name='contact_permission' value='yes'{' checked' if v.get('contact_permission') == 'yes' else ''} required> DealSniffer may contact me about this offer.</label><label><input type='checkbox' name='freshness_commitment' value='yes'{' checked' if v.get('freshness_commitment') == 'yes' else ''} required> I will keep the price, availability, and expiration current.</label></fieldset>
<button type='submit'>Send deal for review</button></form></div>"""


def render_recent(rows: list[dict]) -> str:
    if not rows:
        return "<section id='vendor-submissions'><h2>My deal submissions</h2><p>No deal submissions yet.</p></section>"
    cards = []
    for row in rows[:20]:
        offer, business = row["offer"], row["business"]
        cards.append(f"<article class='card'><h3>{e(offer['title'])}</h3><p><b>${offer['deal_price_usd']:,.2f} {e(offer['unit'])}</b> · {e(business['name'])} · {e(business['location'])}</p><p>Expires {e(offer['expires_on'])} · <b>REVIEW PENDING</b></p><p class='small mut'>Not published · not verified · nobody contacted</p></article>")
    return f"<section id='vendor-submissions'><h2>My deal submissions</h2>{''.join(cards)}</section>"
