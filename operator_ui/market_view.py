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

CSS = """<style>main{max-width:1900px}.banner{padding:3px 16px;font-size:13px}header{padding:4px 16px;flex-wrap:nowrap}header b{display:none}header nav{display:flex;gap:2px 12px;flex-wrap:wrap}header nav a{margin:0;white-space:nowrap}main{padding:8px 16px}.pagehead{margin:4px 0 8px;font-size:20px}.mk-row>h2{margin:8px 0 4px}.mk-gal>p{grid-column:1/-1;margin:2px 0}.mk{display:flex;gap:18px;align-items:flex-start}.mk-side{flex:0 0 210px}
.mk-main{flex:1;min-width:0}.mk-side .card{padding:10px 12px}.mk-side a{display:block;padding:4px 0}.mk-demo{border-top:2px dashed var(--line);margin-top:12px;padding-top:8px}
.mk-form label{display:inline-block;margin:0 10px 8px 0}.mk-res{display:flex;gap:12px}.mk-res img{width:120px;height:90px;object-fit:cover;border-radius:6px}
.mk-tag{font-size:12px;border:1px solid var(--line);border-radius:8px;padding:0 6px;margin-right:4px}
.mk-form button,.mk-side button{background:var(--acc);color:var(--bg);width:auto;opacity:1}.mk-form button:hover{filter:brightness(1.1)}
.mk-form button:focus-visible,.mk-form input:focus-visible,.mk-side a:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
.mk-form button.mk-go{font-size:16px;padding:10px 28px}.mk-chips .chip{background:var(--card);font-size:12px;padding:1px 8px}.mk-chips{margin:4px 0}
.mk-range input[type=range]{width:46%;display:inline-block;margin:0;padding:0}.mk-range input[type=number]{width:110px;display:inline-block}
.mk-sec2{font-size:13px}.mk-side .card button.mk-go{display:block;width:100%;margin-top:6px}.mk-sec{border-top:2px dashed var(--line);margin-top:16px}
.mk-gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(230px,100%),1fr));gap:10px}.mk-g{border:1px solid var(--line);border-radius:8px;padding:8px;background:var(--card);min-width:0}
.mk-g .ph{height:110px;display:flex;align-items:center;justify-content:center;border:1px dashed var(--line);border-radius:6px;text-align:center;overflow:hidden}.mk-g img{width:100%;height:110px;object-fit:cover;border-radius:6px}
.mk-g .pr{font-size:18px;font-weight:700;margin:4px 0 0}.mk-g .ti{font-size:14px;margin:2px 0;overflow-wrap:anywhere}.mk-g button,.mk-pref button{font-size:12px;padding:2px 6px;margin:1px;width:auto;background:var(--acc);color:var(--bg);opacity:1}.mk-pref button:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
.mk-side .mk-range input[type=range],.mk-side .mk-range input[type=number]{width:100%}.mk-side label{display:block}.mk-side .mk-range>label{display:inline-block;width:47%;margin:0 1% 4px 0}.mk-side .mk-range .small{margin:4px 0}.mk-side .mk-range div label{margin:0}.mk-side input[type=checkbox]{width:auto}
.mk-bar{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:flex-end}.mk-bar label{display:block;margin:0;font-size:13px}.mk-bar input,.mk-bar select{width:auto;padding:4px 6px;margin:0;max-width:100%}.mk-bar details{flex:1 1 100%}.mk-bar button.mk-go{padding:6px 22px}.mk-main>.card{padding:8px 12px}.mk-main h2{margin:6px 0}.mk-side input[type=number],.mk-side input[type=text],.mk-side input:not([type]){padding:4px 6px}.mk-jump{display:none}.mk-form details,#save-search{margin:4px 0}
@media(max-width:700px){header nav{flex-wrap:nowrap;overflow-x:auto;padding-bottom:2px}.mk{flex-direction:column}.mk-main{order:2}.mk-side{order:1}.mk-jump{display:block}.mk-g .ph,.mk-g img{height:90px}.mk-side{position:static;flex:none;width:100%}.mk-res{flex-direction:column}.mk-form input,.mk-form select{max-width:100%}}</style>"""


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


def pref_buttons(c: dict, tok) -> str:
    b = lambda a, lbl: f"<button name='act' value='{a}'>{lbl}</button>"  # noqa: E731
    return (f"<form method='post' action='/market/pref' class='mk-pref'>{tok()}<input type='hidden' name='lot' value='{e(c['id'])}'>"
            f"<input type='hidden' name='title' value='{e(c['title'])}'>{b('unsave', 'Unsave') if c.get('saved') else b('save', 'Save')}"
            f"{b('dismiss', 'Not interested')}{b('more', 'More like this')}{b('less', 'Less like this')}</form>"
            + (f"<p class='small mut' data-why>{e(c['why'])}</p>" if c.get("why") else ""))


def gallery_card(c: dict, tok) -> str:
    """F-52 (B): dense card: photo (or an honest placeholder), price attached, short title, town, closing; details on the original listing."""
    img = _photo(c["image"], c["url"])
    ph = img if img.startswith("<img") else f"<div class='ph small mut'>{img}</div>"      # the honest tile/placeholder; never a faked picture
    price = "<div class='pr'>No bids yet</div><div class='small mut'>price UNKNOWN</div>" if c["bid"] is None else f"<div class='pr'>${c['bid']:,.0f}</div><div class='small mut'>current bid</div>"
    town = e(c["city"] or "town UNKNOWN") + (f" · {round(c['distance'], 1):g} mi" if c["distance"] is not None else " · distance UNKNOWN")
    ti = c["title"] if len(c["title"]) <= 60 else c["title"][:59] + "…"
    flag = " <span class='badge'>SAVED</span>" if c.get("saved") else ""
    return (f"<div class='mk-g' data-lot='{e(c['id'])}'>{ph}{price}<div class='ti'><b>{e(ti)}</b>{flag}</div><div class='small'>{town}</div>"
            f"<div class='small mut'>closes {e(c['closes'] or 'UNKNOWN')} · posted age: not given · auction, all-in cost unknown</div>"
            f"<div class='small'>{link_html(c['url'])} · <span class='lbl'>WATCH</span></div>{pref_buttons(c, tok)}</div>")


def gallery(cards: list[dict], q: dict, tok) -> str:
    out = []
    for name, row in ms.gallery_rows(cards, q):
        body = "".join(gallery_card(c, tok) for c in row) or "<p class='mut small'>No matching known inventory in this category (known = the cached GSA list only).</p>"
        out.append(f"<section class='mk-row' data-row='{e(name)}'><h2 style='text-transform:capitalize'>{e(name)} <span class='small mut'>({len(row)})</span></h2><div class='mk-gal'>{body}</div></section>")
    return "".join(out)


def prefs_panel(d: dict, tok) -> str:
    f = lambda a, lbl: f"<form method='post' action='/market/pref' style='display:inline' class='mk-pref'>{tok()}<button name='act' value='{a}'>{lbl}</button></form>"  # noqa: E731
    state = "ON" if d["enabled"] else "OFF"
    return (f"<details class='card small' id='prefs'><summary><b>Suggestions: {state}</b> (how your clicks reorder results)</summary>{e(__import__('operator_ui.market_prefs', fromlist=['x']).summary(d))}<br>"
            "Your clicks only reorder or hide what already passed your filters; they never widen a price, radius or exclusion, and they say nothing about profit.<br>"
            f"{f('disable', 'Turn off') if d['enabled'] else f('enable', 'Turn on')} {f('reset', 'Reset')}</details>")


def render_card(c: dict, tok=None) -> str:
    verdict, why = ms.decision(c)
    tags = "".join(f"<span class='mk-tag'>{e(k)}: {e(t)} ({e(tag)})</span>" for k in ("required", "preferred") for t, tag in (c.get("tags") or {}).get(k, []))
    where = e(c["city"] or "UNKNOWN") + (f" · {round(c['distance'], 1):g} mi from your base" if c["distance"] is not None else " · distance UNKNOWN (place not in our small local gazetteer; see the note above)")
    stale = " <b class='bad'>STALE: bid may have moved</b>" if c["stale"] else ""
    L = c.get("labels") or ms.auction_labels({})
    return (f"<div class='card mk-res'>{_photo(c['image'], c['url'])}<div style='min-width:0'><h3 style='margin:0 0 4px'>{e(c['title'])} "
            f"<span class='badge'>{verdict}</span> <span class='lbl'>RESEARCH NEEDED</span></h3>"
            f"<p class='small'>{e(c['description']) or '<span class=mut>No description from the seller</span>'}</p>"
            f"<p><span class='lbl'>AUCTION</span> Current bid <b>{_money(c['bid'])}</b> (a bid, not a sold price or final cost) · Asking price: none (auction) · closes {e(c['closes'] or 'UNKNOWN')} · {where} · "
            f"condition (seller says): {e(c['condition'] or 'UNKNOWN')}</p>"
            f"<p class='small' id='auction-labels'>Next minimum bid: {e(L['next_min_text'])} · Reserve: {e(L['reserve_text'])} · source GSA Auctions cache</p>"
            f"<p class='small'>Price math: bid {_money(c['bid'])} + buyer premium UNKNOWN + transport UNKNOWN + repair UNKNOWN "
            f"= all-in cost UNKNOWN (never the final cost) · sold comp: none on file</p>{('<p>' + tags + '</p>') if tags else ''}{('<p class=small><b>Not checked against your filters:</b> ' + e('; '.join(c['unchecked'])) + '</p>') if c.get('unchecked') else ''}"
            f"<p>Original listing: {link_html(c['url'])}</p>{pref_buttons(c, tok) if tok else ''}"
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
    return ("<details class='card small' id='distance-caveat'><summary><b>About distances</b> (approximate; unknown is not far)</summary>Place coordinates are approximate town centroids from a small local "
            "gazetteer with limited coverage (mostly Arkansas and a few nearby cities). Distances are rough straight-line miles, good to a few miles at best. "
            "A town missing from the gazetteer shows 'distance UNKNOWN' because we cannot place it, not because it is far; out-of-state lots are often in that group. "
            f"{origin} {lots} No online lookup is made.</details>")


def render_status(d: dict) -> str:
    if d["status"] != "connected":
        return f"<div class='flash err' id='source-status'><b>GSA Auctions: offline.</b> {e(d['message'])}</div>"
    warn = (f" <b class='bad'>STALE ({d['age_h']:g} h old): current bids may have changed.</b>" if d["stale"] else "")
    return (f"<p class='small' id='source-status' style='margin:6px 0'><b>GSA Auctions: connected (cached file)</b> · last fetched {e(str(d['as_of'])[:16].replace('T', ' '))} UTC "
            f"({d['age_h']:g} h ago) · {d['in_scope']} lots in nearby states of {d['in_file']} in the file{warn} · "
            f"not connected: {e(', '.join(ms.NOT_CONNECTED))}</p>")


def chip_url(q: dict, drop: str | None = None) -> str:
    """F-136: a GET link that re-runs the current filters without one state (the chip's remove button). No script, no write."""
    j = lambda k: ", ".join(q[k]) if isinstance(q.get(k), list) else q.get(k)  # noqa: E731
    pairs = [(k, j(k)) for k in ("keywords", "base", "radius", "min_price", "max_price", "any", "condition", "required", "preferred", "exclude", "source", "kind", "closing_by", "sort", "view")]
    pairs += [("broad", "1")] * bool(q.get("broad")) + [("cat", c) for c in q.get("cats") or []] + [(f"row{i}", r) for i, r in enumerate(q.get("rows") or [], 1) if i <= 4]
    pairs += [("loc_mode", q.get("loc_mode", "distance"))] + [("also_radius", "1")] * bool(q.get("also_radius")) + [("state", s) for s in q.get("states") or [] if s != drop]
    return "/market?go=1&amp;" + "&amp;".join(f"{k}={quote(str(v))}" for k, v in pairs if v not in (None, ""))


def scope_text(q: dict) -> str:
    """F-136: the location scope actually applied to this run, in words (the mode is never implicit)."""
    if q.get("loc_mode") == "state":
        st = ", ".join(q.get("states") or []) or "none selected"
        return f"By State: {st}" + (f" AND within {q['radius']:g} mi of {q['base']}" if q.get("also_radius") and q["radius"] is not None else "; the radius is NOT applied")
    return f"By Distance: " + (f"within {q['radius']:g} mi of {q['base']} (known distances only)" if q["radius"] is not None else "no radius") + "; states are NOT applied"


def location_panel(q: dict) -> str:
    """F-136: compact Location panel: By State / By Distance modes, searchable state list, multi-select checkboxes, removable chips (all inside the search form, no script)."""
    v = lambda k: e(q.get(k) if q.get(k) is not None else "")  # noqa: E731
    by_state, sel, find = q.get("loc_mode") == "state", q.get("states") or [], (q.get("state_find") or "").strip().lower()
    mode = lambda val, lbl: f"<label><input form='mkform' type='radio' name='loc_mode' value='{val}'{' checked' if (val == 'state') == by_state else ''}> {lbl}</label> "  # noqa: E731
    shown = [(c, n) for c, n in ms.US_STATES.items() if c in sel or not find or find in n.lower() or find == c.lower()]
    boxes = "".join(f"<label class='st'><input form='mkform' type='checkbox' name='state' value='{c}'{' checked' if c in sel else ''}> {c} {e(n)}</label>" for c, n in shown) \
        or "<span class='small mut'>No state matches that search.</span>"
    hide = "".join(f"<input form='mkform' type='hidden' name='state' value='{c}'>" for c in sel if c not in {c2 for c2, _ in shown})
    chip = "".join(f"<span class='chip'>{c} <a href='{chip_url(q, c)}' aria-label='Remove {c}' title='Remove {c}'>×</a></span>" for c in sel) or "<span class='small mut'>No states selected</span>"
    return ("<fieldset id='location-panel' style='border:1px solid var(--line);border-radius:8px;margin:0 0 8px'><legend>Location</legend>"
            f"<div role='radiogroup' aria-label='Location mode'>{mode('distance', 'By Distance')}{mode('state', 'By State')}</div>"
            f"<label>ZIP or city <input form='mkform' name='base' size='12' value='{v('base')}'></label>"
            f"<label>Radius (mi) <input form='mkform' name='radius' size='5' inputmode='decimal' value='{v('radius')}'></label>"
            f"<details id='state-picker'{' open' if find else ''}><summary>States <span class='small'>({len(sel)} selected)</span></summary>"
            f"<label>Find a state <input form='mkform' name='state_find' size='10' value='{e(q.get('state_find') or '')}'></label>"
            f"<div class='st-list' style='max-height:130px;overflow:auto'>{boxes}</div>{hide}"
            f"<label><input form='mkform' type='checkbox' name='also_radius' value='1'{' checked' if q.get('also_radius') else ''}> In By State mode, also keep the radius</label></details>"
            f"<div id='state-chips' aria-label='Selected states'>{chip}</div>"
            f"<p class='small mut' id='location-scope'>{e(scope_text(q))}. A lot with no known state or distance is never counted as local; it is listed as not checked.</p></fieldset>")


def _side_filters(q: dict) -> str:
    """F-52 (B): origin/ZIP, radius, price and category checkboxes live in the narrow left sidebar; they belong to the search form (form='mkform')."""
    v = lambda k: e(q.get(k) if q.get(k) is not None else "")  # noqa: E731
    cats = "".join(f"<label><input type='checkbox' form='mkform' name='cat' value='{e(k)}'{' checked' if k in q.get('cats', []) else ''}> {e(k.title())}</label>" for k in ms.ROW_CATS)
    return ("<div class='card' id='mkfilters'><b>Filters</b>"
            f"{location_panel(q)}"
            f"<button class='mk-go' type='submit' form='mkform'>Search Now</button>{_slider(q, 'mkform')}"
            f"<b>Categories</b>{cats}<p class='small mut'>None checked = your rows below (default trailers and equipment).</p></div>")


def _sidebar(saved: list[dict], csrf: str, pin_html: str, tok, q: dict, save: str = "") -> str:
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
    return ("<aside class='mk-side'>" + _side_filters(q) + "<div class='card'><nav aria-label='Marketplace'>"
            "<p class='small mut' style='margin:0 0 4px'>More</p><a class='mk-sec2' href='/market?new=1'>New Search</a>"
            f"{save}<details><summary>My Campaigns / Saved Searches ({len(rows)})</summary>{saved_html}</details>"
            "<a class='mk-sec2' href='/resale'>Saved Deals</a><a class='mk-sec2' href='/market?go=1&amp;sort=closing&amp;closing_by=soon'>Auctions Closing Soon</a>"
            "</nav></div></aside>")


def _slider(q: dict, form: str = "") -> str:
    lo, hi = ms.PRICE_RANGE
    g = lambda k: "" if q.get(k) is None else f"{q[k]:g}"  # noqa: E731
    cl = lambda k, d: f"{min(max(q[k], lo), hi):g}" if q.get(k) is not None else str(d)  # noqa: E731
    return ("<fieldset class='mk-range' style='border:1px solid var(--line);border-radius:8px;margin:0 0 8px'><legend>Price range (current bid)</legend>"
            f"<label>Min $ <input form='{form}' type='number' id='min_price' name='min_price' min='0' step='any' inputmode='decimal' value='{e(g('min_price'))}'></label> "
            f"<label>Max $ <input form='{form}' type='number' id='max_price' name='max_price' min='0' step='any' inputmode='decimal' value='{e(g('max_price'))}'></label>"
            f"<div><label>Min slider <input form='{form}' type='range' id='min_r' name='min_r' min='{lo}' max='{hi}' step='1' value='{cl('min_price', lo)}' aria-label='Minimum price slider'></label> "
            f"<label>Max slider <input form='{form}' type='range' id='max_r' name='max_r' min='{lo}' max='{hi}' step='1' value='{cl('max_price', hi)}' aria-label='Maximum price slider'></label>"
            f"<input form='{form}' type='hidden' name='prev_min' value='{cl('min_price', lo)}'><input form='{form}' type='hidden' name='prev_max' value='{cl('max_price', hi)}'></div>"
            f"<p class='small mut'>Type a number or move a slider, then Search; the one you changed is used. Blank = no limit. "
            f"The ${lo:,} to ${hi:,} range is only this control's scale, not a budget or spending authority.</p></fieldset>")


def chips(q: dict) -> str:
    """The filters actually applied to this run, as plain chips (also shown when nothing is limited)."""
    c = []
    c.append(f"Origin: {q['base']}" + (" (ZIP 72032)" if q["base"].strip().lower() in ("", "conway", "conway ar", "conway, ar") else ""))
    c.append("Location: " + scope_text(q)) if q.get("loc_mode") == "state" else c.append((f"Radius: {q['radius']:g} mi (known distances only)" if q["radius"] is not None else "Radius: none") + "; Location mode: By Distance (states not applied)")
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


def _save(q: dict, cid: str | None, tok, pin_html: str) -> str:
    v = lambda k: e(", ".join(q[k]) if isinstance(q.get(k), list) else q.get(k) if q.get(k) is not None else "")  # noqa: E731
    keep = "".join(f"<input type='hidden' name='{k}' value='{v(k)}'>" for k in ("keywords", "base", "radius", "min_price", "max_price", "any", "required", "preferred", "exclude", "condition"))
    keep += f"<input type='hidden' name='loc_mode' value='{q.get('loc_mode', 'distance')}'>" + (f"<input type='hidden' name='state' value='{e(','.join(q['states']))}'>" if q.get("states") else "") \
        + ("<input type='hidden' name='also_radius' value='1'>" if q.get("also_radius") else "")      # F-136
    keep += f"<input type='hidden' name='cat' value='{e(','.join(q.get('cats') or []))}'>" if q.get("cats") else ""        # F-56: these were dropped, so a real Save lost them
    keep += "".join(f"<input type='hidden' name='row{i}' value='{e(r)}'>" for i, r in enumerate(q.get("rows") or [], 1) if i <= 4)
    keep += "<input type='hidden' name='broad' value='1'>" if q.get("broad") else ""
    return (f"<details id='save-search'{' open' if cid else ''}><summary>{'Edit saved search' if cid else 'Save this search'}</summary>"
            f"<form method='post' action='/market/{'%s/edit' % e(cid) if cid else 'save'}' class='mk-form'>{tok()}{keep}"
            f"<label>Name this search <input name='title' maxlength='120' value='{v('keywords')}'></label> {pin_html} "
            f"<button name='do' value='save'>{'Save changes' if cid else 'Save this search'}</button></form>"
            "<p class='small mut'>Saved with a search: keywords, origin, radius, location mode and selected states, min and max price, must/nice/exclude terms, category focus, row order, broad mode and condition. Sort, view and closing date are not saved (they apply to this run and are remembered, even after a restart). A saved search needs a max price. "
            "A search never contacts anyone.</p></details>")


def _form(q: dict, cid: str | None, tok, pin_html: str) -> str:
    v = lambda k: e(", ".join(q[k]) if isinstance(q.get(k), list) else q.get(k) if q.get(k) is not None else "")  # noqa: E731
    sel = lambda name, opts, cur: f"<select name='{name}'>" + "".join(  # noqa: E731
        f"<option value='{e(o)}'{' selected' if str(cur) == o else ''}>{e(lbl)}</option>" for o, lbl in opts) + "</select>"
    return ("<div class='card'><form method='get' action='/market' class='mk-form mk-bar' id='mkform' novalidate><input type='hidden' name='go' value='1'>"
            f"<label>Sort {sel('sort', [(s, s.title()) for s in ms.SORTS], q.get('sort', 'closing'))}</label>"
            f"<label>View {sel('view', [('gallery', 'Gallery'), ('list', 'List')], q.get('view', 'gallery'))}</label>"
            f"<label>Category / keywords, any of <input name='any' size='24' value='{v('any')}'></label>"
            f"<label><input type='checkbox' name='broad' value='1'{' checked' if q.get('broad') else ''}> Broad (all categories)</label>"
            f"<label>Keywords, all of <input name='keywords' size='22' value='{v('keywords')}'></label>"
            f"<details><summary>More filters</summary>"
            f"<label>Condition (seller text) <input name='condition' size='10' value='{v('condition')}'></label>"
            f"<label>Must include <input name='required' size='14' value='{v('required')}'></label>"
            f"<label>Nice to include <input name='preferred' size='14' value='{v('preferred')}'></label>"
            f"<label>Exclude <input name='exclude' size='14' value='{v('exclude')}'></label>"
            f"<label>Source {sel('source', [('gsa', 'GSA Auctions')] + [(n.lower(), n + ' (not connected)') for n in ms.NOT_CONNECTED], q.get('source', 'gsa'))}</label>"
            f"<label>Type {sel('kind', [('any', 'Any'), ('auction', 'Auction'), ('fixed', 'Fixed price')], q.get('kind', 'any'))}</label>"
            f"<label>Closing by <input type='date' name='closing_by' value='{v('closing_by')}'></label>"
            f"<p class='small'><b>Gallery rows</b> (top to bottom; leave blank for fewer than 4)</p>"
            + "".join(f"<label>Row {i} {sel(f'row{i}', [('', '(none)')] + [(k, k.title()) for k in ms.ROW_CATS], (q.get('rows') or ms.DEFAULT_ROWS)[i - 1])}</label>" for i in range(1, 5))
            + "</details></form></div>")


def working_capital(verified=None) -> str:
    """The documented working-capital planning setting, labelled apart from verified cash. Neither is a spend authorization."""
    amt = ms.working_capital()
    return ("<details class='card small' id='working-capital'><summary><b>Working capital (planning setting, not cash).</b></summary>"
            f"<span class='lbl'>SETTING</span> ${amt:,.0f} protected principal, from the owner's documented capital model (docs/product/DEAL_SNIFFER_START_HERE.md section 1; "
            "override with MBOS_WORKING_CAPITAL_USD). <br><b>Verified cash:</b> <span class='unk'>UNKNOWN</span> unless a figure is recorded on "
            "<a href='/numbers'>My numbers</a>. A setting is not a balance and nothing here approves a bid, a purchase or a payment.</details>")


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
                edit_id: str | None = None, ran: bool = True, errors: list[str] | None = None, unchecked: list[dict] | None = None, prefs: dict | None = None) -> str:
    tok = lambda: f"<input type='hidden' name='csrf' value='{e(csrf)}'><input type='hidden' name='nonce' value='{secrets.token_hex(8)}'>"  # noqa: E731
    pin_html = "<input type='password' name='pin' placeholder='PIN' autocomplete='off' required>" if pin_set else "<span class='bad'>PIN not set: saving refused</span>"
    err = f"<div class='flash err'><b>Not saved.</b> {e('; '.join(errors))}</div>" if errors else ""
    bad = q.get("errors") or []
    verr = ("<div class='flash err' id='filter-errors' role='alert'><b>Check your filters.</b><ul>" + "".join(f"<li>{e(m)}</li>" for m in bad) + "</ul>No search was run.</div>") if bad and ran else ""
    if not ran:
        body = "<p class='mut'>Fill in the search and press Search. Nothing is fetched from the internet by this page.</p>"
    elif q["source"] != "gsa":
        body = f"<div class='card'><b>{e(q['source'])}: not connected.</b> No results are shown for a source that is not wired; nothing is mocked.</div>"
    elif q["kind"] == "fixed":
        body = "<div class='card'>GSA Auctions lists auctions only; no fixed-price results from a connected source.</div>"
    elif d["status"] != "connected" or bad:
        body = ""
    else:
        hid = ", ".join(f"{n} by {k}" for k, n in hidden.items() if n)
        unchecked = unchecked or []
        scope = (f" within {q['radius']:g} mi of {e(q['base'])}" if q["radius"] is not None else "") if q.get("loc_mode") != "state" else f" in {e(', '.join(q['states']))}" + (f" and within {q['radius']:g} mi of {e(q['base'])}" if q.get("also_radius") and q["radius"] is not None else "")
        zero = ("<p class='mut' id='zero-results'><b>0 results</b> match every filter" + scope + ". Nothing is padded in"
                + (f"; {len(unchecked)} lot(s) could not be checked and are listed below, not counted" if unchecked else "") + ". Loosen a filter or widen the radius.</p>")
        render = (lambda c: gallery_card(c, tok)) if q.get("view") != "list" else (lambda c: render_card(c, tok))
        wrap = (lambda cs: f"<div class='mk-gal'>{''.join(map(render, cs))}</div>") if q.get("view") != "list" else (lambda cs: "".join(map(render, cs)))
        opt = ((f"<details class='mk-sec' id='unchecked-section'><summary><b>Optional: {len(unchecked)} lot(s) that could not be checked (not counted as local or in range). Click to open.</b></summary>"
                "<p class='small mut'>Their location or state was not found or they have no bid yet, so the location scope or price range cannot be tested. They are shown only so nothing is hidden; "
                "verify on the original listing.</p>" + wrap(unchecked) + "</details>") if unchecked else "")
        body = (chips(q) + f"<h2>{len(results)} result{'s' if len(results) != 1 else ''}{scope}</h2>" + "<p class='small mut' style='margin:2px 0'>Cached copy of the GSA list, not a fresh fetch (GSA surplus only). Price = current bid, not a sold price or final cost; all-in cost UNKNOWN."
                + (f" Hidden: {e(hid)}." if hid else "") + "</p>"
                + ((gallery(results, q, tok) if q.get("view") != "list" else "".join(render_card(c, tok) for c in results)) if results else zero) + opt
                + distance_caveat(q, results + unchecked))
    return (CSS + "<h1 class='pagehead'>Michael's Marketplace</h1><div class='mk'>" + _sidebar(saved, csrf, pin_html, tok, q, _save(q, edit_id, tok, pin_html))
            + f"<section class='mk-main' id='results-top'>{err}{verr}{_form(q, edit_id, tok, pin_html)}{render_status(d)}{body}{prefs_panel(prefs, tok) if prefs else ''}{working_capital()}{gsa_explainer()}</section></div>")


def save_form(f: dict) -> dict:
    """Marketplace form -> the Wanted campaign form fields (exclude terms ride in nice_to_have as `exclude:word`)."""
    q = ms.parse_query({k: ([c for c in v.split(",") if c.strip()] if k in ("cat", "state") else [v]) for k, v in f.items()})   # F-56: `cat` is posted comma-joined (a form keeps one value per name)
    nice = list(q["preferred"]) + [ms.EXCLUDE_PREFIX + t for t in q["exclude"]]
    nice += ([f"min:{q['min_price']:g}"] if q["min_price"] is not None else []) + ([f"cat:{'>'.join(q['cats'])}"] if q["cats"] else []) \
        + ([f"rows:{'>'.join(q['rows'])}"] if q["rows"] != list(ms.DEFAULT_ROWS) else []) + ([f"any:{'>'.join(t.replace('>', ' ') for t in q['any'])}"] if q["any"] else []) + (["broad:1"] if q["broad"] else []) + ([f"locmode:state"] if q["loc_mode"] == "state" else []) + ([f"states:{'>'.join(q['states'])}"] if q["states"] else []) + (["alsorad:1"] if q["also_radius"] else []) + ([f"cond:{q['condition']}"] if q["condition"] else [])
    return {**{k: f[k] for k in ("csrf", "pin", "nonce") if k in f}, "title": (f.get("title") or q["keywords"]).strip() or "Marketplace search",
            "category": CATEGORY, "keywords": q["keywords"].replace(" ", ", "), "max_price_usd": "" if q["max_price"] is None else str(q["max_price"]),
            "radius_miles": "" if q["radius"] is None else str(q["radius"]), "origin": q["base"],
            "must_have": ", ".join(q["required"]), "nice_to_have": ", ".join(nice), "level": "RECOMMEND"}


def go_url(q: dict) -> str:
    return "/market?go=1&" + "&".join(f"{k}={quote(str(v))}" for k, v in q.items() if v not in (None, "", []))
