"""Customer-facing DealSniffer settings for account-scoped search defaults."""

from __future__ import annotations

import html

from . import account_delivery, accounts, market_prefs, market_search
from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731


def _home() -> dict:
    ui = market_prefs.load().get("ui")
    ui = ui if isinstance(ui, dict) else {}
    home = ui.get("home") if isinstance(ui.get("home"), dict) else {}
    raw_cats = home.get("categories") if isinstance(home.get("categories"), list) else market_search.DEFAULT_CATS
    return {
        "location": str(home.get("zip") or home.get("label") or "")[:60],
        "radius": float(home.get("radius") or market_search.DEFAULT_RADIUS),
        "categories": [c for c in raw_cats if c in market_search.CONTROL_CATS],
    }


def save_preferences(form: dict) -> str:
    location = " ".join(str(form.get("location") or "").split())[:60]
    try:
        radius = float(str(form.get("radius") or ""))
    except ValueError:
        raise InputError("radius must be a number") from None
    if not location:
        raise InputError("city or ZIP is required")
    if not 1 <= radius <= 500:
        raise InputError("radius must be between 1 and 500 miles")
    probe = market_search.parse_query({"base": [location], "radius": [str(radius)]})
    if probe["errors"]:
        raise InputError(probe["errors"][0])
    raw_cats = form.get("cat") if isinstance(form.get("cat"), list) else [form.get("cat")] if form.get("cat") else []
    cats = [c for c in dict.fromkeys(x for raw in raw_cats for x in str(raw).split(",")) if c in market_search.CONTROL_CATS]
    if not cats:
        raise InputError("choose at least one category")
    doc = market_prefs.load()
    ui = doc.get("ui") if isinstance(doc.get("ui"), dict) else {}
    doc["ui"] = {**ui, "home": {"state": "", "zip": location, "label": location,
                                  "radius": radius, "categories": cats}}
    market_prefs._store(doc)
    return "Deal preferences saved."


def render(csrf: str, google_status: dict) -> str:
    account = accounts.current()
    home = _home()
    cats = "".join(
        f"<label><input type='checkbox' name='cat' value='{e(c)}'{' checked' if c in home['categories'] else ''}> {e(market_search.CAT_LABELS[c])}</label>"
        for c in market_search.CONTROL_CATS
    )
    identity = (f"Signed in as {e(account.display_name or account.email or 'Google user')}" if account.authenticated
                else "Local owner mode on this EliteDesk")
    oauth = ("CONFIGURED — callback still requires an end-to-end browser proof" if google_status.get("configured")
             else "NOT CONFIGURED — domain, HTTPS, Google client, and consent setup are still required")
    alerts = account_delivery.status(account.storage_key, "alerts")
    contact = account_delivery.status(account.storage_key, "contact")
    return f"""<style>
.settings{{max-width:880px;margin:auto}}.settings-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}}.settings .checks{{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:6px}}.settings button{{background:var(--acc);max-width:260px}}@media(max-width:650px){{.settings-grid{{grid-template-columns:1fr}}}}
</style><div class='settings'><h1>Settings</h1>
<section class='card' id='deal-preferences'><h2>Deal preferences</h2><p class='mut'>These are your starting filters. You can still change filters for any one search.</p>
<form method='post' action='/settings/preferences'><input type='hidden' name='csrf' value='{e(csrf)}'><div class='settings-grid'>
<label>City or ZIP<input name='location' maxlength='60' value='{e(home['location'])}' placeholder='Conway, AR or 72032' required></label>
<label>Default radius (miles)<select name='radius'>{''.join(f"<option value='{n}'{' selected' if home['radius'] == n else ''}>{n}</option>" for n in (10, 25, 30, 50, 100, 250))}</select></label>
<fieldset style='grid-column:1/-1'><legend>What do you want to see?</legend><div class='checks'>{cats}</div></fieldset></div><button>Save my defaults</button></form></section>
<section class='card' id='account-status'><h2>Account</h2><p><b>{identity}</b></p><p>Google sign-in: <b>{oauth}</b></p><p class='small mut'>Google sign-in identifies the DealSniffer user only. It never signs in to Facebook or an auction source.</p></section>
<section class='card' id='delivery-status'><h2>Mailbox & notifications</h2>
<p>Vendor alerts: <b>{e(alerts['state'])}</b>{' · ' + e(alerts['address']) if alerts['address'] else ''}<br><span class='small mut'>{e(alerts['detail'])}</span></p>
<p>Buyer/seller contact: <b>{e(contact['state'])}</b>{' · ' + e(contact['address']) if contact['address'] else ''}<br><span class='small mut'>{e(contact['detail'])}</span></p>
<p>Email notifications: <b>NOT ACTIVE</b> until a destination is verified and a real delivery receipt succeeds.</p></section></div>"""
