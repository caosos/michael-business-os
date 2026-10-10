"""F-47: Michael's Marketplace page: sidebar, search form, source status line, result cards. Saved searches are Wanted campaigns
with category `marketplace` (written through App.wanted_change, so CSRF + PIN + receipts are unchanged). All text escaped."""

from __future__ import annotations

import html
import secrets
from urllib.parse import quote, urlsplit

from . import market_search as ms
from .deal_ui import classify_url
from .live_demo import link_html

CATEGORY = "marketplace"
e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

CSS = """<style>.mk{display:flex;gap:18px;align-items:flex-start}.mk-side{flex:0 0 230px;position:sticky;top:8px}
.mk-main{flex:1;min-width:0}.mk-side .card{padding:10px 12px}.mk-side a{display:block;padding:4px 0}.mk-demo{border-top:2px dashed var(--line);margin-top:12px;padding-top:8px}
.mk-form label{display:inline-block;margin:0 10px 8px 0}.mk-res{display:flex;gap:12px}.mk-res img{width:120px;height:90px;object-fit:cover;border-radius:6px}
.mk-tag{font-size:12px;border:1px solid var(--line);border-radius:8px;padding:0 6px;margin-right:4px}
@media(max-width:700px){.mk{flex-direction:column}.mk-side{position:static;flex:none;width:100%}.mk-res{flex-direction:column}.mk-form input,.mk-form select{max-width:100%}}</style>"""


def _photo(url) -> str:
    try:
        host = urlsplit(url or "").hostname or ""
    except ValueError:
        host = ""
    if url and classify_url(url, hosts=[host])[0] == "live":
        return f"<img src='{e(url)}' alt='Original listing photo' loading='lazy' referrerpolicy='no-referrer'>"
    return "<div class='mut small' style='width:120px'>No photo from the seller</div>"


def _money(v) -> str:
    return "UNKNOWN (no bids yet)" if v is None else f"${v:,.2f}"


def render_card(c: dict) -> str:
    verdict, why = ms.decision(c)
    tags = "".join(f"<span class='mk-tag'>{e(k)}: {e(t)} ({e(tag)})</span>" for k in ("required", "preferred") for t, tag in (c.get("tags") or {}).get(k, []))
    where = e(c["city"] or "UNKNOWN") + (f" · {c['distance']:g} mi from your base" if c["distance"] is not None else " · distance UNKNOWN (place not located)")
    stale = " <b class='bad'>STALE: bid may have moved</b>" if c["stale"] else ""
    return (f"<div class='card mk-res'>{_photo(c['image'])}<div style='min-width:0'><h3 style='margin:0 0 4px'>{e(c['title'])} "
            f"<span class='badge'>{verdict}</span> <span class='lbl'>RESEARCH NEEDED</span></h3>"
            f"<p class='small'>{e(c['description']) or '<span class=mut>No description from the seller</span>'}</p>"
            f"<p>Current bid <b>{_money(c['bid'])}</b> (a bid, not a sold price) · closes {e(c['closes'] or 'UNKNOWN')} · {where} · "
            f"condition (seller says): {e(c['condition'] or 'UNKNOWN')}</p>"
            f"<p class='small'>Price math: bid {_money(c['bid'])} + buyer premium UNKNOWN + transport UNKNOWN + repair UNKNOWN "
            f"= all-in cost UNKNOWN · sold comp: none on file</p>{('<p>' + tags + '</p>') if tags else ''}"
            f"<p>Original listing: {link_html(c['url'])}</p>"
            f"<p class='small mut'>{e(why)}<br>Source {e(c['source'])} · fetched {e(c['fetched_at'])} · {e(c['kind'])}{stale}</p></div></div>")


def render_status(d: dict) -> str:
    if d["status"] != "connected":
        return f"<div class='flash err' id='source-status'><b>GSA Auctions: offline.</b> {e(d['message'])}</div>"
    warn = (f" <b class='bad'>STALE ({d['age_h']:g} h old): current bids may have changed.</b>" if d["stale"] else "")
    return (f"<p class='small' id='source-status'><b>GSA Auctions: connected (cached file)</b> · last fetched as of {e(d['as_of'])} "
            f"({d['age_h']:g} h ago) · {d['in_scope']} lots in nearby states of {d['in_file']} in the file{warn} · "
            f"not connected: {e(', '.join(ms.NOT_CONNECTED))}</p>")


def _sidebar(saved: list[dict], csrf: str, pin_html: str, tok) -> str:
    rows = []
    for r in saved:
        d = r["doc"]
        on = d["status"] == "ACTIVE"
        cid = e(d["campaign_id"])
        toggle = (f"<form method='post' action='/market/{cid}/{'pause' if on else 'resume'}' style='display:inline'>{tok()}{pin_html}"
                  f"<button class='small'>{'Disable' if on else 'Enable'}</button></form>") if d["status"] in ("ACTIVE", "PAUSED") else ""
        rows.append(f"<li><b>{e(d['title'])}</b> <span class='badge'>{'ON' if on else e(d['status'])}</span><br>"
                    f"<a style='display:inline' href='/market?run={cid}'>Run</a> · <a style='display:inline' href='/market?edit={cid}'>Edit</a> {toggle}</li>")
    saved_html = f"<ul style='padding-left:16px;margin:4px 0'>{''.join(rows)}</ul>" if rows else "<p class='small mut'>No saved searches yet.</p>"
    return ("<aside class='mk-side'><div class='card'><nav aria-label='Marketplace'>"
            "<a href='/market?go=1'><b>Find Deals Now</b></a><a href='/market?new=1'>+ New Search</a>"
            f"<h4 style='margin:10px 0 2px'>My Campaigns / Saved Searches</h4>{saved_html}"
            "<a href='/resale'>Saved Deals</a><a href='/market?go=1&amp;sort=closing&amp;closing_by=soon'>Auctions Closing Soon</a>"
            "<div class='mk-demo'><span class='small mut'>Separate area</span><a href='/?demo=1'>DEMO / training data</a></div></nav></div></aside>")


def _form(q: dict, cid: str | None, tok, pin_html: str) -> str:
    v = lambda k: e(", ".join(q[k]) if isinstance(q.get(k), list) else q.get(k) if q.get(k) is not None else "")  # noqa: E731
    sel = lambda name, opts, cur: f"<select name='{name}'>" + "".join(  # noqa: E731
        f"<option value='{e(o)}'{' selected' if str(cur) == o else ''}>{e(lbl)}</option>" for o, lbl in opts) + "</select>"
    keep = "".join(f"<input type='hidden' name='{k}' value='{v(k)}'>" for k in ("keywords", "base", "radius", "max_price", "required", "preferred", "exclude"))
    save = (f"<form method='post' action='/market/{'%s/edit' % e(cid) if cid else 'save'}' class='mk-form'>{tok()}{keep}"
            f"<label>Name this search <input name='title' maxlength='120' value='{v('keywords')}'></label> {pin_html} "
            f"<button name='do' value='save'>{'Save changes' if cid else 'Save this search'}</button></form>")
    return ("<div class='card'><form method='get' action='/market' class='mk-form'><input type='hidden' name='go' value='1'>"
            f"<label>Keywords <input name='keywords' size='22' value='{v('keywords')}'></label>"
            f"<label>Base city <input name='base' size='12' value='{v('base')}'></label>"
            f"<label>Radius (mi) <input name='radius' size='5' inputmode='decimal' value='{v('radius')}'></label>"
            f"<label>Max price $ <input name='max_price' size='7' inputmode='decimal' value='{v('max_price')}'></label>"
            f"<details><summary>More filters</summary>"
            f"<label>Condition (seller text) <input name='condition' size='10' value='{v('condition')}'></label>"
            f"<label>Must include <input name='required' size='14' value='{v('required')}'></label>"
            f"<label>Nice to include <input name='preferred' size='14' value='{v('preferred')}'></label>"
            f"<label>Exclude <input name='exclude' size='14' value='{v('exclude')}'></label>"
            f"<label>Source {sel('source', [('gsa', 'GSA Auctions')] + [(n.lower(), n + ' (not connected)') for n in ms.NOT_CONNECTED], q.get('source', 'gsa'))}</label>"
            f"<label>Type {sel('kind', [('any', 'Any'), ('auction', 'Auction'), ('fixed', 'Fixed price')], q.get('kind', 'any'))}</label>"
            f"<label>Closing by <input type='date' name='closing_by' value='{v('closing_by')}'></label>"
            f"<label>Sort {sel('sort', [(s, s.title()) for s in ms.SORTS], q.get('sort', 'closing'))}</label></details>"
            f"<button>Search</button></form>{save}"
            "<p class='small mut'>Saved: keywords, base city, radius, max price, must/nice/exclude terms. The other filters apply to this run only. "
            "A search never contacts anyone.</p></div>")


def render_page(q: dict, d: dict, results: list[dict], hidden: dict, saved: list[dict], csrf: str, pin_set: bool,
                edit_id: str | None = None, ran: bool = True, errors: list[str] | None = None) -> str:
    tok = lambda: f"<input type='hidden' name='csrf' value='{e(csrf)}'><input type='hidden' name='nonce' value='{secrets.token_hex(8)}'>"  # noqa: E731
    pin_html = "<input type='password' name='pin' placeholder='PIN' autocomplete='off' required>" if pin_set else "<span class='bad'>PIN not set: saving refused</span>"
    err = f"<div class='flash err'><b>Not saved.</b> {e('; '.join(errors))}</div>" if errors else ""
    if not ran:
        body = "<p class='mut'>Fill in the search and press Search. Nothing is fetched from the internet by this page.</p>"
    elif q["source"] != "gsa":
        body = f"<div class='card'><b>{e(q['source'])}: not connected.</b> No results are shown for a source that is not wired; nothing is mocked.</div>"
    elif q["kind"] == "fixed":
        body = "<div class='card'>GSA Auctions lists auctions only; no fixed-price results from a connected source.</div>"
    elif d["status"] != "connected":
        body = ""
    else:
        hid = ", ".join(f"{n} by {k}" for k, n in hidden.items() if n)
        body = (f"<h2>{len(results)} result{'s' if len(results) != 1 else ''}</h2>" + (f"<p class='small mut'>Hidden: {e(hid)}.</p>" if hid else "")
                + ("".join(render_card(c) for c in results) or "<p class='mut'>Nothing matches. Loosen a filter.</p>"))
    return (CSS + "<h1 class='pagehead'>Michael's Marketplace</h1><div class='mk'>" + _sidebar(saved, csrf, pin_html, tok)
            + f"<section class='mk-main'>{err}{_form(q, edit_id, tok, pin_html)}{render_status(d)}{body}</section></div>")


def save_form(f: dict) -> dict:
    """Marketplace form -> the Wanted campaign form fields (exclude terms ride in nice_to_have as `exclude:word`)."""
    q = ms.parse_query({k: [v] for k, v in f.items()})
    nice = list(q["preferred"]) + [ms.EXCLUDE_PREFIX + t for t in q["exclude"]]
    return {**{k: f[k] for k in ("csrf", "pin", "nonce") if k in f}, "title": (f.get("title") or q["keywords"]).strip() or "Marketplace search",
            "category": CATEGORY, "keywords": q["keywords"].replace(" ", ", "), "max_price_usd": "" if q["max_price"] is None else str(q["max_price"]),
            "radius_miles": "" if q["radius"] is None else str(q["radius"]), "origin": q["base"],
            "must_have": ", ".join(q["required"]), "nice_to_have": ", ".join(nice), "level": "RECOMMEND"}


def go_url(q: dict) -> str:
    return "/market?go=1&" + "&".join(f"{k}={quote(str(v))}" for k, v in q.items() if v not in (None, "", []))
