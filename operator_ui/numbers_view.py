"""F-22: the "My numbers" page. Michael's weekly target, hours available and cash situation (MICHAEL_DECISIONS #9/#10) are DATA:
each change is a receipted mission row (`mbos.set_mission`), never assumed. A blank value is stored as NULL and shown as UNKNOWN.
The five capital-ledger fields are read from `mbos.capital_position_document`; fund and withdraw call `mbos.capital_fund` /
`mbos.capital_withdraw`. Dry-run accounting only. Human channel only (R14): CSRF + PIN, author set by the server."""

from __future__ import annotations

import html
import json
import re
from pathlib import Path
import secrets
from decimal import Decimal, InvalidOperation

from .mission_view import LEDGER_FIELDS, current_week, money
from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
MAX_USD, MAX_HOURS, MAX_NOTE = Decimal("10000000"), Decimal("168"), 500
LIMITS_FILE = Path(__file__).parent / "data" / "numbers_limits.v1.json"
# One optional "$", then digits (ASCII only) with commas only as correct thousands groups, then up to 2 decimals.
AMOUNT_RE = re.compile(r"\$?((?:[0-9]{1,3}(?:,[0-9]{3})+|[0-9]+)(?:\.[0-9]{1,2})?)", re.ASCII)


def usd(v) -> str:
    v = Decimal(str(v))
    return f"${v:,.0f}" if v == v.to_integral_value() else f"${v:,.2f}"


def limits() -> dict:
    """F-76: fund limits are DATA (Michael edits the file). A missing or bad file falls back to the provisional defaults."""
    d = {"max_fund_per_transaction_usd": MAX_USD, "max_total_funded_usd": Decimal("5000"), "confirm_fund_above_usd": Decimal("2000")}
    try:
        raw = json.loads(LIMITS_FILE.read_text())
        for k in d:
            if k in raw:
                v = Decimal(str(raw[k]))
                if v.is_finite() and v >= 0:
                    d[k] = v
    except (OSError, ValueError, InvalidOperation):
        pass
    return d


def fund_confirmation(amt: Decimal) -> str:
    return f"FUND {amt:.2f}"


def check_fund(amt: Decimal, funded_so_far, confirm: str) -> None:
    """F-76: per-transaction cap, cumulative cap, and a typed confirmation above the threshold. Raises InputError."""
    lim = limits()
    if amt > lim["max_fund_per_transaction_usd"]:
        raise InputError(f"One fund cannot be more than {usd(lim['max_fund_per_transaction_usd'])}")
    total = Decimal(str(funded_so_far or 0)) + amt
    if total > lim["max_total_funded_usd"]:
        raise InputError(f"This would bring total funded to {usd(total)}, over your limit of {usd(lim['max_total_funded_usd'])}. "
                         "To raise the limit, change max_total_funded_usd in operator_ui/data/numbers_limits.v1.json.")
    if amt > lim["confirm_fund_above_usd"] and " ".join((confirm or "").split()).upper() != fund_confirmation(amt):
        raise InputError(f"Funding more than {usd(lim['confirm_fund_above_usd'])} needs confirmation: type {fund_confirmation(amt)} "
                         "in the confirmation box and submit again.")


def parse_amount(raw: str, label: str, *, cap: Decimal, required: bool, positive: bool = False):
    """'' -> None (UNKNOWN) when not required. Otherwise a finite Decimal with at most 2 places, within [0, cap]."""
    raw = (raw or "").strip()
    if not raw:
        if required:
            raise InputError(f"{label} is required")
        return None
    m = AMOUNT_RE.fullmatch(raw)
    if not m:
        raise InputError(f"{label} must be a plain number like 1500, $1,500 or 12.50")
    try:
        d = Decimal(m.group(1).replace(",", ""))
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


def _fill(v) -> str:
    """Form pre-fill: only None is blank; an explicit 0 shows as 0 (F-74). Whole numbers drop the '.0'."""
    return "" if v is None else (str(int(v)) if float(v) == int(v) else str(v))


def unknown(v, fmt=None) -> str:
    return "<b class='unk'>UNKNOWN</b>" if v is None else (fmt(v) if fmt else e(v))


def render_page(data: dict, csrf: str, pin_set: bool, reasons=None, values=None, lock_minutes: int = 0) -> str:
    if not data.get("available"):
        return "<div class='card'><h2>My numbers</h2><p class='bad'>My numbers needs the lane D store (MBOS_STATE_BACKEND=lane_d).</p></div>"
    values = values or {}
    m, l = data["mission"], data["ledger"]
    err = (f"<div class='flash err'><b>Not saved.</b><ul>{''.join(f'<li>{e(r)}</li>' for r in reasons)}</ul></div>" if reasons else "")
    lock = (f"<div class='flash err'><b>PIN entry is locked</b> after 5 wrong tries. Try again in about {lock_minutes} minute(s).</div>" if lock_minutes else "")
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
               f"<label>Weekly target (USD) <input name='weekly_target_usd' inputmode='decimal' value='{e(values.get('weekly_target_usd', _fill((m or {}).get('weekly_target_usd'))))}'></label> "
               f"<label>Hours available <input name='hours_available' inputmode='decimal' value='{e(values.get('hours_available', _fill((m or {}).get('hours_available'))))}'></label><br>"
               f"<label>Current cash situation (in your words) <input name='cash_situation' size='60' maxlength='{MAX_NOTE}' value='{e(values.get('cash_situation', (m or {}).get('notes') or ''))}'></label><br>"
               f"{pin} <button>Save</button></form></div>")
    if l:
        rows = "".join(f"<tr><td>{label}</td><td class='num'>{money(l.get(k))}</td></tr>" for k, label in LEDGER_FIELDS)
        pos = f"<table>{rows}</table><p class='small mut'>As of {e(l.get('as_of'))}. Dry-run accounting.</p>"
    else:
        pos = "<p class='unk'><b>UNKNOWN.</b> No capital has been funded yet, so there is no position.</p>"
    lim = limits()
    confirm = (f"<label>Confirm if over {usd(lim['confirm_fund_above_usd'])} (type FUND and the amount, like FUND 2500.00) "
               f"<input name='confirm' autocomplete='off' value='{e((values or {}).get('confirm', ''))}'></label> ")
    move = lambda kind, label: (f"<form method='post' action='/numbers/capital' style='display:inline-block;margin-right:24px'>{tok()}"  # noqa: E731
                                f"<input type='hidden' name='kind' value='{kind}'><label>{label} (USD) <input name='amount' inputmode='decimal' required></label> "
                                f"{confirm if kind == 'fund' else ''}{pin} <button>{label}</button></form>")
    cap = (f"<div class='card'><h2>Capital ledger</h2>{pos}{move('fund', 'Fund')}{move('withdraw', 'Withdraw')}"
           "<p class='small mut'>Withdrawals come only from earned working capital; protected principal cannot be withdrawn here. "
           "The ledger is derived from receipts and cannot be edited. "
           f"Total funded is limited to {usd(lim['max_total_funded_usd'])} (a setting you can raise).</p></div>")
    return lock + err + mission + cap
