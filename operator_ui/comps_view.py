"""F-28: a parked item (RESEARCHING) says what it needs from Michael, and "Add a price I saw" writes a sold comp into the
`ManualCompsAdapter` inbox (lane B, `mbos_discovery.comps`; A-39 selects it per item as `MBOS_COMPS_INBOX`).

Human channel only (R14): CSRF + PIN, and `entered_by` is set by the server, never by the form. Nothing is fetched or automated:
Michael types what he saw. The UI process cannot re-launch the lifecycle, so after saving it says so and shows `mbos recheck`.
One file per comp, named by an id derived from the item and the form nonce, created exclusively: a double submit is a no-op."""

from __future__ import annotations

import hashlib
import html
import json
import os
import re
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Optional

from .numbers_view import parse_amount
from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
MAX_PRICE, MAX_AGE_DAYS = Decimal("1000000"), 730
CONDITIONS = ("used", "new", "parts", "unknown")  # == mbos_discovery.comps.CONDITIONS
DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", re.ASCII)
DEFAULT_GAP = "no comparable sold price"


def gap_text(card: dict) -> str:
    """The research gap in the system's own words: the latest 'gaps: ...' or 'needs ...' reason on the card's trail."""
    for t in reversed(card.get("activity_trail") or []):
        why = str(t.get("why") or "")
        for key in ("gaps:", "needs "):
            if key in why:
                return why.split(key, 1)[1].strip(" .;") or DEFAULT_GAP
    return DEFAULT_GAP


def _text(raw, label: str, limit: int, required: bool = True) -> str:
    s = " ".join(str(raw or "").split())
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        raise InputError(f"{label} has control characters")
    if required and not s:
        raise InputError(f"{label} is required")
    if len(s) > limit:
        raise InputError(f"{label} is limited to {limit} characters")
    return s


def parse_comp(f: dict, item: dict, author: str, now: datetime) -> dict:
    """The exact inbox shape `ManualCompsAdapter.normalize` reads, or InputError. All reasons are collected."""
    errs: list[str] = []

    def get(fn, *a):
        try:
            return fn(*a)
        except InputError as ex:
            errs.append(str(ex))

    price = None
    try:
        price = parse_amount(f.get("sold_price"), "Sold price", cap=MAX_PRICE, required=True, positive=True)
    except InputError as ex:
        errs.append(str(ex))
    make, model = get(_text, f.get("make"), "Make", 60), get(_text, f.get("model"), "Model", 60)
    where = get(_text, f.get("where_sold"), "Where you saw it", 100)
    note = get(_text, f.get("note"), "Note", 300, False) or ""
    url = (f.get("url") or "").strip()
    if url and not (url.isascii() and re.fullmatch(r"https?://[^\s<>\"']{4,490}", url)):
        errs.append("Link must be a plain http(s) address with no spaces")
        url = ""
    if not url and len(note) < 3:
        errs.append("Give a link or a short note saying where the price came from")
    cond = (f.get("condition") or "").strip().lower()
    if cond not in CONDITIONS:
        errs.append("Condition must be one of " + ", ".join(CONDITIONS))
    sold = (f.get("sold_date") or "").strip()
    sold_on = None
    if not DATE_RE.fullmatch(sold):
        errs.append("Sold date must look like 2026-09-21")
    else:
        try:
            sold_on = date.fromisoformat(sold)
        except ValueError:
            errs.append("Sold date is not a real calendar date")
    if sold_on and sold_on > now.date():
        errs.append("Sold date is in the future")
    if sold_on and sold_on < now.date() - timedelta(days=MAX_AGE_DAYS):
        errs.append(f"Sold date is more than {MAX_AGE_DAYS // 365} years old; older prices are not comparable")
    if errs:
        raise CompRefused(errs)
    nonce = f.get("nonce") or ""
    cid = "ui-" + hashlib.sha256(f"{item['item_id']}|{nonce}".encode()).hexdigest()[:24]
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    prov = (f"Entered by {author} through the Operator UI at {stamp} for item {item['item_id']}; typed from a price {author} saw "
            f"({where}). Nothing was fetched or automated." + (f" Note: {note}" if note else ""))
    doc = {"comp_id": cid, "category": item.get("category") or "", "title": f"{make} {model}", "make": make, "model": model,
           "sold_price": float(price), "sold_date": sold, "where_sold": where, "url": url, "condition": cond,
           "entered_by": author, "provenance_note": prov, "item_id": item["item_id"], "entered_via": "operator_ui"}
    if note:
        doc["note"] = note
    return doc


class CompRefused(InputError):
    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = list(reasons)


def write_comp(inbox: Optional[str], doc: dict) -> tuple[Path, bool]:
    """Atomically create `<inbox>/<comp_id>.json`. Returns (path, created); an existing file means this was a double submit."""
    if not inbox:
        raise InputError("MBOS_COMPS_INBOX is not set: a price cannot be saved")
    d = Path(inbox)
    d.mkdir(parents=True, exist_ok=True)
    final = d / (doc["comp_id"] + ".json")
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, indent=2, sort_keys=True)
        try:
            os.link(tmp, final)  # fails if it exists: never overwrite a recorded comp
            return final, True
        except FileExistsError:
            return final, False
    finally:
        os.unlink(tmp)


def render_needs(card: dict, item_state: str, csrf: str, pin_set: bool, inbox_set: bool, reasons=None, values=None, nonce: str = "") -> str:
    """The "Needs from you" section + the "Add a price I saw" form. Shown only while the item is parked in RESEARCHING."""
    if item_state != "RESEARCHING":
        return ""
    v = values or {}
    i = card["item"]
    errs = ("<div class='flash err'><b>Price not saved.</b><ul>" + "".join(f"<li>{e(r)}</li>" for r in reasons) + "</ul></div>") if reasons else ""
    mm = i["make_model"]
    make_model = mm.get("value") if isinstance(mm, dict) and isinstance(mm.get("value"), str) else ""
    cond = v.get("condition") or "used"
    opts = "".join(f"<option value='{c}'{' selected' if c == cond else ''}>{c}</option>" for c in CONDITIONS)
    if not (pin_set and inbox_set):
        form = ("<p class='bad'>" + ("MBOS_OPERATOR_PIN is not set: " if not pin_set else "MBOS_COMPS_INBOX is not set: ")
                + "prices cannot be saved from this page (fail-closed).</p>")
    else:
        form = f"""<form method="post" action="/item/{e(card['item_id'])}/comp"><input type="hidden" name="csrf" value="{e(csrf)}">
<input type="hidden" name="nonce" value="{e(nonce)}">
<p class="small">Type a price you saw something like this <b>sell for</b>. Nothing is fetched from any site. Entered as <b>you</b>; category: {e(i['category'])}.</p>
<div class="decide"><label>Make<input name="make" maxlength="60" value="{e(v.get('make') or '')}" required></label>
<label>Model<input name="model" maxlength="60" value="{e(v.get('model') or make_model)}" required></label>
<label>Sold price ($)<input name="sold_price" inputmode="decimal" value="{e(v.get('sold_price'))}" required></label>
<label>Date it sold<input name="sold_date" placeholder="YYYY-MM-DD" maxlength="10" value="{e(v.get('sold_date'))}" required></label>
<label>Condition<select name="condition">{opts}</select></label></div>
<div class="decide"><label>Where you saw it<input name="where_sold" maxlength="100" value="{e(v.get('where_sold'))}" required></label>
<label>Link (optional if you add a note)<input name="url" maxlength="500" value="{e(v.get('url'))}"></label>
<label>Note (optional if you add a link)<input name="note" maxlength="300" value="{e(v.get('note'))}"></label>
<label>PIN<input name="pin" type="password" autocomplete="off" required></label></div>
<button class="b-HOLD" style="width:auto">Save this price</button></form>"""
    return (f"<div class='card rec' id='needs'><h2>Needs from you</h2><p style='font-size:18px'><b>{e(gap_text(card))}</b></p>"
            "<p>This item is parked: the system cannot recommend it until it has a price to compare with. "
            f"A price you actually saw is enough.</p>{errs}<h3>Add a price I saw</h3>{form}</div>")


def saved_message(item_id: str, created: bool) -> str:
    head = "Price saved." if created else "That price was already recorded; nothing changed."
    return (f"{head} The item has not moved yet: this page cannot re-check it. Run `mbos recheck {item_id}` "
            "(or `mbos recheck --researching`) on the server and it will be re-checked with your price.")


def render_today(parked: list) -> str:
    """The Today list: parked Items and what each needs. Empty when nothing is parked."""
    if not parked:
        return ""
    rows = "".join(f"<div class='card q'><a class='rowlink' href='/item/{e(it['item_id'])}#needs'><b>{e(it['normalized']['title'])}</b>"
                   f"<div>Needs from you: <b>{e(gap)}</b></div></a></div>" for it, gap in parked)
    return f"<h2>Needs from you ({len(parked)})</h2>{rows}"
