"""F-141: the "Your finds" section and the "Add a find" form on /market. Owner-entered, not fetched, unverified; separate from the GSA results and counts."""

from __future__ import annotations

import html

from . import market_finds as mf
from . import market_search as ms
from . import precedent_view as pv
from .live_demo import link_html

e = html.escape
TAG = "<span class='lbl'>OWNER-ENTERED</span> <span class='small mut'>not fetched · unverified · not a live listing</span>"


def _fields(tok, r: dict | None = None) -> str:
    r = r or {}
    v = lambda k: e(str(r.get(k) if r.get(k) is not None else ""))  # noqa: E731
    src = "".join(f"<option value='{k}'{' selected' if r.get('source') == k else ''}>{e(n)}</option>" for k, n in mf.SOURCES.items())
    cond = "".join(f"<option value='{c}'{' selected' if r.get('condition', '') == c else ''}>{e(c or 'condition: not stated')}</option>" for c in ms.CONDITIONS)
    return (f"{tok()}<label>Pasted link <input name='link' value='{v('link')}' maxlength='500' placeholder='https://… (saved as text, never opened by this system)'></label> "
            f"<label>Title <input name='title' value='{v('title')}' maxlength='120' required></label> <label>Price $ (optional) <input name='price' value='{v('price')}' inputmode='decimal'></label> "
            f"<label>City, ST or ZIP <input name='location' value='{v('location')}' maxlength='60' required></label> <label>Condition <select name='condition'>{cond}</select></label> "
            f"<label>Source <select name='source'>{src}</select></label> <label>Notes <input name='notes' value='{v('notes')}' maxlength='600'></label>")


def add_form(tok) -> str:
    return ("<details class='card small' id='add-find'><summary><b>Add a find</b> (something you saw on Facebook, Craigslist, OfferUp or another site)</summary>"
            "<p class='mut'>You type or paste what you saw. This system never visits those sites, never logs in and never fetches the link; "
            "what you enter is shown back as owner-entered and unverified.</p>"
            f"<form method='post' action='/market/find' class='mk-form'><input type='hidden' name='act' value='add'>{_fields(tok)}<button class='mk-add' type='submit'>Add find</button></form></details>")


def find_card(c: dict, tok, pref_buttons) -> str:
    r = c["find"]
    saved = " <span class='badge'>SAVED</span>" if c.get("saved") else ""
    price = f"<div class='pr'>${c['bid']:,.2f}</div><div class='small mut'>price as entered</div>" if c["bid"] is not None else "<div class='pr'>Price UNKNOWN</div>"
    where = e(c["city"]) + (f" · {round(c['distance'], 1):g} mi" if c["distance"] is not None else " · distance UNKNOWN (place not found; not counted as local)")
    edit = (f"<details class='small'><summary>Edit / delete</summary><form method='post' action='/market/find' class='mk-form'><input type='hidden' name='act' value='edit'>"
            f"<input type='hidden' name='find' value='{e(c['id'])}'>{_fields(tok, r)}<button type='submit'>Save changes</button></form>"
            f"<form method='post' action='/market/find' class='mk-xf'>{tok()}<input type='hidden' name='act' value='delete'><input type='hidden' name='find' value='{e(c['id'])}'>"
            "<button type='submit'>Delete (can be undone)</button></form></details>")
    return (f"<div class='mk-g' data-lot='{e(c['id'])}' data-find='1'><div class='ph small mut'>No photo (owner-entered)</div>{price}<div class='ti'><b>{e(c['title'])}</b>{saved}</div>"
            f"<div class='small'><b>{e(c['source'])}</b> · {where}</div><div class='small'>Condition: {e(c['condition'] or 'not stated')}</div>"
            + (f"<div class='small mut'>{e(c['description'])}</div>" if c["description"] else "") + f"<div class='small'>{TAG}</div>"
            f"<div class='small'><a class='mk-detail' href='{e(__import__('operator_ui.market_detail', fromlist=['x']).href(c))}'>View details</a> · {link_html(c['url']) if c['url'] else 'No link entered'}</div>"
            f"<div class='small mut'>added {e(r.get('created_at', ''))} by {e(r.get('created_by', ''))}" + (f" · edited {e(r.get('updated_at', ''))}" if r.get("updated_at") != r.get("created_at") else "") + f"</div>"
            f"{pref_buttons(c, tok)}{edit}</div>")


def section(res: list[dict], unch: list[dict], gone: list[dict], hidden_n: int, by_filters: int, tok, pref_buttons) -> str:
    prec, note = pv.for_cards(res)
    cards = "".join(pv.inject(find_card(c, tok, pref_buttons), prec.get(c["id"], "")) for c in res)
    opt = (f"<details class='mk-sec' id='finds-unchecked'><summary><b>{len(unch)} find(s) that could not be checked against your filters (unknown location or price; not counted as local or in range).</b></summary>"
           f"<div class='mk-gal'>{''.join(pv.inject(find_card(c, tok, pref_buttons), '') for c in unch)}</div></details>") if unch else ""
    dele = "".join(f"<li data-deleted='{e(r['id'])}'>{e(r['title'])} <span class='mut'>({e(mf.SOURCES.get(r['source'], r['source']))}, deleted {e(r.get('deleted_at', ''))})</span> "
                   f"<form method='post' action='/market/find' class='mk-pref' style='display:inline'>{tok()}<input type='hidden' name='act' value='undo'><input type='hidden' name='find' value='{e(r['id'])}'>"
                   "<button type='submit'>Undo delete</button></form></li>" for r in gone)
    return (f"<section class='mk-sec' id='your-finds'><h2>Your finds <span class='small mut'>({len(res)})</span></h2>"
            "<p class='small mut'>Owner-entered, not fetched, unverified. Not GSA results, not in the GSA counts, and not live listings: confirm on the original site before acting. "
            "The same price, distance, category, condition and hide filters apply." + (f" {hidden_n} hidden by you." if hidden_n else "") + (f" {by_filters} find(s) are hidden by your filters (price, distance, state, category focus or condition); loosen them to see those." if by_filters else "") + "</p>"
            + (f"<p class='small mut' id='finds-precedent-note'>{e(note)}</p>" if note and res else "")
            + (f"<div class='mk-gal'>{cards}</div>" if res else "<p class='mut small' id='finds-none'>No finds match your filters" + (" (some may be in the unchecked list below)." if unch else ".") + "</p>")
            + opt + add_form(tok)
            + (f"<details class='card small' id='deleted-finds'><summary><b>Deleted finds: {len(gone)}</b></summary><ul>{dele}</ul></details>" if gone else "") + "</section>")
