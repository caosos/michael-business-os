"""F-47: Michael's Marketplace page: sidebar, search form, source status line, result cards. Saved searches are Wanted campaigns
with category `marketplace` (written through App.wanted_change, so CSRF + PIN + receipts are unchanged). All text escaped."""

from __future__ import annotations

import html
import secrets
from urllib.parse import quote, urlsplit

from . import landing_fix
from . import market_search as ms
from .deal_ui import classify_url
from .live_demo import link_html

CATEGORY = "marketplace"
e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

CSS = """<style>.mk{display:flex;gap:18px;align-items:flex-start}.mk-side{flex:0 0 230px;position:sticky;top:8px}
.mk-main{flex:1;min-width:0}.mk-side .card{padding:10px 12px}.mk-side a{display:block;padding:4px 0}.mk-demo{border-top:2px dashed var(--line);margin-top:12px;padding-top:8px}
.mk-form label{display:inline-block;margin:0 10px 8px 0}.mk-res{display:flex;gap:12px}.mk-res img{width:120px;height:90px;object-fit:cover;border-radius:6px}
.mk-tag{font-size:12px;border:1px solid var(--line);border-radius:8px;padding:0 6px;margin-right:4px}
.mk-form button,.mk-side button{background:var(--acc);color:var(--bg);width:auto;opacity:1}.mk-form button:hover{filter:brightness(1.1)}
.mk-form button:focus-visible,.mk-form input:focus-visible,.mk-side a:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
.mk-form button.mk-go{font-size:16px;padding:10px 28px}.mk-chips .chip{background:var(--card)}
.mk-range input[type=range]{width:46%;display:inline-block;margin:0;padding:0}.mk-range input[type=number]{width:110px;display:inline-block}
.mk-sec{border-top:2px dashed var(--line);margin-top:16px}
@media(max-width:700px){.mk{flex-direction:column}.mk-side{position:static;flex:none;width:100%}.mk-res{flex-direction:column}.mk-form input,.mk-form select{max-width:100%}}</style>"""


def _photo(url, listing=None) -> str:
    if landing_fix.is_gsa_image(url):
        return landing_fix.photo_tile(url, listing)
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
    where = e(c["city"] or "UNKNOWN") + (f" · {c['distance']:g} mi from your base" if c["distance"] is not None else " · distance UNKNOWN (place not in our small local gazetteer; see the note above)")
    stale = " <b class='bad'>STALE: bid may have moved</b>" if c["stale"] else ""
    return (f"<div class='card mk-res'>{_photo(c['image'], c['url'])}<div style='min-width:0'><h3 style='margin:0 0 4px'>{e(c['title'])} "
            f"<span class='badge'>{verdict}</span> <span class='lbl'>RESEARCH NEEDED</span></h3>"
            f"<p class='small'>{e(c['description']) or '<span class=mut>No description from the seller</span>'}</p>"
            f"<p><span class='lbl'>AUCTION</span> Current bid <b>{_money(c['bid'])}</b> (a bid, not a sold price or final cost) · Asking price: none (auction) · closes {e(c['closes'] or 'UNKNOWN')} · {where} · "
            f"condition (seller says): {e(c['condition'] or 'UNKNOWN')}</p>"
            f"<p class='small'>Price math: bid {_money(c['bid'])} + buyer premium UNKNOWN + transport UNKNOWN + repair UNKNOWN "
            f"= all-in cost UNKNOWN (never the final cost) · sold comp: none on file</p>{('<p>' + tags + '</p>') if tags else ''}{('<p class=small><b>Not checked against your filters:</b> ' + e('; '.join(c['unchecked'])) + '</p>') if c.get('unchecked') else ''}"
            f"<p>Original listing: {link_html(c['url'])}</p>"
            f"<p class='small mut'>{e(why)}<br>Source {e(c['source'])} · fetched {e(c['fetched_at'])} · {e(c['kind'])}{stale}</p></div></div>")


def distance_caveat(q: dict, results: list[dict]) -> str:
    """F-50: distances come from approximate town centroids in small local gazetteers; say what was and was not located."""
    if not results:
        return ""
    base = (q.get("base") or "").strip() or ms.DEFAULT_BASE
    towns = lambda sel: sorted({c["city"] or "no town given" for c in results if sel(c)})  # noqa: E731
    got, miss = towns(lambda c: c["distance"] is not None), towns(lambda c: c["distance"] is None)
    origin = f"Your base '{e(base)}' is located." if ms._origin(base) else f"Your base '{e(base)}' is NOT located, so no distance can be shown."
    lots = f"Lot towns located: {e(', '.join(got)) or 'none'}. Lot towns NOT located (distance UNKNOWN, not 'far away'): {e(', '.join(miss)) or 'none'}."
    return ("<div class='card small' id='distance-caveat'><b>About distances.</b> Place coordinates are approximate town centroids from a small local "
            "gazetteer with limited coverage (mostly Arkansas and a few nearby cities). Distances are rough straight-line miles, good to a few miles at best. "
            "A town missing from the gazetteer shows 'distance UNKNOWN' because we cannot place it, not because it is far; out-of-state lots are often in that group. "
            f"{origin} {lots} No online lookup is made.</div>")


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
            "</nav></div></aside>")


def _slider(q: dict) -> str:
    lo, hi = ms.PRICE_RANGE
    g = lambda k: "" if q.get(k) is None else f"{q[k]:g}"  # noqa: E731
    cl = lambda k, d: f"{min(max(q[k], lo), hi):g}" if q.get(k) is not None else str(d)  # noqa: E731
    return ("<fieldset class='mk-range' style='border:1px solid var(--line);border-radius:8px;margin:0 0 8px'><legend>Price range (current bid)</legend>"
            f"<label>Min $ <input type='number' id='min_price' name='min_price' min='0' step='any' inputmode='decimal' value='{e(g('min_price'))}'></label> "
            f"<label>Max $ <input type='number' id='max_price' name='max_price' min='0' step='any' inputmode='decimal' value='{e(g('max_price'))}'></label>"
            f"<div><label>Min slider <input type='range' id='min_r' name='min_r' min='{lo}' max='{hi}' step='1' value='{cl('min_price', lo)}' aria-label='Minimum price slider'></label> "
            f"<label>Max slider <input type='range' id='max_r' name='max_r' min='{lo}' max='{hi}' step='1' value='{cl('max_price', hi)}' aria-label='Maximum price slider'></label>"
            f"<input type='hidden' name='prev_min' value='{cl('min_price', lo)}'><input type='hidden' name='prev_max' value='{cl('max_price', hi)}'></div>"
            f"<p class='small mut'>Type a number, or move a slider (arrow keys work), then press Search; the control you changed is the one used. "
            f"The ${lo:,} to ${hi:,} slider range is only the scale of this control: it is not a budget and authorizes no spending. Leave a box empty for no limit.</p></fieldset>")


def chips(q: dict) -> str:
    """The filters actually applied to this run, as plain chips (also shown when nothing is limited)."""
    c = []
    c.append(f"Origin: {q['base']}" + (" (ZIP 72032)" if q["base"].strip().lower() in ("", "conway", "conway ar", "conway, ar") else ""))
    c.append(f"Radius: {q['radius']:g} mi (known distances only)" if q["radius"] is not None else "Radius: none")
    c.append("Mode: BROAD inventory (all categories)" if q.get("broad") else "Mode: repairable trailers/equipment focus: " + (", ".join(q["any"]) or "none"))
    if q.get("min_price") is not None:
        c.append(f"Min price: ${q['min_price']:,.0f}")
    if q.get("max_price") is not None:
        c.append(f"Max price: ${q['max_price']:,.0f}")
    for lbl, k in (("Keywords", "keywords"), ("Must include", "required"), ("Nice to include", "preferred"), ("Exclude", "exclude")):
        v = ", ".join(q[k]) if isinstance(q[k], list) else q[k]
        if v:
            c.append(f"{lbl}: {v}")
    for lbl, k in (("Condition", "condition"), ("Closing by", "closing_by")):
        if q.get(k):
            c.append(f"{lbl}: {q[k]}")
    return ("<p class='mk-chips' id='applied-filters' aria-label='Applied filters'><b class='small'>Applied filters:</b> "
            + "".join(f"<span class='chip'>{e(x)}</span>" for x in c) + "</p>")


def _form(q: dict, cid: str | None, tok, pin_html: str) -> str:
    v = lambda k: e(", ".join(q[k]) if isinstance(q.get(k), list) else q.get(k) if q.get(k) is not None else "")  # noqa: E731
    sel = lambda name, opts, cur: f"<select name='{name}'>" + "".join(  # noqa: E731
        f"<option value='{e(o)}'{' selected' if str(cur) == o else ''}>{e(lbl)}</option>" for o, lbl in opts) + "</select>"
    keep = "".join(f"<input type='hidden' name='{k}' value='{v(k)}'>" for k in ("keywords", "base", "radius", "min_price", "max_price", "any", "required", "preferred", "exclude"))
    keep += "<input type='hidden' name='broad' value='1'>" if q.get("broad") else ""
    save = (f"<form method='post' action='/market/{'%s/edit' % e(cid) if cid else 'save'}' class='mk-form'>{tok()}{keep}"
            f"<label>Name this search <input name='title' maxlength='120' value='{v('keywords')}'></label> {pin_html} "
            f"<button name='do' value='save'>{'Save changes' if cid else 'Save this search'}</button></form>")
    return ("<div class='card'><form method='get' action='/market' class='mk-form'><input type='hidden' name='go' value='1'>"
            f"<label>Origin (city or ZIP) <input name='base' size='14' value='{v('base')}'></label>"
            f"<label>Radius (mi) <input name='radius' size='5' inputmode='decimal' value='{v('radius')}'></label>"
            f"<label>Category / keywords, any of <input name='any' size='24' value='{v('any')}'></label>"
            f"<label><input type='checkbox' name='broad' value='1'{' checked' if q.get('broad') else ''}> Broad inventory mode (ignore the category focus; off by default)</label>"
            f"{_slider(q)}"
            f"<label>Keywords, all of <input name='keywords' size='22' value='{v('keywords')}'></label>"
            f"<details><summary>More filters</summary>"
            f"<label>Condition (seller text) <input name='condition' size='10' value='{v('condition')}'></label>"
            f"<label>Must include <input name='required' size='14' value='{v('required')}'></label>"
            f"<label>Nice to include <input name='preferred' size='14' value='{v('preferred')}'></label>"
            f"<label>Exclude <input name='exclude' size='14' value='{v('exclude')}'></label>"
            f"<label>Source {sel('source', [('gsa', 'GSA Auctions')] + [(n.lower(), n + ' (not connected)') for n in ms.NOT_CONNECTED], q.get('source', 'gsa'))}</label>"
            f"<label>Type {sel('kind', [('any', 'Any'), ('auction', 'Auction'), ('fixed', 'Fixed price')], q.get('kind', 'any'))}</label>"
            f"<label>Closing by <input type='date' name='closing_by' value='{v('closing_by')}'></label>"
            f"<label>Sort {sel('sort', [(s, s.title()) for s in ms.SORTS], q.get('sort', 'closing'))}</label></details>"
            f"<button class='mk-go' type='submit'>Search</button></form>{save}"
            "<p class='small mut'>Saved with a search: keywords, origin, radius, max price, must/nice/exclude terms. Min price, category focus, broad mode and the other filters apply to this run (and are remembered while you move around). "
            "A search never contacts anyone.</p></div>")


def working_capital(verified=None) -> str:
    """The documented working-capital planning setting, labelled apart from verified cash. Neither is a spend authorization."""
    amt = ms.working_capital()
    return ("<div class='card small' id='working-capital'><b>Working capital (planning setting, not cash).</b> "
            f"<span class='lbl'>SETTING</span> ${amt:,.0f} protected principal, from the owner's documented capital model (docs/product/DEAL_SNIFFER_START_HERE.md section 1; "
            "override with MBOS_WORKING_CAPITAL_USD). <br><b>Verified cash:</b> <span class='unk'>UNKNOWN</span> unless a figure is recorded on "
            "<a href='/numbers'>My numbers</a>. A setting is not a balance and nothing here approves a bid, a purchase or a payment.</div>")


def gsa_explainer() -> str:
    return ("<details class='small' id='gsa-explainer'><summary><b>What is GSA?</b></summary><p><b>GSA</b> here means the U.S. General Services Administration's "
            "<b>government surplus auctions</b> (gsaauctions.gov): federal agencies sell used vehicles, trailers and equipment to the public.</p>"
            "<ul><li><b>Freshness:</b> this page reads a saved copy (cache) of the GSA list, never the live site. The line below shows when the copy was fetched; "
            "bids and closing times may have changed since, and a copy older than 6 hours is marked STALE.</li>"
            "<li><b>Photos:</b> GSA's photo server requires a GSA login, so photos usually cannot load here. We show a plain tile instead of a fake or broken picture, "
            "and we do not log in or bypass anything.</li>"
            "<li><b>Verify:</b> use the Original listing link on a card (the lot's own GSA page) to confirm the current bid, condition, location and rules before acting.</li>"
            "<li>A current bid is not a final price: buyer premium, transport and repairs are not known here.</li></ul></details>")


def render_page(q: dict, d: dict, results: list[dict], hidden: dict, saved: list[dict], csrf: str, pin_set: bool,
                edit_id: str | None = None, ran: bool = True, errors: list[str] | None = None, unchecked: list[dict] | None = None) -> str:
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
        unchecked = unchecked or []
        scope = f" within {q['radius']:g} mi of {e(q['base'])}" if q["radius"] is not None else ""
        zero = ("<p class='mut' id='zero-results'><b>0 results</b> match every filter" + scope + ". Nothing is padded in"
                + (f"; {len(unchecked)} lot(s) could not be checked and are listed below, not counted" if unchecked else "") + ". Loosen a filter or widen the radius.</p>")
        opt = ((f"<div class='mk-sec' id='unchecked-section'><h2>Optional: {len(unchecked)} lot(s) that could not be checked (not counted as local or in range)</h2>"
                "<p class='small mut'>Their location was not found or they have no bid yet, so the radius or price range cannot be tested. They are shown only so nothing is hidden; "
                "verify on the original listing.</p>" + "".join(render_card(c) for c in unchecked) + "</div>") if unchecked else "")
        body = (chips(q) + f"<h2>{len(results)} result{'s' if len(results) != 1 else ''}{scope}</h2>" + (f"<p class='small mut'>Hidden: {e(hid)}.</p>" if hid else "")
                + distance_caveat(q, results + unchecked) + ("".join(render_card(c) for c in results) or zero) + opt)
    return (CSS + "<h1 class='pagehead'>Michael's Marketplace</h1><div class='mk'>" + _sidebar(saved, csrf, pin_html, tok)
            + f"<section class='mk-main'>{err}{_form(q, edit_id, tok, pin_html)}{working_capital()}{gsa_explainer()}{render_status(d)}{body}</section></div>")


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
