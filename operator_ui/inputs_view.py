"""F-32: Michael's typed inputs on an item, through the owner channel (A-43 `spine_d.record_human_input` over D-30).

"Set my quote" (service leads): the amount he quotes the customer, which lane C (C-28) uses as the job's revenue, human-attested.
"Tell me about the job" (an item the engine cannot estimate, `scope_override_required`): parts or materials cost, labour hours,
optional admin hours and the skills needed, which lane C (C-27) feeds into the estimate as human-attested overrides.

Human channel only (R14): CSRF + PIN, the author is server-set. Validation is strict and finite; nothing is guessed or defaulted.
Saving does not move the item by itself: the running worker re-checks it (about a minute), so the after-save text says exactly that."""

from __future__ import annotations

import html
import re
from decimal import Decimal, InvalidOperation

from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
MAX_NOTE, MAX_MONEY, MAX_HOURS = 300, Decimal("1000000"), Decimal("1000")
SKILL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{1,39}", re.ASCII)
NUM_RE = re.compile(r"([0-9]{1,3}(,[0-9]{3})+|[0-9]{1,9})(\.[0-9]{1,2})?", re.ASCII)
DONE_STATES = ("ARCHIVED", "FAILED", "LEARNED", "ACTED")


def block(item: dict) -> str:
    """The estimator block a scope override belongs to: a service job or a flip's rehab."""
    return "job" if item.get("type") == "service" else "rehab"


def needs_scope(card: dict) -> bool:
    """True when the engine's latest gap on the card trail is `scope_override_required` (nothing else makes this form appear)."""
    for t in reversed(card.get("activity_trail") or []):
        why = str(t.get("why") or "")
        if "gaps:" in why or "needs " in why:
            return "scope_override_required" in why
    return False


def current(item: dict, field: str):
    """The latest stored value for a research field (the latest entry wins, as in lane C), or None."""
    mine = [r for r in (item.get("research") or []) if r.get("field") == field]
    return mine[-1].get("value") if mine else None


def _num(raw, label: str, limit: Decimal, positive: bool) -> int | float:
    s = str(raw or "").strip().removeprefix("$")
    if not NUM_RE.fullmatch(s):
        raise InputError(f"{label} must be a plain number like 700 or 42.50")
    d = Decimal(s.replace(",", ""))
    try:
        ok = d.is_finite() and (d > 0 if positive else d >= 0) and d <= limit
    except InvalidOperation:  # pragma: no cover
        ok = False
    if not ok:
        raise InputError(f"{label} must be {'more than 0' if positive else '0 or more'} and at most {limit:,}")
    return int(d) if d == d.to_integral_value() else float(d)


def parse_note(raw) -> str:
    s = " ".join(str(raw or "").split())
    if any(ord(c) < 32 or ord(c) == 127 for c in s):
        raise InputError("Note has control characters")
    if len(s) < 3:
        raise InputError("Say in a few words how you know (who you spoke to, what you saw)")
    if len(s) > MAX_NOTE:
        raise InputError(f"Note is limited to {MAX_NOTE} characters")
    return s


def parse_quote(f: dict) -> tuple[list[tuple[str, str, object]], str]:
    """[(kind, key, value)] and the note, or InputError."""
    errs, note, amount = [], "", None
    for fn, label in ((lambda: parse_note(f.get("note")), "note"), (lambda: _num(f.get("amount"), "Quote", MAX_MONEY, True), "amount")):
        try:
            v = fn()
            note, amount = (v, amount) if label == "note" else (note, v)
        except InputError as ex:
            errs.append(str(ex))
    if errs:
        raise InputError("; ".join(errs))
    return [("quote", "amount_usd", amount)], note


def parse_scope(f: dict, item: dict) -> tuple[list[tuple[str, str, object]], str]:
    blk = block(item)
    cost = "materials_cost" if blk == "job" else "parts_cost"
    errs, out = [], []
    for field, label, lim, req in ((cost, "Parts/materials cost", MAX_MONEY, True), ("labor_hours", "Labour hours", MAX_HOURS, True),
                                   ("admin_hours", "Admin hours", MAX_HOURS, False)):
        raw = f.get(field)
        if not req and not str(raw or "").strip():
            continue
        try:
            out.append(("scope_override", f"{blk}.{field}", _num(raw, label, lim, False)))
        except InputError as ex:
            errs.append(str(ex))
    skills = [" ".join(s.split()) for s in str(f.get("required_skills") or "").split(",") if s.strip()]
    if not skills or len(skills) > 8 or not all(SKILL_RE.fullmatch(s) for s in skills):
        errs.append("Skills needed: one to eight names separated by commas (letters, numbers, spaces)")
    else:
        out.append(("scope_override", f"{blk}.required_skills", skills))
    try:
        note = parse_note(f.get("note"))
    except InputError as ex:
        errs.append(str(ex))
        note = ""
    if errs:
        raise InputError("; ".join(errs))
    return out, note


def saved_message(what: str, item_id: str) -> str:
    return (f"Saved {what} (you, human, receipted). Nothing is sent to anyone and the verdict has not changed yet: the running worker "
            f"re-checks this item by itself (about a minute); reload to see the result. If no worker is running, run `mbos recheck {item_id}` on the server.")


def _unavailable(pin_set: bool) -> str:
    return ("<p class='bad'>" + ("MBOS_OPERATOR_PIN is not set" if not pin_set else "Saving needs the lane D store (MBOS_STATE_BACKEND=lane_d)")
            + ": this cannot be saved from this page (fail-closed).</p>")


def _errs(title: str, reasons) -> str:
    return (f"<div class='flash err'><b>{e(title)}</b><ul>" + "".join(f"<li>{e(r)}</li>" for r in reasons) + "</ul></div>") if reasons else ""


def render_inputs(item: dict, card: dict, csrf: str, pin_set: bool, lane_d: bool, nonce: str, reasons=None, which=None, values=None) -> str:
    """Quote form for a service lead, scope form for an item waiting on `scope_override_required`; "" when neither applies."""
    if item.get("state") in DONE_STATES:
        return ""
    v, ok, iid = values or {}, pin_set and lane_d, e(item["item_id"])
    parts = []
    if item.get("type") == "service":
        cur = current(item, "quote:amount_usd")
        sc = ((item.get("scores") or {}).get("scorecard")) or {}
        hint = sc.get("min_quote_for_yes")
        info = (f"<p>Your quote on file: <b>${e(cur)}</b>. </p>" if cur is not None else "<p>No quote of yours is on file yet (the system uses its own default).</p>")
        if isinstance(hint, (int, float)) and not isinstance(hint, bool):
            info += f"<p class='small'>The system's suggestion: a quote of ${e(f'{hint:,}')} or more would clear the bar. It is only a suggestion.</p>"
        form = _unavailable(pin_set) if not ok else f"""<form method="post" action="/item/{iid}/quote"><input type="hidden" name="csrf" value="{e(csrf)}">
<input type="hidden" name="nonce" value="{e(nonce)}q"><div class="decide">
<label>My quote ($)<input name="amount" inputmode="decimal" value="{e(v.get('amount') if which == 'quote' else '')}" required></label>
<label>How did you arrive at it?<input name="note" maxlength="{MAX_NOTE}" value="{e(v.get('note') if which == 'quote' else '')}" required></label>
<label>PIN<input name="pin" type="password" autocomplete="off" required></label>
<button class="b-HOLD" style="width:auto">Set my quote</button></div></form>"""
        parts.append(f"<div class='card rec' id='quote'><h2>Set my quote</h2><p class='small'>The price you quote the customer. It is recorded as <b>your word</b> and "
                     f"used as the job's revenue; it is never guessed. Nothing is sent to anyone.</p>{info}"
                     f"{_errs('Quote not saved.', reasons if which == 'quote' else None)}{form}</div>")
    if needs_scope(card):
        blk = block(item)
        cost = "materials_cost" if blk == "job" else "parts_cost"
        form = _unavailable(pin_set) if not ok else f"""<form method="post" action="/item/{iid}/scope"><input type="hidden" name="csrf" value="{e(csrf)}">
<input type="hidden" name="nonce" value="{e(nonce)}s"><div class="decide">
<label>{'Materials' if blk == 'job' else 'Parts'} cost ($)<input name="{cost}" inputmode="decimal" value="{e(v.get(cost) if which == 'scope' else '')}" required></label>
<label>Labour hours<input name="labor_hours" inputmode="decimal" value="{e(v.get('labor_hours') if which == 'scope' else '')}" required></label>
<label>Admin hours (optional)<input name="admin_hours" inputmode="decimal" value="{e(v.get('admin_hours') if which == 'scope' else '')}"></label></div>
<div class="decide"><label>Skills needed (comma separated)<input name="required_skills" maxlength="200" value="{e(v.get('required_skills') if which == 'scope' else '')}" required></label>
<label>How do you know?<input name="note" maxlength="{MAX_NOTE}" value="{e(v.get('note') if which == 'scope' else '')}" required></label>
<label>PIN<input name="pin" type="password" autocomplete="off" required></label>
<button class="b-HOLD" style="width:auto">Save what I know</button></div></form>"""
        parts.append("<div class='card rec' id='scope'><h2>Tell me about the job</h2><p class='small'>The system has no estimate for this kind of job. "
                     "Tell it the cost, hours and skills; they are recorded as <b>your word</b> (human, receipted) and used as your figures, not guessed.</p>"
                     f"{_errs('Not saved.', reasons if which == 'scope' else None)}{form}</div>")
    return "".join(parts)
