"""F-22: the "My numbers" page. Michael's weekly target, hours available and cash situation (MICHAEL_DECISIONS #9/#10) are DATA:
each change is a receipted mission row (`mbos.set_mission`), never assumed. A blank value is stored as NULL and shown as UNKNOWN.
The five capital-ledger fields are read from `mbos.capital_position_document`; fund and withdraw call `mbos.capital_fund` /
`mbos.capital_withdraw`. Dry-run accounting only. Human channel only (R14): CSRF + PIN, author set by the server."""

from __future__ import annotations

import html
import re
import secrets
from decimal import Decimal, InvalidOperation

from .mission_view import LEDGER_FIELDS, current_week, money
from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
MAX_USD, MAX_HOURS, MAX_NOTE = Decimal("10000000"), Decimal("168"), 500


def parse_amount(raw: str, label: str, *, cap: Decimal, required: bool, positive: bool = False):
    """'' -> None (UNKNOWN) when not required. Otherwise a finite Decimal with at most 2 places, within [0, cap]."""
    raw = (raw or "").strip().replace(",", "").lstrip("$")
    if not raw:
        if required:
            raise InputError(f"{label} is required")
        return None
    if not re.fullmatch(r"\d+(\.\d{1,2})?", raw):
        raise InputError(f"{label} must be a plain number like 1500 or 12.50")
    try:
        d = Decimal(raw)
    except InvalidOperation:
        raise InputError(f"{label} must be a number") from None
    if not d.is_finite() or d < 0 or d > cap or d != d.quantize(Decimal("0.01")):
        raise InputError(f"{label} must be between 0 and {cap} with at most 2 decimals")
    if positive and d <= 0:
        raise InputError(f"{label} must be more than 0")
    return d


def parse_mission(f: dict, now) -> dict:
    """Blank target/hours/cash situation = UNKNOWN (null). Nothing is defaulted."""
    target = parse_amount(f.get("weekly_target_usd"), "Weekly target", cap=MAX_USD, required=False)
    hours = parse_amount(f.get("hours_available"), "Hours available", cap=MAX_HOURS, required=False)
    cash = (f.get("cash_situation") or "").strip()
    if len(cash) > MAX_NOTE:
        raise InputError(f"Cash situation is limited to {MAX_NOTE} characters")
    doc = {"mission_version": "1.0.0", "period": current_week(now),
           "weekly_target_usd": None if target is None else float(target),
           "hours_available": None if hours is None else float(hours)}
    if cash:
        doc["notes"] = cash
    return doc


def unknown(v, fmt=None) -> str:
    return "<b class='unk'>UNKNOWN</b>" if v is None else (fmt(v) if fmt else e(v))


def render_page(data: dict, csrf: str, pin_set: bool, reasons=None, values=None) -> str:
    if not data.get("available"):
        return "<div class='card'><h2>My numbers</h2><p class='bad'>My numbers needs the lane D store (MBOS_STATE_BACKEND=lane_d).</p></div>"
    values = values or {}
    m, l = data["mission"], data["ledger"]
    err = (f"<div class='flash err'><b>Not saved.</b><ul>{''.join(f'<li>{e(r)}</li>' for r in reasons)}</ul></div>" if reasons else "")
    pin = ("<label>PIN (it identifies you) <input type='password' name='pin' autocomplete='off' required></label>" if pin_set else
           "<p class='bad'>MBOS_OPERATOR_PIN is not set: changes are refused (fail-closed).</p>")
    tok = lambda: f"<input type='hidden' name='csrf' value='{e(csrf)}'><input type='hidden' name='nonce' value='{secrets.token_hex(8)}'>"  # noqa: E731
    cur = (f"<tr><td>Weekly target</td><td class='num'>{unknown(m and m.get('weekly_target_usd'), money)}</td></tr>"
           f"<tr><td>Hours available</td><td class='num'>{unknown(m and m.get('hours_available'), lambda v: e(v) + ' h')}</td></tr>"
           f"<tr><td>Cash situation</td><td>{unknown(m and m.get('notes'))}</td></tr>"
           f"<tr><td>Week</td><td>{e(m['period']['start'] + ' to ' + m['period']['end']) if m else unknown(None)}</td></tr>")
    mission = (f"<div class='card'><h2>My numbers: this week</h2><table>{cur}</table>"
               "<p class='small mut'>Leave a box empty to clear it: it goes back to UNKNOWN and the system will not guess. "
               "Each save is a receipted change.</p>"
               f"<form method='post' action='/numbers/mission'>{tok()}"
               f"<label>Weekly target (USD) <input name='weekly_target_usd' inputmode='decimal' value='{e(values.get('weekly_target_usd', (m or {}).get('weekly_target_usd') or ''))}'></label> "
               f"<label>Hours available <input name='hours_available' inputmode='decimal' value='{e(values.get('hours_available', (m or {}).get('hours_available') or ''))}'></label><br>"
               f"<label>Current cash situation (in your words) <input name='cash_situation' size='60' maxlength='{MAX_NOTE}' value='{e(values.get('cash_situation', (m or {}).get('notes') or ''))}'></label><br>"
               f"{pin} <button>Save</button></form></div>")
    if l:
        rows = "".join(f"<tr><td>{label}</td><td class='num'>{money(l.get(k))}</td></tr>" for k, label in LEDGER_FIELDS)
        pos = f"<table>{rows}</table><p class='small mut'>As of {e(l.get('as_of'))}. Dry-run accounting.</p>"
    else:
        pos = "<p class='unk'><b>UNKNOWN.</b> No capital has been funded yet, so there is no position.</p>"
    move = lambda kind, label: (f"<form method='post' action='/numbers/capital' style='display:inline-block;margin-right:24px'>{tok()}"  # noqa: E731
                                f"<input type='hidden' name='kind' value='{kind}'><label>{label} (USD) <input name='amount' inputmode='decimal' required></label> "
                                f"{pin} <button>{label}</button></form>")
    cap = (f"<div class='card'><h2>Capital ledger</h2>{pos}{move('fund', 'Fund')}{move('withdraw', 'Withdraw')}"
           "<p class='small mut'>Withdrawals come only from earned working capital; protected principal cannot be withdrawn here. "
           "The ledger is derived from receipts and cannot be edited.</p></div>")
    return err + mission + cap
