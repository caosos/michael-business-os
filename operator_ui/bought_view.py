"""F-33: "I bought it" on an approved flip (D-31 `mbos.record_acquisition`), and the open-flips block on the Mission page.

The system never buys anything (F-114): Michael buys off-system and tells it here, so capital deploys when HE records it. The
amount, a note and his PIN are the whole form; the author is server-set. The database refuses an amount above what is available to
deploy and an unfunded ledger, and the after-save text says what moved. Human channel only (R14). Everything is DRY-RUN."""

from __future__ import annotations

import html

from .inputs_view import MAX_MONEY, MAX_NOTE, _errs, _num, _unavailable, parse_note
from .ux import InputError

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
BUY_STATES = ("APPROVED", "ACTING", "ACTED")  # a YES that was approved; once an outcome is recorded the buy is over


def money(v) -> str:
    return f"${v:,.2f}"


def parse_bought(f: dict) -> tuple[object, str]:
    """(amount, note) or InputError listing every problem. The amount is positive money with at most two decimals."""
    errs, amount, note = [], None, ""
    try:
        amount = _num(f.get("amount"), "Amount paid", MAX_MONEY, True)
    except InputError as ex:
        errs.append(str(ex))
    try:
        note = parse_note(f.get("note"))
    except InputError as ex:
        errs.append(str(ex))
    if errs:
        raise InputError("; ".join(errs))
    return amount, note


def saved_message(amount, capital: dict) -> str:
    return (f"Recorded: you bought it for {money(float(amount))} (you, human, receipted, DRY-RUN). Nothing was spent or sent by the system. "
            f"Capital deployed on this item is now {money(capital['deployed'])}; it comes back, plus any profit, when you record the sale.")


def render_bought(item: dict, cap: dict, csrf: str, pin_set: bool, lane_d: bool, nonce: str, reasons=None, values=None) -> str:
    """The card section: the form while the YES is approved and nothing is closed; otherwise what is on file. "" for other items."""
    if item.get("type") != "flip" or item.get("state") not in BUY_STATES + ("OUTCOME_RECORDED",):
        return ""
    iid, v = e(item["item_id"]), values or {}
    held = (f"<p>Recorded as bought: <b>{money(cap['deployed'])}</b> deployed on this item.</p>" if cap["deployed"] else
            "<p>No purchase of yours is on file for this item yet, so no capital is deployed on it.</p>")
    if cap["closed"]:
        net = cap.get("net")
        return (f"<div class='card' id='bought'><h2>I bought it</h2>{held}<p>Closed: the principal came back to your ledger"
                f"{'' if net is None else f' and the net was <b>{money(net)}</b>'}. A second close is refused.</p></div>")
    if item["state"] not in BUY_STATES:
        return ""
    form = _unavailable(pin_set) if not (pin_set and lane_d) else f"""<form method="post" action="/item/{iid}/bought">
<input type="hidden" name="csrf" value="{e(csrf)}"><input type="hidden" name="nonce" value="{e(nonce)}b"><div class="decide">
<label>Amount I paid ($)<input name="amount" inputmode="decimal" value="{e(v.get('amount'))}" required></label>
<label>Note (who from, when)<input name="note" maxlength="{MAX_NOTE}" value="{e(v.get('note'))}" required></label>
<label>PIN<input name="pin" type="password" autocomplete="off" required></label>
<button class="b-HOLD" style="width:auto">I bought it</button></div></form>"""
    return (f"<div class='card rec' id='bought'><h2>I bought it</h2><p class='small'>You buy off-system; the system never buys anything. "
            "Recording it deploys that amount from your bankroll (refused if it is more than is available). It is receipted as you, dry-run.</p>"
            f"{held}{_errs('Not recorded.', reasons)}{form}</div>")


def render_open_flips(rows: list[dict]) -> str:
    """Mission page: capital held by flips that are bought and not yet sold. Nothing is shown when none are open."""
    if not rows:
        return ""
    body = "".join(f"<tr><td><a href='/item/{e(r['item_id'])}'>{e(r['title'])}</a></td><td class='num'>{money(r['amount'])}</td></tr>" for r in rows)
    return (f"<div class='card'><h2>Open flips ({len(rows)})</h2><table><tr><th>Bought</th><th>Capital deployed</th></tr>{body}"
            f"<tr><td><b>Total deployed in open flips</b></td><td class='num'><b>{money(sum(r['amount'] for r in rows))}</b></td></tr></table>"
            "<p class='small mut'>Principal returns, and profit becomes earned working capital, when you record the sale.</p></div>")
