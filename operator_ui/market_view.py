"""F-47: Michael's Marketplace page: sidebar, search form, source status line, result cards. Saved searches are Wanted campaigns
with category `marketplace` (written through App.wanted_change, so CSRF + PIN + receipts are unchanged). All text escaped."""

from __future__ import annotations

import html
import math
import secrets
from urllib.parse import quote, urlsplit

from . import landing_fix
from . import market_search as ms
from .deal_ui import classify_url
from .live_demo import link_html
from . import precedent_view as pv
from . import market_source_view as msv
from . import market_browse as mb
from . import market_detail as md
from . import market_source_panel as msp

CATEGORY = "marketplace"
SLIDER_MAX = 500          # F-144: normal slider scale (miles); control usability, not a travel limit
e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

CSS = """<style>main{max-width:1900px}.banner{padding:3px 16px;font-size:13px}header{padding:4px 16px;flex-wrap:nowrap}header b{display:none}header nav{display:flex;gap:2px 12px;flex-wrap:wrap}header nav a{margin:0;white-space:nowrap}main{padding:8px 16px}.pagehead{margin:4px 0 8px;font-size:20px}.mk-row>h2{margin:8px 0 4px}.mk-gal>p{grid-column:1/-1;margin:2px 0}.mk{display:flex;gap:18px;align-items:flex-start}.mk-side{flex:0 0 210px}
.mk-main{flex:1;min-width:0}.mk-side .card{padding:10px 12px}.mk-side a{display:block;padding:4px 0}.mk-demo{border-top:2px dashed var(--line);margin-top:12px;padding-top:8px}
.mk-form label{display:inline-block;margin:0 10px 8px 0}.mk-res{display:flex;gap:12px}.mk-res img{width:120px;height:90px;object-fit:cover;border-radius:6px}
.mk-tag{font-size:12px;border:1px solid var(--line);border-radius:8px;padding:0 6px;margin-right:4px}
.mk-form button,.mk-side button{background:var(--acc);color:var(--bg);width:auto;opacity:1}.mk-form button:hover{filter:brightness(1.1)}
.mk-form button:focus-visible,.mk-form input:focus-visible,.mk-side a:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
.mk-form button.mk-add,.mk-form button.mk-go{font-size:16px;padding:10px 28px}.mk-chips .chip{background:var(--card);font-size:12px;padding:1px 8px}.mk-chips{margin:4px 0}
.mk-range input[type=range]{width:46%;display:inline-block;margin:0;padding:0}.mk-range input[type=number]{width:110px;display:inline-block}
#mkcats{display:flex;flex-wrap:wrap;gap:6px}#mkcats label.mk-cat{display:flex;align-items:center;gap:8px;min-height:44px;padding:6px 12px;border:1px solid var(--line);border-radius:8px;font-size:16px;margin:0}#mkcats input[type=checkbox]{width:24px;height:24px;margin:0}.mk-sec2{font-size:13px}.mk-side .card button.mk-go{display:block;width:100%;margin-top:6px}.mk-sec{border-top:2px dashed var(--line);margin-top:16px}
.mk-gal{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(230px,100%),1fr));gap:10px}.mk-g{border:1px solid var(--line);border-radius:8px;padding:8px;background:var(--card);min-width:0}
.mk-g .ph{height:110px;display:flex;align-items:center;justify-content:center;border:1px dashed var(--line);border-radius:6px;text-align:center;overflow:hidden}.mk-g img{width:100%;height:110px;object-fit:cover;border-radius:6px}
.mk-g .pr{font-size:18px;font-weight:700;margin:4px 0 0}.mk-g .ti{font-size:14px;margin:2px 0;overflow-wrap:anywhere}.mk-g button,.mk-pref button{font-size:12px;padding:2px 6px;margin:1px;width:auto;background:var(--acc);color:var(--bg);opacity:1}.mk-acts{display:flex;justify-content:space-between;align-items:flex-end;gap:4px}.mk-xf{margin:0}.mk-g button.mk-x,.mk-x{background:transparent;color:var(--ink);border:1px solid var(--line);font-size:14px;line-height:1;padding:3px 7px}.mk-xt{font-size:11px}.mk-pref button:focus-visible,.mk-x:focus-visible{outline:3px solid var(--ink);outline-offset:2px}
.mk-side .mk-range input[type=range],.mk-side .mk-range input[type=number]{width:100%}.mk-side label{display:block}.mk-side .mk-range>label{display:inline-block;width:47%;margin:0 1% 4px 0}.mk-side .mk-range .small{margin:4px 0}.mk-side .mk-range div label{margin:0}.mk-side input[type=checkbox]{width:auto}
.mk-bar{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:flex-end}.mk-bar label{display:block;margin:0;font-size:13px}.mk-bar input,.mk-bar select{width:auto;padding:4px 6px;margin:0;max-width:100%}.mk-bar details{flex:1 1 100%}.mk-bar button.mk-go{padding:6px 22px}.mk-main>.card{padding:8px 12px}.mk-main h2{margin:6px 0}.mk-side input[type=number],.mk-side input[type=text],.mk-side input:not([type]){padding:4px 6px}.mk-jump{display:none}.mk-form details,#save-search{margin:4px 0}
@media(max-width:700px){header nav{flex-wrap:nowrap;overflow-x:auto;padding-bottom:2px}.mk{flex-direction:column}.mk-main{order:2}.mk-side{order:1}.mk-jump{display:block}.mk-g .ph,.mk-g img{height:90px}.mk-side{position:static;flex:none;width:100%}.mk-res{flex-direction:column}.mk-form input,.mk-form select{max-width:100%}}</style>"""


def _photo(url, listing=None) -> str:
    if landing_fix.is_gsa_image(url):
        return ""
    try:
        host = urlsplit(url or "").hostname or ""
    except ValueError:
        host = ""
    if url and classify_url(url, hosts=[host])[0] == "live":
        return f"<img src='{e(url)}' alt='Original listing photo' loading='lazy' referrerpolicy='no-referrer'>"
    return ""


def vlink(c: dict) -> str:
    return f"<a class='mk-detail' href='{html.escape(md.href(c))}'>View details</a>"       # F-160


def _money(v) -> str:
    return "UNKNOWN (no bids yet)" if v is None else f"${v:,.2f}"


def save_button(c: dict, tok) -> str:
    action, label = ("unsave", "Saved ✓") if c.get("saved") else ("save", "Save")
    hid = f"<input type='hidden' name='lot' value='{e(c['id'])}'><input type='hidden' name='title' value='{e(c['title'])}'>"
    return f"<form method='post' action='/market/pref' class='mk-save'>{tok()}{hid}<button name='act' value='{action}' type='submit'>{label}</button></form>"


def pref_buttons(c: dict, tok, include_save: bool = True) -> str:
    """Learning controls on the left (each labelled with its effect), the distinct X / Hide this listing control bottom-right (no learning)."""
    b = lambda a, lbl, tip: f"<button name='act' value='{a}' title='{tip}'>{lbl}</button>"  # noqa: E731
    hid = f"<input type='hidden' name='lot' value='{e(c['id'])}'><input type='hidden' name='title' value='{e(c['title'])}'>"
    save = b('unsave', 'Unsave', 'Remove from saved') if c.get('saved') else b('save', 'Save', 'Keep this listing')
    return (f"<div class='mk-acts'><form method='post' action='/market/pref' class='mk-pref'>{tok()}{hid}{save if include_save else ''}"
            f"{b('dismiss', 'Not interested', 'Hides this listing and counts its title words as less like this')}{b('more', 'More like this', 'Boosts its title words in ranking')}{b('less', 'Less like this', 'Lowers its title words in ranking')}</form>"
            f"<form method='post' action='/market/pref' class='mk-xf'>{tok()}{hid}<button name='act' value='hide' class='mk-x' type='submit' aria-label='Hide this listing' "
            "title='Hide this listing (this one only; nothing is learned; restore it from the hidden list)'>&#10005;<span class='mk-xt'> Hide</span></button></form></div>"
            + __import__('operator_ui.market_bids', fromlist=['x']).button(c, tok) + (f"<p class='small mut' data-why>{e(c['why'])}</p>" if c.get("why") else ""))


def hidden_panel(d: dict, tok) -> str:
    """Hidden listings, each restorable on its own. Restoring changes nothing else (saves, likes, filters)."""
    h = d.get("hidden") or {}
    if not h:
        return "<details class='card small' id='hidden-list'><summary><b>Hidden listings: 0</b></summary>Nothing hidden. Use the X on a card to hide one listing.</details>"
    rows = "".join(f"<li data-hidden='{e(i)}'>{e(t or 'title not recorded')} <span class='mut'>({e(i)})</span> <form method='post' action='/market/pref' style='display:inline' class='mk-pref'>{tok()}"
                   f"<input type='hidden' name='lot' value='{e(i)}'><button name='act' value='restore' aria-label='Undo hide: {e(t or i)}'>Undo hide</button></form></li>" for i, t in sorted(h.items()))
    return (f"<details class='card small' id='hidden-list'><summary><b>Hidden listings: {len(h)}</b> (hidden by you; kept across restarts)</summary><ul>{rows}</ul>"
            "<span class='mut'>Undo restores only that listing, and only if it still passes your filters. Saves, likes and filters are untouched.</span></details>")


def gallery_labels(c: dict) -> str:
    """F-137: compact reserve + current-vs-estimated-next-bid line for the gallery card (cached values, live minimum unverified)."""
    L = c.get("labels") or ms.auction_labels({})
    nb = f"~${L['est_next_bid']:,.0f}" if L["est_next_bid"] is not None else "UNKNOWN"
    cur = f"${L['current_bid']:,.0f}" if L["current_bid"] is not None else "none"
    res = {"Yes": "Yes (amount undisclosed)", "No": "No", "Unknown": "UNKNOWN"}[L["reserve"]]
    return f"Bid {e(cur)} → est. next {e(nb)} (cached, unverified) · Reserve: {e(res)}"


def gallery_card(c: dict, tok) -> str:
    """F-52 (B): dense card: real photo when supplied, otherwise compact text; price, title, town and closing."""
    if c.get("event"):
        return msv.event_gallery(c, tok, pref_buttons, lambda u: f"{vlink(c)} · {link_html(u)}")
    img = _photo(c["image"], c["url"])
    ph = img if img.startswith("<img") else ""
    price = f"<div class='pr'>No bids yet</div><div class='small mut' data-opening>{e((c.get('labels') or ms.auction_labels({}))['opening_text'])}</div>" if c["bid"] is None else f"<div class='pr'>${c['bid']:,.0f}</div><div class='small mut'>current bid</div>"
    town = e(c["city"] or "town UNKNOWN") + (f" · {round(c['distance'], 1):g} mi" if c["distance"] is not None else " · distance UNKNOWN")
    ti = c["title"] if len(c["title"]) <= 60 else c["title"][:59] + "…"
    flag = " <span class='badge'>SAVED</span>" if c.get("saved") else ""
    return (f"<div class='mk-g' data-lot='{e(c['id'])}'>{ph}{price}<div class='ti'><b>{e(ti)}</b>{flag}</div><div class='small'>{town}</div>{msv.card_note(c)}"
            f"<div class='small mut'>closes {e(c['closes'] or 'UNKNOWN')}{c.get('closing_badge', '')} · posted age: not given · auction, all-in cost unknown</div>"
            f"<div class='small mut gal-lbl'>{gallery_labels(c)}</div><div class='small'>{vlink(c)} · {link_html(c['url'])} · <span class='lbl'>WATCH</span></div>{pref_buttons(c, tok)}</div>")


def gallery(cards: list[dict], q: dict, tok, prec: dict | None = None) -> str:
    out = []
    for name, row in ms.gallery_rows(cards, q):
        body = "".join(pv.inject(gallery_card(c, tok), (prec or {}).get(c["id"], "")) for c in row) or "<p class='mut small'>No matching known inventory in this category (known = the cached GSA list only).</p>"
        out.append(f"<section class='mk-row' data-row='{e(name)}'><h2 style='text-transform:capitalize'>{e(name)} <span class='small mut'>({len(row)})</span></h2><div class='mk-gal'>{body}</div></section>")
    return "".join(out)


def suggest_strip(sug: str, n: int = 0) -> str:
    """F-163: the Suggestions panel as a one-line collapsed strip above the grid ('Suggestions (N)' = engine-ranked rows)."""
    if not sug:
        return ""
    return f"<details class='mk-strip' id='suggestions-strip'><summary><b>Suggestions ({n})</b> <span class='small mut'>ranked by the engine, display only</span></summary>{sug}</details>"


def prefs_panel(d: dict, tok) -> str:
    f = lambda a, lbl: f"<form method='post' action='/market/pref' style='display:inline' class='mk-pref'>{tok()}<button name='act' value='{a}'>{lbl}</button></form>"  # noqa: E731
    state = "ON" if d["enabled"] else "OFF"
    return (f"<details class='card small' id='prefs'><summary><b>Suggestions: {state}</b> (how your clicks reorder results)</summary>{e(__import__('operator_ui.market_prefs', fromlist=['x']).summary(d))}<br>"
            "Your clicks only reorder or hide what already passed your filters; they never widen a price, radius or exclusion, and they say nothing about profit.<br>"
            f"{f('disable', 'Turn off') if d['enabled'] else f('enable', 'Turn on')} {f('reset', 'Reset')}</details>")


def render_card(c: dict, tok=None) -> str:
    if c.get("event"):
        return msv.event_card(c, tok, pref_buttons, lambda u: f"{vlink(c)} · {link_html(u)}")
    verdict, why = ms.decision(c)
    tags = "".join(f"<span class='mk-tag'>{e(k)}: {e(t)} ({e(tag)})</span>" for k in ("required", "preferred") for t, tag in (c.get("tags") or {}).get(k, []))
    where = e(c["city"] or "UNKNOWN") + (f" · {round(c['distance'], 1):g} mi from your base" if c["distance"] is not None else " · distance UNKNOWN (place not in our small local gazetteer; see the note above)")
    stale = " <b class='bad'>STALE: bid may have moved</b>" if c["stale"] else ""
    L = c.get("labels") or ms.auction_labels({})
    auction_line = (f"<p class='small' id='auction-labels'>Next bid: {e(L['next_min_text'])} · Reserve: {e(L['reserve_text'])} · source GSA Auctions cache</p>" if not c.get("fixture")
                    else f"<p class='small'>{msv.card_note(c)}Reserve and next bid: UNKNOWN (alert e-mail text only).</p>")
    return (f"<div class='card mk-res'>{_photo(c['image'], c['url'])}<div style='min-width:0'><h3 style='margin:0 0 4px'>{e(c['title'])} "
            f"<span class='badge'>{verdict}</span> <span class='lbl'>RESEARCH NEEDED</span></h3>"
            f"<p class='small'>{e(c['description']) or '<span class=mut>No description from the seller</span>'}</p>"
            f"<p><span class='lbl'>AUCTION</span> Current bid <b>{_money(c['bid'])}</b> (a bid, not a sold price or final cost) · Asking price: none (auction) · closes {e(c['closes'] or 'UNKNOWN')}{c.get('closing_badge', '')} · {where} · "
            f"condition (seller says): {e(c['condition'] or 'UNKNOWN')}</p>"
            f"{auction_line}"
            + (f"<p class='small' id='opening-min'>No bids yet. {e(L['opening_text'])}" + ("" if L["opening_min"] is not None else f" {link_html(c['url'])}") + "</p>" if c["bid"] is None else "")
            + "<p class='small mut' id='valuation-note'>Valuation: a gross scrap/component estimate is not a net yard pickup offer. Pickup, deductions, towing, disposal, fees, title, condition and recoverable weight: UNKNOWN.</p>"
            f"<p class='small'>Price math: bid {_money(c['bid'])} + buyer premium UNKNOWN + transport UNKNOWN + repair UNKNOWN "
            f"= all-in cost UNKNOWN (never the final cost) · sold comp: none on file</p>{('<p>' + tags + '</p>') if tags else ''}{('<p class=small><b>Not checked against your filters:</b> ' + e('; '.join(c['unchecked'])) + '</p>') if c.get('unchecked') else ''}"
            f"<p>{vlink(c)} · Original listing: {link_html(c['url'])}</p>{pref_buttons(c, tok) if tok else ''}"
            f"<p class='small mut'>{e(why)}<br>Source {e(c['source'])} · fetched {e(c['fetched_at'])} · {e(c['kind'])}{stale}</p></div></div>")


def distance_caveat(q: dict, results: list[dict]) -> str:
    """F-50: distances come from approximate town centroids in small local gazetteers; say what was and was not located."""
    if not results:
        return ""
    base = (q.get("base") or "").strip()
    towns = lambda sel: sorted({c["city"] or "no town given" for c in results if sel(c)})  # noqa: E731
    got, miss = towns(lambda c: c["distance"] is not None), towns(lambda c: c["distance"] is None)
    origin = f"Your base '{e(base)}' is located." if ms._origin(base) else f"Your base '{e(base)}' is NOT located, so no distance can be shown."
    lots = f"Lot towns located: {e(', '.join(got)) or 'none'}. Lot towns NOT located (distance UNKNOWN, not 'far away'): {e(', '.join(miss)) or 'none'}."
    return ("<details class='card small' id='distance-caveat'><summary><b>About distances</b> (approximate; unknown is not far)</summary>Place coordinates are approximate town centroids from the "
            "Census 2023 ZIP and place gazetteer (Arkansas and neighbouring states). Distances are rough straight-line miles, good to a few miles at best. "
            "A town missing from the gazetteer shows 'distance UNKNOWN' because we cannot place it, not because it is far; out-of-state lots are often in that group. "
            f"{origin} {lots} No online lookup is made.</details>")


def render_status(d: dict, banner_inline: bool = True) -> str:
    if d.get("name") or d.get("coverage"):             # F-145: a non-GSA source page (govdeals | publicsurplus | all): per-source coverage
        return msv.coverage(d, banner_inline)
    if d["status"] != "connected":
        return f"<div class='flash err' id='source-status'><b>GSA Auctions: offline.</b> {e(d['message'])}</div>"
    warn = (f" <b class='bad'>STALE ({d['age_h']:g} h old): current bids may have changed.</b>" if d["stale"] else "")
    return (f"<p class='small' id='source-status' style='margin:6px 0'><b>GSA Auctions: connected (cached file)</b> · last fetched {e(str(d['as_of'])[:16].replace('T', ' '))} UTC "
            f"({d['age_h']:g} h ago) · {d['in_scope']} lots in nearby states of {d['in_file']} in the file{warn} · "
            f"not connected: {e(', '.join(ms.NOT_CONNECTED))}</p>")


def chip_url(q: dict, drop: str | None = None) -> str:
    """F-136: a GET link that re-runs the current filters without one state (the chip's remove button). No script, no write."""
    j = lambda k: ", ".join(q[k]) if isinstance(q.get(k), list) else q.get(k)  # noqa: E731
    pairs = [(k, j(k)) for k in ("keywords", "base", "radius", "min_price", "max_price", "any", "condition", "required", "preferred", "exclude", "source", "kind", "closing_by", "sort", "view", "ltype", "quick", "cat_find")]
    pairs += [("broad", "1")] * bool(q.get("broad")) + [("cat", c) for c in (['all'] if q.get('cat_all') else [] if q.get('cat_default') else q.get('cats') or [])] + [(f"row{i}", r) for i, r in enumerate(q.get("rows") or [], 1) if i <= 4]
    pairs += [("loc_mode", q.get("loc_mode", "distance"))] + [("also_radius", "1")] * bool(q.get("also_radius")) + [("state", s) for s in q.get("states") or [] if s != drop]
    return "/market?go=1&amp;" + "&amp;".join(f"{k}={quote(str(v))}" for k, v in pairs if v not in (None, ""))


def scope_text(q: dict) -> str:
    """F-136: the location scope actually applied to this run, in words (the mode is never implicit)."""
    if q.get("loc_mode") == "state":
        st = ", ".join(q.get("states") or []) or "none selected"
        return f"By State: {st}" + (f" AND within {q['radius']:g} miles" if q.get("also_radius") and q["radius"] is not None else "; the radius is NOT applied")
    return f"By Distance: " + (f"within {q['radius']:g} miles (known distances only)" if q["radius"] is not None else "no radius") + "; states are NOT applied"


def location_panel(q: dict, counts: dict | None = None) -> str:
    """F-136: compact Location panel: By State / By Distance modes, searchable state list, multi-select checkboxes, removable chips (all inside the search form, no script)."""
    v = lambda k: e(q.get(k) if q.get(k) is not None else "")  # noqa: E731
    by_state, sel, find = q.get("loc_mode") == "state", q.get("states") or [], (q.get("state_find") or "").strip().lower()
    mode = lambda val, lbl: f"<label><input form='mkform' type='radio' name='loc_mode' value='{val}'{' checked' if (val == 'state') == by_state else ''}> {lbl}</label> "  # noqa: E731
    shown = [(c, n) for c, n in ms.US_STATES.items() if c in sel or not find or find in n.lower() or find == c.lower()]
    cnt = lambda c: "" if counts is None else f" <span class='mk-n'>({counts.get(c, 0)})</span>"  # noqa: E731
    boxes = "".join(f"<label class='st' data-count='{'' if counts is None else counts.get(c, 0)}'><input form='mkform' type='checkbox' name='state' value='{c}'{' checked' if c in sel else ''}> {c} {e(n)}{cnt(c)}</label>" for c, n in shown) \
        or "<span class='small mut'>No state matches that search.</span>"
    hide = "".join(f"<input form='mkform' type='hidden' name='state' value='{c}'>" for c in sel if c not in {c2 for c2, _ in shown})
    chip = "".join(f"<span class='chip'>{c} <a href='{chip_url(q, c)}' aria-label='Remove {c}' title='Remove {c}'>×</a></span>" for c in sel) or "<span class='small mut'>No states selected</span>"
    return ("<fieldset id='location-panel' style='border:1px solid var(--line);border-radius:8px;margin:0 0 8px'><legend>Location</legend>"
            f"<div role='radiogroup' aria-label='Location mode'>{mode('distance', 'By Distance')}{mode('state', 'By State')}</div>"
            f"<label>ZIP or city <input form='mkform' name='base' size='12' value='{v('base')}'></label>"
            f"{_radius(q)}"
            f"<details id='state-picker' open><summary>States <span class='small'>({len(sel)} selected)</span></summary>"
            f"<label>Find a state <input form='mkform' name='state_find' size='10' value='{e(q.get('state_find') or '')}'></label>"
            f"<div class='st-list' style='max-height:130px;overflow:auto'>{boxes}</div>{hide}"
            f"<label><input form='mkform' type='checkbox' name='also_radius' value='1'{' checked' if q.get('also_radius') else ''}> In By State mode, also keep the radius</label></details>"
            f"<div id='state-chips' aria-label='Selected states'>{chip}</div>"
            f"<p class='small mut' id='location-scope'>{e(scope_text(q))}. A lot with no known state or distance is never counted as local; it is listed as not checked.</p></fieldset>")


def _radius(q: dict) -> str:
    """F-159: a radius dropdown (10 / 25 / 50 / 100 / 250 miles / Any). A saved or typed value that is not a preset is kept as an extra option, never clamped."""
    r = q.get("radius")
    cur = "" if r is None else f"{r:g}"
    opts = [(x, "Any" if x == "" else f"{x} miles") for x in mb.RADII] + ([(cur, f"{cur} miles")] if cur not in mb.RADII else [])
    return ("<div id='radius-ctl'><label>Radius <select form='mkform' id='radius' name='radius'>"
            + "".join(f"<option value='{e(v)}'{' selected' if v == cur else ''}>{e(lbl)}</option>" for v, lbl in opts) + "</select></label></div>")


def _sel(name: str, opts, cur) -> str:
    return f"<select form='mkform' name='{name}'>" + "".join(f"<option value='{e(o)}'{' selected' if str(cur) == o else ''}>{e(lbl)}</option>" for o, lbl in opts) + "</select>"


def _more_filters(q: dict) -> str:
    """F-142/F-159: the advanced filters (the search box, source, type and condition now have their own controls)."""
    v = lambda k: e(", ".join(q[k]) if isinstance(q.get(k), list) else q.get(k) if q.get(k) is not None else "")  # noqa: E731
    return (f"<details id='more-filters'><summary><b>More filters</b></summary>"
            f"<label>Category / keywords, any of <input form='mkform' name='any' size='20' value='{v('any')}'></label>"
            f"<label><input type='checkbox' form='mkform' name='broad' value='1'{' checked' if q.get('broad') else ''}> Broad (all categories)</label>"
            f"<label>Must include <input form='mkform' name='required' size='14' value='{v('required')}'></label>"
            f"<label>Nice to include <input form='mkform' name='preferred' size='14' value='{v('preferred')}'></label>"
            f"<label>Exclude <input form='mkform' name='exclude' size='14' value='{v('exclude')}'></label>"
            f"<label>Closing by <input type='date' form='mkform' name='closing_by' value='{v('closing_by')}'></label>"
            "</details>")


def _side_filters(q: dict, fc: dict, now) -> str:
    """F-159: the GSA-style filter sections (Category, Source, Location, Price, Listing type, Condition); every input belongs to the top-bar search form (form='mkform')."""
    return ("<div class='card' id='mkfilters'><label class='mk-fbtn mk-fm' for='mkdrawer'>Close filters</label><b>Filters</b>"
            f"{mb.category_section(q, fc)}{mb.source_section(q, fc, now)}"
            f"<details open class='mk-sect' id='sec-location'><summary><b>Location</b></summary>{location_panel(q, fc['states'])}</details>"
            f"<details open class='mk-sect' id='sec-price'><summary><b>Price range</b></summary>{_slider(q, 'mkform')}</details>"
            f"{mb.ltype_section(q, fc)}{mb.condition_section(q, fc)}{_more_filters(q)}"
            "<button class='mk-apply' type='submit' form='mkform'>Apply filters</button></div>")


def _sidebar(saved: list[dict], csrf: str, pin_html: str, tok, q: dict, save: str = "", bids: str = "", fc: dict | None = None, now=None, folded: bool = False, prefs: dict | None = None) -> str:
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
    mine = ("<details class='mk-sect' id='my-marketplace'><summary><b>My Marketplace</b></summary>"
            f"<a class='mk-sec2' href='{mb.href(q, quick='saved', page=1)}'>Saved listings</a><a class='mk-sec2' href='/market?new=1'>New search</a>"
            f"{save}<details><summary>Saved searches ({len(rows)})</summary>{saved_html}</details>{bids}{hidden_panel(prefs, tok) if prefs else ''}</details>")
    admin = ("<details class='mk-sect' id='admin-menu'><summary><b>Admin</b></summary><a href='/queue'>Queue</a><a href='/mission'>Weekly mission</a>"
             "<a href='/numbers'>My numbers</a><a href='/wanted'>Wanted</a><a href='/intake'>Intake</a><a href='/assets'>My assets</a>"
             "<a href='/resale'>Resale</a><a href='/sources'>Source health</a></details>")
    return f"<aside class='mk-side{' folded' if folded else ''}' id='filters-side'>{_side_filters(q, fc, now) if fc else ''}{mine}{admin}</aside>"


def _slider(q: dict, form: str = "") -> str:
    """F-143: explicit numeric Min/Max price only (blank = unlimited). The range sliders and their hidden previous-value wiring are gone."""
    g = lambda k: "" if q.get(k) is None else f"{q[k]:g}"  # noqa: E731
    return ("<fieldset class='mk-range' style='border:1px solid var(--line);border-radius:8px;margin:0 0 8px'><legend>Price range (current bid)</legend>"
            f"<label>Min $ <input form='{form}' type='number' id='min_price' name='min_price' min='0' step='any' inputmode='decimal' value='{e(g('min_price'))}'></label> "
            f"<label>Max $ <input form='{form}' type='number' id='max_price' name='max_price' min='0' step='any' inputmode='decimal' value='{e(g('max_price'))}'></label>"
            "<p class='small mut'>Type a number. Blank = no limit. This is not a budget or spending authority.</p></fieldset>")


def chips(q: dict) -> str:
    """The filters actually applied to this run, as plain chips (also shown when nothing is limited)."""
    c = []
    c.append(f"Origin: {q['base']}" + (" (ZIP 72032)" if q["base"].strip().lower() in ("", "conway", "conway ar", "conway, ar") else ""))
    c.append("Location: " + scope_text(q)) if q.get("loc_mode") == "state" else c.append((f"Radius: {q['radius']:g} mi (known distances only)" if q["radius"] is not None else "Radius: none") + "; Location mode: By Distance (states not applied)")
    c.append("Mode: BROAD inventory (all categories)" if q.get("broad") else "Categories: " + ("all" if q.get("cat_all") else "default (all except Land/Real Estate)" if q.get("cat_default") else ", ".join(ms.CAT_LABELS.get(k, k) for k in q["cats"])) + (f"; keyword focus: {', '.join(q['any'])}" if q.get("any") and q["any"] != ms._terms(ms.DEFAULT_ANY) else ""))
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
    keep += f"<input type='hidden' name='cat' value='{'all' if q.get('cat_all') else e(','.join(q.get('cats') or []))}'>" if q.get("cats") and not q.get("cat_default") else ""        # F-56: these were dropped, so a real Save lost them
    keep += "".join(f"<input type='hidden' name='row{i}' value='{e(r)}'>" for i, r in enumerate(q.get("rows") or [], 1) if i <= 4)
    keep += "<input type='hidden' name='broad' value='1'>" if q.get("broad") else ""
    return (f"<details id='save-search'{' open' if cid else ''}><summary>{'Edit saved search' if cid else 'Save this search'}</summary>"
            f"<form method='post' action='/market/{'%s/edit' % e(cid) if cid else 'save'}' class='mk-form'>{tok()}{keep}"
            f"<label>Name this search <input name='title' maxlength='120' value='{v('keywords')}'></label> {pin_html} "
            f"<button name='do' value='save'>{'Save changes' if cid else 'Save this search'}</button></form>"
            "<p class='small mut'>Saved with a search: keywords, origin, radius, location mode and selected states, min and max price, must/nice/exclude terms, category focus, row order, broad mode and condition. Sort, view and closing date are not saved (they apply to this run and are remembered, even after a restart). A saved search needs a max price. "
            "A search never contacts anyone.</p></details>")


def _form(q: dict, cid: str | None, tok, pin_html: str) -> str:
    sel = lambda name, opts, cur: f"<select name='{name}'>" + "".join(  # noqa: E731
        f"<option value='{e(o)}'{' selected' if str(cur) == o else ''}>{e(lbl)}</option>" for o, lbl in opts) + "</select>"
    return ("<div class='card'><form method='get' action='/market' class='mk-form mk-bar' id='mkform' novalidate><input type='hidden' name='go' value='1'>"
            f"<label>Sort {sel('sort', [(s, s.title()) for s in ms.SORTS], q.get('sort', 'closing'))}</label>"
            f"<label>View {sel('view', [('gallery', 'Gallery'), ('list', 'List')], q.get('view', 'gallery'))}</label>"
            "</form></div>")


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
                edit_id: str | None = None, ran: bool = True, errors: list[str] | None = None, unchecked: list[dict] | None = None, prefs: dict | None = None, finds: str = "", bids: str = "", suggest: str = "", browse: dict | None = None) -> str:
    tok = lambda: f"<input type='hidden' name='csrf' value='{e(csrf)}'><input type='hidden' name='nonce' value='{secrets.token_hex(8)}'>"  # noqa: E731
    pin_html = "<input type='password' name='pin' placeholder='PIN' autocomplete='off' required>" if pin_set else "<span class='bad'>PIN not set: saving refused</span>"
    err = f"<div class='flash err'><b>Not saved.</b> {e('; '.join(errors))}</div>" if errors else ""
    bad = q.get("errors") or []
    verr = ("<div class='flash err' id='filter-errors' role='alert'><b>Check your filters.</b><ul>" + "".join(f"<li>{e(m)}</li>" for m in bad) + "</ul>No search was run.</div>") if bad and ran else ""
    if not ran:
        body = "<p class='mut'>Fill in the search and press Search. Nothing is fetched from the internet by this page.</p>"
    elif msv.gate(q, d):
        body = msv.gate(q, d)
    elif q["kind"] == "fixed":
        body = "<div class='card'>GSA Auctions lists auctions only; no fixed-price results from a connected source.</div>"
    elif d["status"] not in ("connected", "fixture") or bad:
        body = ""
    else:
        unchecked = unchecked or []
        display_rows = results + unchecked
        zero = "<p class='mut' id='zero-results'><b>0 listings</b> match these filters. Loosen a filter or widen the radius.</p>"
        browse = browse or {}
        now = browse.get("now") or __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
        page_rows, page, pages = mb.paginate(display_rows, q.get("page", 1))
        prec, _ = pv.for_cards(page_rows)
        render = (lambda c: mb.card(c, tok, now, pref_buttons)) if q.get("view") != "list" else (lambda c: render_card(c, tok))
        n_hid = q.get("hidden_checked", 0)
        if n_hid and not display_rows:
            zero = f"<p class='mut' id='zero-results'><b>0 listings left.</b> {n_hid} matching listing(s) are hidden. Open My Marketplace in the filters panel to restore them.</p>"
        unknown = f" <span class='small mut'>({len(unchecked)} with distance or price not verified)</span>" if unchecked else ""
        body = (f"<h2>{len(display_rows)} listing{'s' if len(display_rows) != 1 else ''}{unknown}</h2>"
                + ((f"<div class='mk-grid' id='result-grid'>{''.join(pv.inject(render(c), prec.get(c['id'], '')) for c in page_rows)}</div>" if q.get("view") != "list" else "".join(pv.inject(render_card(c, tok), prec.get(c["id"], "")) for c in page_rows)) if display_rows else zero)
                + mb.pager(q, page, pages, len(display_rows)))
    fc = browse.get("fc") if browse else None
    offline = d["status"] not in ("connected", "fixture") and not d.get("name") and not d.get("coverage")
    banner = f"<div class='flash err' id='fixture-banner' role='note' title='{e(msv.FIXTURE_BANNER)}'><b>{e(msv.FIXTURE_BANNER)}</b></div>" if fc and d.get("fixture") else ""
    status = render_status(d, not fc) if not fc or offline else ""          # F-163: on the browse page the per-source status lives in the collapsed Sources panel
    folded = mb.collapsed()
    back = browse.get("back", "/market") if browse else "/market"
    total = len(results) + len(unchecked or [])
    bar = mb.top_bar(q, total if ran and not bad and d["status"] in ("connected", "fixture") else 0, q.get("sort", "closing"), q.get("view", "gallery"), tok, mb.active_filters(q), back, (fc or {}).get("quick"), folded) if fc else _form(q, edit_id, tok, pin_html)
    return (CSS + mb.CSS + "<script src='/static/market_radius.js' defer></script><h1 class='pagehead'>DealSniffer Marketplace</h1><input type='checkbox' id='mkdrawer' class='mk-drawer-t' aria-label='Show filters'><div class='mk'>"
            + _sidebar(saved, csrf, pin_html, tok, q, _save(q, edit_id, tok, pin_html), bids, fc, browse.get("now") if browse else None, folded, prefs)
            + f"<section class='mk-main' id='results-top'>{bar}{err}{verr}{banner}{status}{body}</section></div>")


def save_form(f: dict) -> dict:
    """Marketplace form -> the Wanted campaign form fields (exclude terms ride in nice_to_have as `exclude:word`)."""
    q = ms.parse_query({k: ([c for c in v.split(",") if c.strip()] if k in ("cat", "state") else [v]) for k, v in f.items()})   # F-56: `cat` is posted comma-joined (a form keeps one value per name)
    nice = list(q["preferred"]) + [ms.EXCLUDE_PREFIX + t for t in q["exclude"]]
    nice += ([f"min:{q['min_price']:g}"] if q["min_price"] is not None else []) + ([f"cat:{'all' if q['cat_all'] else '>'.join(q['cats'])}"] if q["cats"] and not q["cat_default"] else []) \
        + ([f"rows:{'>'.join(q['rows'])}"] if q["rows"] != list(ms.DEFAULT_ROWS) else []) + ([f"any:{'>'.join(t.replace('>', ' ') for t in q['any'])}"] if q["any"] else []) + (["broad:1"] if q["broad"] else []) + ([f"locmode:state"] if q["loc_mode"] == "state" else []) + ([f"states:{'>'.join(q['states'])}"] if q["states"] else []) + (["alsorad:1"] if q["also_radius"] else []) + ([f"cond:{q['condition']}"] if q["condition"] else [])
    return {**{k: f[k] for k in ("csrf", "pin", "nonce") if k in f}, "title": (f.get("title") or q["keywords"]).strip() or "Marketplace search",
            "category": CATEGORY, "keywords": q["keywords"].replace(" ", ", "), "max_price_usd": "" if q["max_price"] is None else str(q["max_price"]),
            "radius_miles": "" if q["radius"] is None else str(q["radius"]), "origin": q["base"],
            "must_have": ", ".join(q["required"]), "nice_to_have": ", ".join(nice), "level": "RECOMMEND"}


def go_url(q: dict) -> str:
    return "/market?go=1&" + "&".join(f"{k}={quote(str(v))}" for k, v in q.items() if v not in (None, "", []))
