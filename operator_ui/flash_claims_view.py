"""Small customer and vendor views for deterministic flash claims."""

from __future__ import annotations

import html
from datetime import datetime
from zoneinfo import ZoneInfo

e = lambda value: html.escape("" if value is None else str(value))  # noqa: E731


def _time(value: str) -> str:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(ZoneInfo("America/Chicago"))
        return stamp.strftime("%b %d, %Y · %I:%M %p Central").replace(" 0", " ")
    except (ValueError, TypeError):
        return e(value)


def customer_page(deals: list[dict], csrf: str, result: dict | None = None) -> str:
    notice = ""
    if result:
        if result["status"] == "CLAIMED":
            token = result.get("token") or result["receipt"]["details"].get("redemption_token")
            notice = ("<div class='card flash-award'><h2>Claim secured</h2>"
                      f"<p>Show this one-time redemption code to the vendor:</p><p class='flash-token'><code>{e(token)}</code></p>"
                      f"<p class='small mut'>Expires {_time(result['receipt']['details']['redemption_expires_at'])}. "
                      f"Receipt <code>{e(result['receipt']['receipt_id'])}</code>.</p></div>")
        elif result["status"] == "WAITLISTED":
            notice = ("<div class='card'><h2>Waitlist joined</h2>"
                      f"<p>You are number {e(result['receipt']['details']['position'])} on the waitlist.</p></div>")
        else:
            notice = f"<div class='flash err'>This claim is {e(result['status'].lower().replace('_', ' '))}.</div>"
    cards = []
    for deal in deals:
        state = deal["state"]
        if state in ("OPEN", "WAITLIST"):
            label = "Join waitlist" if state == "WAITLIST" else "Claim this deal"
            action = (f"<form method='post' action='/market/flash/{e(deal['deal_id'])}/claim'>"
                      f"<input type='hidden' name='csrf' value='{e(csrf)}'><button>{label}</button></form>")
        elif state == "SCHEDULED":
            action = f"<p><b>Opens {_time(deal['starts_at'])}</b></p>"
        elif state == "EXPIRED":
            action = "<p class='mut'><b>Expired</b></p>"
        else:
            action = "<p class='bad'><b>Claimed out</b></p>"
        cards.append(f"""<article class='card flash-deal'><div class='row'><div class='grow'><h3>{e(deal['title'])}</h3>
<p><b>{e(deal['vendor'])}</b> · {e(deal['territory'])}</p></div><span class='badge'>{e(state)}</span></div>
<p>{e(deal['description'])}</p><p><b>{e(deal['remaining'])} of {e(deal['claim_limit'])} claims remaining</b> · {e(deal['waitlisted'])} waitlisted</p>
<p class='small mut'>Eligibility: {e(deal['eligibility'])}<br>Claims close {_time(deal['claims_end_at'])}; redeem by {_time(deal['redeem_by'])}.</p>{action}</article>""")
    empty = "<div class='card'><p>No flash deals are available in this account yet.</p></div>"
    return f"""<style>.flash-list{{max-width:820px;margin:auto}}.flash-token code{{font-size:22px;letter-spacing:.06em}}.flash-deal h3{{margin:0}}</style>
<div class='flash-list'><p><a href='/market'>All listings</a> · <a href='/sell/deal/flash'>Vendor controls</a></p>
<h1>Flash deals</h1><p>Scheduled first-come offers with a fixed number of claims. No random winner and no payment to claim.</p>
{notice}{''.join(cards) or empty}</div>"""


def vendor_page(deals: list[dict], receipts: list[dict], csrf: str, values: dict | None = None) -> str:
    values = values or {}
    val = lambda key: e(values.get(key, ""))  # noqa: E731
    cards = "".join(
        f"<article class='card'><h3>{e(d['title'])}</h3><p><b>{e(d['state'])}</b> · {e(d['claimed'])}/{e(d['claim_limit'])} claimed · "
        f"{e(d['waitlisted'])} waitlisted · {e(d['confirmed'])} redeemed</p><p class='small mut'>Deal ID <code>{e(d['deal_id'])}</code></p></article>"
        for d in deals
    ) or "<p>No flash deals created yet.</p>"
    trail = "".join(
        f"<tr><td>{e(r['occurred_at'])}</td><td>{e(r['event'])}</td><td><code>{e(r['receipt_id'])}</code></td></tr>"
        for r in reversed(receipts[-30:])
    ) or "<tr><td colspan='3'>No receipts yet.</td></tr>"
    return f"""<style>.flash-admin{{max-width:900px;margin:auto}}.flash-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px 16px}}
.flash-grid .wide{{grid-column:1/-1}}@media(max-width:650px){{.flash-grid{{grid-template-columns:1fr}}.flash-grid .wide{{grid-column:auto}}}}</style>
<div class='flash-admin'><p><a href='/sell/deal'>Deal submissions</a> · <a href='/market/flash'>Customer view</a></p>
<h1>Deterministic flash deals</h1><div class='card'><p><b>Fixed first-N claims only.</b> This feature has no random selection, payment, bid, or chance-based prize mode.</p></div>
<form class='card' method='post' action='/sell/deal/flash/create'><input type='hidden' name='csrf' value='{e(csrf)}'><h2>Create a scheduled flash deal</h2>
<div class='flash-grid'><label>Vendor<input name='vendor' maxlength='160' value='{val('vendor')}' required></label>
<label>Deal title<input name='title' maxlength='180' value='{val('title')}' required></label>
<label class='wide'>Description<textarea name='description' maxlength='1500'>{val('description')}</textarea></label>
<label>Territory<input name='territory' maxlength='180' value='{val('territory')}' placeholder='Conway, AR · within 30 miles' required></label>
<label>Eligibility<input name='eligibility' maxlength='300' value='{val('eligibility')}' placeholder='One per verified account; pickup terms' required></label>
<label>Release time<input type='datetime-local' name='starts_at' value='{val('starts_at')}' required></label>
<label>Claims close<input type='datetime-local' name='claims_end_at' value='{val('claims_end_at')}' required></label>
<label>Redeem by<input type='datetime-local' name='redeem_by' value='{val('redeem_by')}' required></label>
<label>Number of claims<input type='number' name='claim_limit' min='1' max='100000' value='{val('claim_limit') or '3'}' required></label>
<label>Waitlist size<input type='number' name='waitlist_limit' min='0' max='100000' value='{val('waitlist_limit') or '10'}' required></label></div>
<button>Create deterministic deal</button></form>
<form class='card' method='post' action='/sell/deal/flash/confirm'><input type='hidden' name='csrf' value='{e(csrf)}'><h2>Confirm a redemption</h2>
<label>Customer redemption code<input name='token' autocomplete='off' required></label><button>Confirm redeemed</button></form>
<section><h2>Vendor report</h2>{cards}</section><details class='card'><summary>Append-only receipt trail</summary>
<table><tr><th>Time</th><th>Event</th><th>Receipt</th></tr>{trail}</table></details></div>"""
