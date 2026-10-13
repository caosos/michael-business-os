"""F-159: the GSA-Auctions-style browse layer for /market. Pure functions, no write path except the remembered sidebar state (existing market prefs file, key `ui`).
Quick views, listing type, source filter, live facet counts (each count = the rows you would get by choosing that value, everything else unchanged), the uniform card,
numbered pagination and the sticky top bar. Reuses market_search filters and the F-157 categories; nothing here is a second store or a second filter path."""

from __future__ import annotations

import html
import re
from datetime import datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import market_bids as mbids
from . import market_prefs as mp
from . import market_search as ms
from . import market_source_panel as msp
from . import market_sources as msrc
from .deal_ui import classify_url

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
CT = ZoneInfo("America/Chicago")
HOME = {"state": "AR", "zip": "72032", "label": "Conway"}        # this owner's default; whoever logs in later sets their own in prefs `ui.home`
RADII = ("10", "25", "50", "100", "250", "")
SORT_LABELS = (("closing", "Ending soonest"), ("new", "Newest"), ("bid", "Price: low to high"), ("price_desc", "Price: high to low"), ("distance", "Distance"), ("suggested", "Suggested"))
QUICK_LABELS = (("", "All"), ("saved", "Saved"), ("new", "New today"), ("today", "Closing today"), ("soon", "Closing soon"))
LTYPE_LABELS = (("auction", "Auction"), ("fixed", "Buy now or fixed price"), ("event", "Auction event"))
CONDITION_OPTS = ("new", "used", "salvage", "for parts", "not working", "working", "as is")
SOON_H = 72


# ---- remembered owner state (existing prefs file) ----
def ui_state() -> dict:
    d = mp.load().get("ui")
    return d if isinstance(d, dict) else {}


def home() -> dict:
    h = ui_state().get("home")
    h = h if isinstance(h, dict) else {}
    if "state" in h and not h["state"] and not h.get("zip"):
        return {"state": "", "zip": "", "label": "", "radius": ms.DEFAULT_RADIUS, "categories": list(ms.DEFAULT_CATS)}
    st = str(h.get("state") or HOME["state"]).upper()
    raw_cats = h.get("categories") if isinstance(h.get("categories"), list) else ms.DEFAULT_CATS
    cats = [c for c in raw_cats if c in ms.CONTROL_CATS]
    try:
        radius = float(h.get("radius", ms.DEFAULT_RADIUS))
    except (TypeError, ValueError):
        radius = ms.DEFAULT_RADIUS
    return {"state": st if st in ms.US_STATES else HOME["state"], "zip": str(h.get("zip") or HOME["zip"])[:60], "label": str(h.get("label") or HOME["label"])[:60],
            "radius": radius if 1 <= radius <= 500 else ms.DEFAULT_RADIUS, "categories": cats or list(ms.DEFAULT_CATS)}


def collapsed() -> bool:
    return bool(ui_state().get("filters_collapsed"))


def set_collapsed(flag: bool) -> str:
    d = mp.load()
    ui = d.get("ui") if isinstance(d.get("ui"), dict) else {}
    d["ui"] = {**ui, "filters_collapsed": bool(flag)}
    mp._store(d)
    return "Filters sidebar collapsed." if flag else "Filters sidebar expanded."


def with_home(qs: dict) -> dict:
    """A visit that names no location starts with this account's city/ZIP, radius and wanted categories."""
    if any(k in qs for k in ("state", "loc_mode", "base", "radius", "run", "edit")):
        return qs
    h = home()
    if not h["zip"]:
        return qs
    return {**qs, "loc_mode": ["distance"], "base": [h["zip"]], "radius": [f"{h['radius']:g}"], "cat": list(h["categories"])}


# ---- row predicates ----
def _today(now: datetime):
    return now.astimezone(CT).date()


def ltype(c: dict) -> str:
    if c.get("event"):
        return "event"
    return "fixed" if c.get("price_type") in ("asking", "fixed", "buy_now") or c.get("kind") in ("fixed", "owner-entered") else "auction"


def source_key(c: dict) -> str | None:
    for k, n in _names().items():
        if n == c.get("source"):
            return k
    return None


def _names() -> dict:
    return {i.key: i.name for i in msrc.REGISTRY}


def selected_sources(q: dict | str) -> set[str]:
    raw = q.get("source", "all") if isinstance(q, dict) else q
    vals = {v for v in str(raw or "all").split(",") if v}
    return {"all"} if not vals or "all" in vals else vals


def source_ok(c: dict, source: str) -> bool:
    selected = selected_sources(source)
    if "all" in selected:
        return True
    if msrc.ALL_HOUSES in selected and c.get("source") in msrc.EVENT_NAMES:
        return True
    return any(c.get("source") == _names().get(key, key) for key in selected)


def quick_ok(c: dict, quick: str, now: datetime) -> bool:
    if not quick:
        return True
    if quick == "saved":
        return bool(c.get("saved"))
    if quick == "new":
        return c.get("posted") == _today(now).isoformat()
    t = mbids._end(c)
    if t is None or t <= now:
        return False
    if quick == "today":
        return t.astimezone(CT).date() == _today(now)
    return t <= now + timedelta(hours=SOON_H)


def post(rows: list[dict], q: dict, now: datetime, relax=()) -> list[dict]:
    """Source, listing type and quick view on rows that already passed the market_search filters. `relax` skips a dimension (used to count it)."""
    return [c for c in rows if ("source" in relax or source_ok(c, q["source"])) and ("ltype" in relax or not q.get("ltype") or ltype(c) == q["ltype"])
            and ("quick" in relax or quick_ok(c, q.get("quick") or "", now))]


# ---- facet counts ----
def facets(res, q: dict, now: datetime) -> dict:
    """`res(qq, relax)` -> the checked result rows for filter dict qq (the same chain as the grid). Every count below equals len(res(...)) with that one value chosen."""
    wide = res({**q, "cat_all": True, "cat_default": False}, ()) if not (q.get("any") and q["any"] != ms._terms(ms.DEFAULT_ANY) and not q.get("broad")) else None
    cats = {}
    for k in ms.CONTROL_CATS:
        cats[k] = sum(1 for c in wide if k in ms.card_cats(c)) if wide is not None else len(res({**q, "cats": [k], "cat_all": False, "cat_default": False}, ()))
    cats["all"] = len(wide) if wide is not None else len(res({**q, "cat_all": True, "cat_default": False}, ()))
    by_src = res(q, ("source",))
    src = {}
    for c in by_src:
        k = source_key(c)
        src[k] = src.get(k, 0) + 1
    st_rows = res({**q, "loc_mode": "state", "states": list(ms.US_STATES)}, ())
    states = {}
    for c in st_rows:
        if c.get("state"):
            states[c["state"]] = states.get(c["state"], 0) + 1
    lt_rows = res(q, ("ltype",))
    ltypes = {k: sum(1 for c in lt_rows if ltype(c) == k) for k, _ in LTYPE_LABELS}
    cd_rows = res({**q, "condition": ""}, ())
    conds = {k: sum(1 for c in cd_rows if k in c["text"]) for k in CONDITION_OPTS}
    qk_rows = res(q, ("quick",))
    quick = {"": len(qk_rows), **{k: sum(1 for c in qk_rows if quick_ok(c, k, now)) for k in ms.QUICK}}
    return {"cats": cats, "source": src, "all_sources": len(by_src), "states": states, "ltype": ltypes, "cond": conds, "quick": quick}


def active_filters(q: dict) -> int:
    """The number on the Filters button: filters that differ from the owner's starting view (the search box is not counted)."""
    h = home()
    n = 0
    start_cats = set(q.get("cats") or []) == set(h["categories"]) and not q.get("cat_all")
    n += not start_cats
    n += selected_sources(q) != {"all"}
    start_loc = (q.get("loc_mode") != "state" and q.get("base") == h["zip"] and q.get("radius") == h["radius"]) if h["zip"] else \
        (q.get("loc_mode") != "state" and not q.get("base") and q.get("radius") is None)

    n += not start_loc
    n += q.get("min_price") is not None or q.get("max_price") is not None
    n += bool(q.get("ltype")) + bool(q.get("condition")) + bool(q.get("closing_by")) + bool(q.get("quick"))
    n += sum(1 for k in ("required", "preferred", "exclude") if q.get(k))
    n += bool(q.get("any") and q["any"] != ms._terms(ms.DEFAULT_ANY)) + bool(q.get("broad"))
    return int(n)


# ---- links ----
def href(q: dict, page: int | None = None, **ov) -> str:
    from . import market_view as mv
    qq = {**q, **ov}
    if "cats" in ov:
        qq.update(cat_all=False, cat_default=False)
    url = mv.chip_url(qq)
    return url + (f"&amp;page={page}" if page and page > 1 else "")


def paginate(rows: list[dict], page: int, size: int = ms.PAGE_SIZE) -> tuple[list[dict], int, int]:
    pages = max(1, -(-len(rows) // size))
    page = min(max(1, page), pages)
    return rows[(page - 1) * size: page * size], page, pages


def pager(q: dict, page: int, pages: int, total: int) -> str:
    if pages <= 1:
        return ""
    show = sorted({1, pages, *range(max(1, page - 2), min(pages, page + 2) + 1)})
    out, prev = [], 0
    for n in show:
        if n - prev > 1:
            out.append("<span class='mut'>…</span>")
        out.append(f"<b class='mk-pg cur' aria-current='page'>{n}</b>" if n == page else f"<a class='mk-pg' href='{href(q, n)}'>{n}</a>")
        prev = n
    nav = (f"<a class='mk-pg' rel='prev' href='{href(q, page - 1)}'>Previous</a>" if page > 1 else "") + "".join(out) + (f"<a class='mk-pg' rel='next' href='{href(q, page + 1)}'>Next</a>" if page < pages else "")
    lo, hi = (page - 1) * ms.PAGE_SIZE + 1, min(total, page * ms.PAGE_SIZE)
    return f"<nav class='mk-pages' id='pager' aria-label='Result pages'>{nav}<span class='small mut'> Showing {lo}-{hi} of {total} · page {page} of {pages}</span></nav>"


# ---- the card ----
def countdown(c: dict, now: datetime) -> tuple[str, bool]:
    """-> (text, red). A real timestamp gives minutes; a date-only close can only say 'Closes today (time UNKNOWN)'. Nothing under 24 h or unknown -> ('', False)."""
    t = mbids._end(c)
    if t is None:
        return "", False
    precise = bool(c.get("closes_at"))
    s = int((t - now).total_seconds())
    if s <= 0:
        return "Closed", False
    if not precise:
        return ("Closes today (time UNKNOWN)", True) if t.astimezone(CT).date() == _today(now) else ("", False)
    if s >= 86400:
        return "", False
    if s < 60:
        return "Closing", True
    return (f"{s // 60} min left" if s < 3600 else f"{s // 3600} h {s % 3600 // 60} min left"), True


def _view(c) -> str:
    from . import market_detail                   # F-160: View opens OUR detail page; the original listing link lives there
    return f"<a class='mk-view' href='{e(market_detail.href(c))}'>View</a>"


def card(c: dict, tok, now: datetime, pref_buttons) -> str:
    from . import market_view as mv
    img = mv._photo(c.get("image"), c.get("url"))
    # Empty photo data must not consume half the card.  Real source images are
    # shown; otherwise this remains a compact text listing with no fake or
    # broken placeholder.
    media = f"<div class='mk-ph'>{img}</div>" if img.startswith("<img") else ""
    txt, red = countdown(c, now)
    cd = f"<span class='mk-cd{' red' if red else ''}'>{e(txt)}</span>" if txt else ""
    place = e(_where(c)) + (f" · {round(c['distance'], 1):g} mi" if c.get("distance") is not None else " · distance UNKNOWN")
    ti = c["title"] if len(c["title"]) <= 70 else c["title"][:69] + "…"
    closes = c.get("closes_local") or msrc.local_when(c.get("closes")) or "closes UNKNOWN"
    if c.get("event"):
        money = "<div class='pr'>Auction event</div><div class='small mut'>current bid / bidders UNKNOWN (event, not a lot)</div>"
    elif ltype(c) == "fixed":
        price = c.get("price") if c.get("price") is not None else c.get("bid")
        label = "asking price" if c.get("price_type") == "asking" else "fixed price"
        unit = f" {e(c['unit'])}" if c.get("unit") else ""
        shown = f"${price:,.2f}" if c.get("unit") else f"${price:,.0f}"
        money = f"<div class='pr'>{shown}{unit}</div><div class='small mut'>{label}</div>" if price is not None else "<div class='pr'>Price not stated</div><div class='small mut'>check original listing</div>"
    else:
        bd = c.get("bidders")
        bidders = f"{bd} bidder{'s' if bd != 1 else ''}" if isinstance(bd, int) and not isinstance(bd, bool) else "bidders UNKNOWN"
        cur = f"<div class='pr'>${c['bid']:,.0f}</div><div class='small mut'>current bid · {e(bidders)}</div>" if c["bid"] is not None else f"<div class='pr'>No bids yet</div><div class='small mut'>{e(bidders)}</div>"
        money = cur
    flag = " <span class='badge'>SAVED</span>" if c.get("saved") else ""
    msvm = __import__("operator_ui.market_source_view", fromlist=["x"])
    note = msvm.card_note(c)
    kind = " data-kind='auction-event'" if c.get("event") else ""
    plat = msvm._platform(c) if c.get("event") else ""
    lbl = (f"<div class='small'>{plat}</div>" if plat else "") if c.get("event") else "<div class='small mut gal-lbl'>" + mv.gallery_labels(c) + "</div>"
    save = mv.save_button(c, tok)
    actions = pref_buttons(c, tok, include_save=False, include_hide=False, include_why=False) if pref_buttons is mv.pref_buttons else pref_buttons(c, tok)
    more = f"<details class='mk-more'><summary title='More actions' aria-label='More actions'>&#8943;</summary>{lbl}{actions}</details>"
    reason = f"<div class='small mut mk-why' data-why>{e(c['why'])}</div>" if c.get("why") else ""
    if cd and img.startswith("<img"):
        media = media.replace("</div>", f"{cd}</div>", 1)
    elif cd:
        media += cd
    return (f"<div class='mk-g mk-card' data-lot='{e(c['id'])}'{kind}>{media}"
            f"<div class='ti'><b>{e(ti)}</b>{flag}</div><div class='small'>{place}</div>{note}<div class='small mut'>Closes {e(closes)}{c.get('closing_badge', '')}</div>{money}"
            f"{reason}<div class='mk-card-src'><span class='mk-src'>{e(c['source'])}</span></div>"
            f"<div class='mk-vw'>{_view(c)}{save}{mv.hide_button(c, tok)}{more}</div></div>")


# ---- sidebar sections / top bar ----
def _count(n, zero_cls="mut") -> tuple[str, str]:
    return f" <span class='mk-n'>({n})</span>", (f" {zero_cls}" if not n else "")


def category_section(q: dict, fc: dict) -> str:
    on, find = set(q.get("cats") or []), (q.get("cat_find") or "").strip().lower()
    # Keep the visible boxes truthful after a round trip.  Selecting All means
    # every category is selected, so every category box stays checked on the
    # rendered response (the source picker already behaves this way).
    all_on = bool(q.get("cat_all"))
    items = [("all", "All categories", all_on)] + [(k, ms.CAT_LABELS[k], all_on or k in on) for k in ms.CONTROL_CATS]
    rows = ""
    for k, lbl, ck in items:
        if find and find not in lbl.lower() and not ck:
            continue
        n = fc["cats"].get(k, 0)
        cnt, _ = _count(n)
        rows += f"<label class='mk-cat' data-count='{n}'><input type='checkbox' form='mkform' name='cat' value='{e(k)}'{' checked' if ck else ''}> {e(lbl)}{cnt}</label>"
    hid = "".join(f"<input type='hidden' form='mkform' name='cat' value='{k}'>" for k in (q.get("cats") or []) if find and find not in ms.CAT_LABELS[k].lower() and not q.get("cat_all") and not q.get("cat_default"))
    return ("<details open class='mk-sect' id='sec-category'><summary><b>Category</b></summary>"
            f"<label class='small'>Filter categories <input form='mkform' name='cat_find' size='10' value='{e(q.get('cat_find') or '')}'></label>"
            f"<div id='mkcats'>{rows}{hid}</div><p class='small mut'>Land/Real Estate starts unticked; a lot that also matches a ticked category stays. None ticked = the defaults.</p></details>")


def source_section(q: dict, fc: dict, now: datetime) -> str:
    selected = selected_sources(q)
    all_on = "all" in selected
    rows = f"<label class='mk-src-row'><input type='checkbox' form='mkform' name='source' value='all'{' checked' if all_on else ''}> <b>All sources</b> <span class='mk-n'>({fc['all_sources']})</span></label>"
    for r in msp.rows(now):
        i, st = r["info"], r["state"]
        n = fc["source"].get(i.key, 0)
        state = {"LIVE CONNECTED": "connected", "CONNECTED, WAITING FOR ALERTS": "connected, waiting for alerts", "MANUAL": "manual: paste finds", "BLOCKED": "blocked"}.get(st, "not connected")
        if r["probe"]["status"] == "fixture":
            state = "FIXTURE, not live"
        checked = all_on or i.key in selected
        box = f"<input type='checkbox' form='mkform' name='source' value='{e(i.key)}'{' checked' if checked else ''}>"
        rows += (f"<label class='mk-src-row' data-src='{e(i.key)}' data-count='{n}'>{box} {e(i.name)} <span class='mk-n'>({n})</span> "
                 f"<span class='small {'' if state == 'connected' else 'mut'}'>{e(state)}</span></label>")
    return (f"<details open class='mk-sect' id='sec-source'><summary><b>Sources</b></summary>{rows}"
            "<p class='small mut'>Choose any combination. All sources selects every row; untick All to exclude individual sources.</p></details>")


def ltype_section(q: dict, fc: dict) -> str:
    cur = q.get("ltype") or ""
    rows = f"<label><input type='radio' form='mkform' name='ltype' value=''{' checked' if not cur else ''}> Any</label>"
    for k, lbl in LTYPE_LABELS:
        n = fc["ltype"][k]
        rows += f"<label data-count='{n}'><input type='radio' form='mkform' name='ltype' value='{k}'{' checked' if cur == k else ''}> {e(lbl)} <span class='mk-n'>({n})</span></label>"
    return f"<details open class='mk-sect' id='sec-ltype'><summary><b>Listing type</b></summary>{rows}</details>"


def condition_section(q: dict, fc: dict) -> str:
    cur = q.get("condition") or ""
    rows = f"<label><input type='radio' form='mkform' name='condition' value=''{' checked' if not cur else ''}> Any</label>"
    for k in CONDITION_OPTS:
        n = fc["cond"][k]
        rows += f"<label data-count='{n}'><input type='radio' form='mkform' name='condition' value='{e(k)}'{' checked' if cur == k else ''}> {e(k.capitalize())} <span class='mk-n'>({n})</span></label>"
    if cur and cur not in CONDITION_OPTS:
        rows += f"<label><input type='radio' form='mkform' name='condition' value='{e(cur)}' checked> {e(cur)}</label>"
    return f"<details class='mk-sect' id='sec-condition'><summary><b>Condition</b> <span class='small mut'>(seller text)</span></summary>{rows}</details>"


def _where(c: dict) -> str:
    """F-164: 'City, ST ZIP' once. The cache city can already end in ', ST', so the state is appended only when it is missing."""
    city, st, z = (c.get("city") or "").strip(), (c.get("state") or "").strip(), (c.get("zip") or "").strip()
    if not city:
        return "town UNKNOWN"
    if st and not re.search(r",\s*" + re.escape(st) + r"$", city, re.I):
        city += f", {st}"
    return city + (f" {z}" if z and z not in city else "")


def top_bar(q: dict, total: int, sort_sel: str, view: str, csrf_tok, n_active: int, back: str, quick_counts: dict | None, folded: bool) -> str:
    """The sticky bar: one large search box (title + description), result count, Filters button with the active count, Sort, and the quick views."""
    opts = "".join(f"<option value='{k}'{' selected' if sort_sel == k else ''}>{e(lbl)}</option>" for k, lbl in SORT_LABELS)
    views = "".join(f"<option value='{k}'{' selected' if view == k else ''}>{lbl}</option>" for k, lbl in (("gallery", "Cards"), ("list", "Detailed list")))
    toggle = (f"<form method='post' action='/market/ui' class='mk-fd'>{csrf_tok()}<input type='hidden' name='back' value='{e(back)}'>"
              f"<button name='act' value='{'expand' if folded else 'collapse'}' id='filters-btn' class='mk-fbtn' aria-expanded='{'false' if folded else 'true'}'>Filters ({n_active})</button></form>"
              f"<label class='mk-fbtn mk-fm' for='mkdrawer' id='filters-btn-m'>Filters ({n_active})</label>")
    quick = ""
    if quick_counts is not None:
        quick = "<div class='mk-quick' id='quick-views' role='group' aria-label='Quick views'>" + "".join(
            f"<a class='mk-q{' cur' if (q.get('quick') or '') == k else ''}' data-quick='{k or 'all'}' href='{href(q, quick=k)}'>{e(lbl)} <span class='mk-n'>({quick_counts[k]})</span></a>" for k, lbl in QUICK_LABELS) + "</div>"
    return ("<div class='mk-top' id='topbar'><form method='get' action='/market' class='mk-form mk-bar' id='mkform' novalidate>"
            f"<input class='mk-search' type='search' name='keywords' form='mkform' aria-label='Search title and description' placeholder='Search title and description' value='{e(q.get('keywords') or '')}'>"
            "<button class='mk-go' type='submit' name='go' value='1'>Search</button>"
            f"<span id='result-count' class='mk-count'>{total:,} result{'s' if total != 1 else ''} found</span>"
            f"<label>Sort <select name='sort'>{opts}</select></label><label>View <select name='view'>{views}</select></label>"
            "</form>"
            f"{toggle}{quick}</div>")


CSS = """<style>
.mk-top{position:sticky;top:0;z-index:20;background:var(--bg);padding:6px 0;border-bottom:1px solid var(--line);display:flex;flex-wrap:wrap;gap:6px 12px;align-items:center}
.mk-top .mk-bar{flex:1 1 560px;align-items:center}.mk-search{flex:1 1 320px;font-size:18px;padding:10px 12px;min-width:0}.mk-count{font-weight:700;white-space:nowrap}
.mk-fbtn{background:var(--acc);color:var(--bg);border:0;border-radius:8px;padding:8px 14px;font-size:15px;width:auto;opacity:1;cursor:pointer}.mk-fd{margin:0}.mk-fm,.mk-side .mk-fm{display:none}
.mk-quick{flex:1 1 100%;display:flex;flex-wrap:wrap;gap:6px}.mk-q{border:1px solid var(--line);border-radius:16px;padding:4px 12px;font-size:14px;text-decoration:none}.mk-q.cur{background:#1d4ed8;color:#fff;border-color:#1d4ed8}.mk-q.cur .mk-n{color:#fff}
.mk-n{color:var(--mut,#777);font-size:12px}.mk-sect{border:1px solid var(--line);border-radius:8px;padding:4px 8px;margin:0 0 8px}.mk-sect label{display:block;padding:2px 0}.mk-side .mk-cat,.mk-sect label{opacity:1;color:var(--ink)!important}.mk-cat,.mk-src-row{opacity:1!important;color:var(--ink)!important}.mk-src-row .small{color:var(--ink)}
.mk-cat input,.mk-src-row input{accent-color:#1d4ed8}.mk-cat:has(input:checked),.mk-src-row:has(input:checked){background:color-mix(in srgb,#1d4ed8 12%,var(--card));border-color:#1d4ed8;font-weight:700}.mk-src-row{border-left:3px solid transparent;border-radius:5px;padding:4px 5px!important;margin:1px 0}
.mk-filter-head{position:sticky;top:0;z-index:3;background:var(--card);display:flex;align-items:center;justify-content:space-between;gap:8px;padding:2px 0 7px}.mk-filter-head .mk-apply{width:auto;margin:0;padding:7px 12px}
.mk-side.folded #mkfilters{display:none}.mk-drawer-t{position:absolute;opacity:0;pointer-events:none}
.mk-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px}.mk-card{display:flex;flex-direction:column;gap:2px}.mk-ph{position:relative}.mk-ph .ph{height:130px}.mk-ph img{height:130px}
.mk-cd{position:absolute;left:6px;bottom:6px;background:#444;color:#fff;border-radius:6px;padding:2px 8px;font-size:12px;font-weight:700}.mk-cd.red{background:#c0222c}.mk-card-src{display:flex;justify-content:flex-end;min-height:20px;margin-top:auto}.mk-src{font-size:12px;font-weight:700;color:var(--mut,#5d6470);text-align:right}
.mk-view{display:inline-block;background:var(--acc);color:var(--bg);border-radius:6px;padding:6px 18px;font-weight:700;text-decoration:none}.mk-vw{margin:4px 0;display:flex;gap:7px;align-items:center;flex-wrap:wrap}.mk-save{display:inline}.mk-save button{width:auto;padding:6px 12px;background:var(--card);color:var(--acc);border:1px solid var(--acc)}.mk-vw .mk-x{padding:6px 10px}.mk-off{background:transparent;color:var(--mut,#777);border:1px dashed var(--line);font-weight:400}
.mk-pages{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin:14px 0}.mk-pg{border:1px solid var(--line);border-radius:6px;padding:4px 10px;text-decoration:none}.mk-pg.cur{background:#1d4ed8;color:#fff}
.mk-top .mk-bar{flex-wrap:nowrap;gap:10px}.mk-top .mk-bar label{margin:0;white-space:nowrap}.mk-top select{width:auto}.mk-go{width:auto;padding:10px 18px;white-space:nowrap}
.mk-quick{padding:0}.mk-chips{display:flex;flex-wrap:nowrap;gap:4px;overflow:hidden;margin:2px 0;white-space:nowrap}.mk-chips .chip{flex:0 0 auto}
.mk-strip{margin:2px 0;border:1px solid var(--line);border-radius:8px;padding:2px 10px}.mk-strip>summary{cursor:pointer}#fixture-banner{margin:2px 0;padding:2px 10px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:13px}
.mk-more{display:inline-block;margin-left:8px;vertical-align:middle}.mk-more>summary{display:inline-block;cursor:pointer;border:1px solid var(--line);border-radius:6px;padding:2px 10px;font-weight:700;list-style:none}.mk-more[open]{display:block;margin:6px 0 0}
.mk-main>h2{margin:2px 0;font-size:16px}
@media(max-width:1400px){.mk-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}@media(max-width:1000px){.mk-grid{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){.mk-grid{grid-template-columns:minmax(0,1fr)}}
@media(max-width:700px){.mk-top .mk-bar{flex-wrap:wrap;gap:6px}.mk-top .mk-bar .mk-search{flex:1 1 60%}.mk-top{gap:4px 8px;padding:2px 0}.mk-quick{gap:4px}.mk-q{padding:2px 9px;font-size:13px}.pagehead{display:none}.mk-fd{display:none}.mk-fm,.mk-side .mk-fm{display:inline-block}.mk-side,.mk-side.folded{display:none;position:fixed;inset:0 20% 0 0;z-index:40;overflow:auto;background:var(--bg);padding:10px;box-shadow:4px 0 16px rgba(0,0,0,.4);width:auto}
.mk{align-items:stretch}.mk-main,.mk-side{min-width:0;max-width:100%}header{min-width:0}header nav{min-width:0;max-width:100%;overflow-x:auto}.mk-top{max-width:100%;box-sizing:border-box}.mk-top .mk-bar{display:contents}#topbar .mk-search{order:1;flex:1 1 100%;width:100%;box-sizing:border-box}#topbar .mk-go{order:2;flex:1 1 40%}#topbar .mk-fm{order:3;flex:1 1 40%;text-align:center;box-sizing:border-box}#topbar .mk-count{order:4;flex:1 1 100%;white-space:normal}#topbar .mk-bar label:not(.mk-fm){order:5;flex:1 1 40%}#topbar .mk-quick{order:6;flex:1 1 100%;flex-wrap:nowrap;overflow-x:auto;max-width:100%}.mk-q{white-space:nowrap;flex:0 0 auto}#fixture-banner{white-space:normal;overflow-wrap:anywhere}.mk-chips{flex-wrap:wrap;white-space:normal}.mk-card,.mk-grid>*{min-width:0;overflow-wrap:anywhere}
#mkdrawer:checked~.mk .mk-side{display:block}.mk-side.folded #mkfilters{display:block}.mk-top{position:static}.mk-search{font-size:16px}}
</style>"""
