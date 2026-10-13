"""Review-only owner/scout intake for items that may be sold through DealSniffer."""

from __future__ import annotations

import html
import json
import os
import re
import threading
from pathlib import Path
from urllib.parse import urlsplit

from . import market_prefs
from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

ROLES = {
    "owner": "I own this item",
    "representative": "I am authorized by the owner",
    "scout": "I found a possible item (the owner has not signed up)",
}
CONDITIONS = ("running/working", "needs repair", "not running", "unknown")
CATEGORIES = ("Farm equipment", "Tractor/implement", "Trailer", "Tools", "Lawn equipment", "Vehicle", "Machinery", "Other")
OUTCOMES = ("Auction", "Consignment", "Either / not sure")
_EMAIL = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_PHONE = re.compile(r"^[0-9+().\-\s]{7,30}$")
_LOCK = threading.Lock()


def default_path() -> Path:
    return Path(os.environ.get("MBOS_SELL_INTAKE_FILE") or market_prefs.path().parent / "sell_intake.jsonl")


def _text(form: dict, key: str, limit: int, required: bool = False) -> str:
    value = " ".join(str(form.get(key) or "").split())[:limit]
    if required and not value:
        raise InputError(f"{key.replace('_', ' ')} is required")
    return value


def _url(value: str, label: str) -> str:
    if not value:
        return ""
    try:
        p = urlsplit(value)
    except ValueError:
        raise InputError(f"{label} must be an http or https link") from None
    if p.scheme not in ("http", "https") or not p.netloc or p.username or p.password:
        raise InputError(f"{label} must be an http or https link")
    return value[:1000]


def parse(form: dict, created_at: str, submission_id: str) -> dict:
    """Validate one submission. Every claim remains submitter-stated and unverified."""
    role = str(form.get("relationship") or "")
    if role not in ROLES:
        raise InputError("choose whether you are the owner, an authorized representative, or a scout")
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

    return {
        "schema": "dealsniffer.sell_intake.v1",
        "submission_id": submission_id,
        "created_at": created_at,
        "status": "REVIEW_PENDING",
        "basis": "SUBMITTER_STATED",
        "published": False,
        "contact_attempted": False,
        "submitter": {
            "name": _text(form, "name", 120, required=True),
            "relationship": role,
            "email": email or None,
            "phone": phone or None,
            "contact_permission": True,
        },
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
        },
        "desired_outcome": outcome,
        "notes": str(form.get("notes") or "").strip()[:1500],
    }


class Store:
    """Small append-only local inbox. Corrections are new submissions; prior rows remain."""

    def __init__(self, path=None):
        self.path = Path(path) if path else default_path()

    def append(self, record: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n"
        with _LOCK:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()
                os.fsync(fh.fileno())

    def recent(self, limit=20) -> list[dict]:
        if not self.path.exists():
            return []
        rows = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(row, dict) and row.get("schema") == "dealsniffer.sell_intake.v1":
                rows.append(row)
        return rows[-limit:][::-1]


def _options(values, chosen="") -> str:
    return "".join(f"<option{' selected' if x == chosen else ''}>{e(x)}</option>" for x in values)


def render_form(csrf: str, values: dict | None = None) -> str:
    v = values or {}
    val = lambda key: e(v.get(key, ""))  # noqa: E731
    role = "".join(f"<label><input type='radio' name='relationship' value='{k}'{' checked' if v.get('relationship') == k else ''} required> {e(lbl)}</label>" for k, lbl in ROLES.items())
    return f"""<style>
.sell-wrap{{max-width:920px;margin:auto}}.sell-hero{{display:flex;justify-content:space-between;gap:12px;align-items:center}}.sell-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}}.sell-grid .wide{{grid-column:1/-1}}.sell-form fieldset{{border:1px solid var(--line);border-radius:8px;margin:0 0 14px;padding:12px}}.sell-form button{{background:var(--acc);max-width:280px}}.sell-note{{background:var(--warn);padding:10px;border-radius:8px}}@media(max-width:650px){{.sell-grid{{grid-template-columns:1fr}}.sell-grid .wide{{grid-column:auto}}}}
</style><div class='sell-wrap'><div class='sell-hero'><div><h1>Sell with DealSniffer</h1><p>Tell us about equipment or other items that may be a fit for auction or consignment.</p></div><a href='/market'>Back to Marketplace</a></div>
<p class='sell-note'><b>Review only.</b> This form does not publish a listing, contact an owner, promise a sale, or start an auction. A person reviews every submission first.</p>
<form method='post' action='/sell/submit' class='sell-form'><input type='hidden' name='csrf' value='{e(csrf)}'>
<fieldset><legend><b>Who is submitting?</b></legend><div class='sell-grid'><div class='wide'>{role}</div><label>Your name<input name='name' maxlength='120' value='{val('name')}' required></label><label>Email<input type='email' name='email' maxlength='254' value='{val('email')}'></label><label>Phone<input type='tel' name='phone' maxlength='30' value='{val('phone')}'></label><label>How should we respond?<input value='Email or phone—whichever you provide' disabled></label><label class='wide'><input type='checkbox' name='contact_permission' value='yes'{' checked' if v.get('contact_permission') == 'yes' else ''} required> DealSniffer may contact me about this submission.</label></div></fieldset>
<fieldset><legend><b>Item</b></legend><div class='sell-grid'><label>Item name<input name='title' maxlength='160' value='{val('title')}' placeholder='Example: John Deere 4020 tractor' required></label><label>Category<select name='category' required><option value=''>Choose one</option>{_options(CATEGORIES, v.get('category', ''))}</select></label><label>City, state or ZIP<input name='location' maxlength='160' value='{val('location')}' placeholder='Conway, AR 72032' required></label><label>Condition<select name='condition' required><option value=''>Choose one</option>{_options(CONDITIONS, v.get('condition', ''))}</select></label><label>Asking price, if known<input inputmode='decimal' name='asking_price' maxlength='20' value='{val('asking_price')}' placeholder='2500'></label><label>What are you considering?<select name='desired_outcome' required><option value=''>Choose one</option>{_options(OUTCOMES, v.get('desired_outcome', ''))}</select></label><label class='wide'>Description<textarea name='description' maxlength='3000' placeholder='Make, model, year, hours, included attachments'>{val('description')}</textarea></label><label class='wide'>Known problems or missing parts<textarea name='known_issues' maxlength='1500' placeholder='Say “none known” or “unknown” if that is all you know'>{val('known_issues')}</textarea></label><label class='wide'>Photo links, one per line (up to 8)<textarea name='photo_urls' maxlength='8000' placeholder='https://...'>{val('photo_urls')}</textarea></label><label class='wide'>Public listing or source link, if there is one<input type='url' name='source_url' maxlength='1000' value='{val('source_url')}'></label></div></fieldset>
<fieldset><legend><b>Owner permission</b></legend><p class='small mut'>A scout lead can be submitted without the owner's contact information. DealSniffer will not contact anyone automatically.</p><label><input type='checkbox' name='owner_contact_permission' value='yes'{' checked' if v.get('owner_contact_permission') == 'yes' else ''}> The owner explicitly agreed that DealSniffer may contact them.</label><label>Owner contact details (only when that box is checked)<textarea name='owner_contact' maxlength='300'>{val('owner_contact')}</textarea></label><label>Anything else for the reviewer?<textarea name='notes' maxlength='1500'>{val('notes')}</textarea></label></fieldset>
<button type='submit'>Send for human review</button></form></div>"""


def render_recent(rows: list[dict]) -> str:
    if not rows:
        return ""
    cards = "".join(f"<div class='card'><b>{e(r['item']['title'])}</b> · {e(r['item']['location'])}<br><span class='small mut'>Submission {e(r['submission_id'])} · REVIEW PENDING · not published</span></div>" for r in rows[:5])
    return f"<div class='sell-wrap'><h2>Your recent submissions</h2>{cards}</div>"
