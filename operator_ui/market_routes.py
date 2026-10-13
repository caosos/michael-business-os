"""F-47: the two thin entry points server.py calls for /market (GET page, POST save/edit/enable/disable). Saved searches go through
App.wanted_change, so the Wanted model, its history rows, CSRF + PIN and receipts are reused; no second datastore."""

from __future__ import annotations

import os
from urllib.parse import quote

from . import landing_fix
from . import market_search as ms
from . import market_suggest as msug
from . import market_prefs as mp
from . import market_view as mv
from . import market_browse as mbr
from . import market_finds as mf
from . import market_autobids as mba
from . import market_bids as mb
from . import finds_view as fv
from .ux import InputError


def _saved(app) -> list[dict]:
    out = []
    for r in app.campaign_records():
        d = r.get("doc") if isinstance(r, dict) else None
        if isinstance(d, dict) and (d.get("criteria") or {}).get("category") == mv.CATEGORY:
            out.append(r)
    return out


FILTER_KEYS = ("keywords", "base", "radius", "min_price", "max_price", "any", "broad", "condition", "required", "preferred", "exclude", "source",
               "kind", "closing_by", "sort", "cat", "row1", "row2", "row3", "row4", "view", "state", "loc_mode", "also_radius", "state_find", "ltype", "quick", "cat_find")


def _remembered(app, qs: dict) -> dict:
    """Entered filters persist across navigation AND a server restart (single owner): a visit with no filters restores the last search
    from the prefs file (MBOS_MARKET_PREFS_FILE); `new` clears it. Saving as a campaign is separate (Wanted)."""
    given = {k: qs[k] for k in FILTER_KEYS if k in qs}
    if qs.get("new"):
        mp.remember({})
    elif given:
        if ms.parse_query(given)["errors"]:
            pass                                      # F-54: a refused request never replaces the last good choices
        elif given != mp.recall(FILTER_KEYS):
            mp.remember({k: v if isinstance(v, list) else [v] for k, v in given.items()})
    elif not (qs.get("run") or qs.get("edit")):
        last = mp.recall(FILTER_KEYS)
        if last:
            return {**qs, **last}
    return qs


def page_body(app, qs: dict, now, errors=None, values=None) -> str:
    qs = _remembered(app, qs) if values is None else qs
    page_qs = qs
    qs = mbr.with_home(qs) if values is None else qs        # F-159: no location named -> this owner's home (By State, their state, their ZIP)
    saved = _saved(app)
    ids = {r["doc"]["campaign_id"]: r["doc"] for r in saved}
    pick = (qs.get("run") or qs.get("edit") or [None])[0]
    if values is not None:
        q = ms.parse_query({k: [v] for k, v in values.items()})
    elif pick in ids:
        q = ms.parse_query({k: v if isinstance(v, list) else [str(v)] for k, v in ms.criteria_to_query(ids[pick]).items()})
    else:
        q = ms.parse_query(qs)
    edit = (qs.get("edit") or [None])[0]
    ran = not qs.get("new") and not qs.get("edit")
    # Always load the unified source pool once. The browse layer applies the selected source checkboxes.
    # A paid provider refresh is an explicit owner action: Search/Run may refresh Facebook,
    # ordinary page loads, filter navigation and reloads only read the last successful cache.
    source_query = {**q, "_facebook_refresh": bool(qs.get("go") or qs.get("run"))}
    data = ms.load_source("all", now, ms._origin(q["base"]), os.environ.get("MBOS_GSA_CACHE") or None, query=source_query) if ran else \
        {"status": "connected", "as_of": None, "age_h": 0, "stale": False, "in_scope": 0, "in_file": 0, "cards": [], "message": ""}
    allcards = data["cards"] if ran else []
    prefs = mp.load()
    auto, auto_note = mba.load(now, prefs)             # F-152: bid e-mails read from the staging fixture directory only; else a one-line not-connected note
    au = mba.urls(auto)
    live = ran and data["status"] in ("connected", "fixture", "imported") and not q["errors"]

    def chain(qq, relax=()):                           # F-159: ONE filter chain for the grid and for every facet count, so a count always equals the rows you get
        # Source/type/quick are hard filters too.  Apply them to the common
        # pool before partitioning or counting owner-hidden rows; otherwise a
        # GSA-only page can claim that a matching Facebook row was hidden.
        # Saved state must be attached first because the Saved quick view is
        # one of these pre-partition filters.
        saved_ids = set(prefs.get("saved") or [])
        pool = [{**c, "saved": c["id"] in saved_ids} for c in allcards]
        pool = mbr.post(pool, qq, now, relax) if live else []
        res, unch, hid = ms.partition(pool, qq) if live else ([], [], {})
        if ms.radius_applies(qq):                      # P0-06: a listing whose distance cannot be measured is never shown inside a radius
            far = [c for c in unch if c.get("distance") is None]
            unch = [c for c in unch if c.get("distance") is not None]
            if far:
                hid = {**hid, "location_unknown": len(far)}
        n0 = len(res) + len(unch)
        res, g1 = mp.hide(res, prefs)                  # a hidden listing stays hidden in BOTH sections, with suggestions on or off
        unch, g2 = mp.hide(unch, prefs)
        res, x1 = mb.exclude(res, prefs, au)           # F-147: tracked ("I bid on this") items leave the lineup; they live in the My bids window
        unch, x2 = mb.exclude(unch, prefs, au)
        return res, unch, hid, (n0, g1, g2, x1, x2)

    results, unchecked, hidden, (n_before, g1, g2, b1, b2) = chain(q)
    q["hidden_n"], q["hidden_checked"], q["matched_n"] = g1 + g2, g1, n_before - b1 - b2
    if prefs["enabled"] and "sort" not in qs and (prefs["saved"] or prefs["more"] or prefs["less"]):
        q["sort"] = "suggested"                      # feedback exists and the owner chose no sort: use it; hard filters already ran
    if prefs["enabled"]:                              # dismissed lots are hidden and saved/why shown always; the ORDER follows the sort the owner chose
        results, _ = mp.rank(results, prefs, lambda c: (c["closes"] or "9999", c["title"]), q["sort"] == "suggested")
    if q["hidden_n"]:
        hidden = {**hidden, "hidden by you (restore from the hidden list)": q["hidden_n"]}
    note = landing_fix.origin_note(q["base"], ms._origin(q["base"]) is not None, q["radius"] if q["loc_mode"] != "state" or q["also_radius"] else None) if ran else ""
    finds = ""
    if ran and not q["errors"]:                       # F-141: owner-entered finds, their own section, never in the GSA results or counts
        tok = lambda: f"<input type='hidden' name='csrf' value='{app.csrf}'><input type='hidden' name='nonce' value='{__import__('secrets').token_hex(8)}'>"  # noqa: E731
        fr, fu, *fr_rest = mf.cards(q, prefs)
        fr, f1 = mb.exclude(fr, prefs, au)
        fu, f2 = mb.exclude(fu, prefs, au)
        b1 += f1 + f2
        finds = fv.section(fr, fu, *fr_rest, tok, mv.pref_buttons)
    tok = lambda: f"<input type='hidden' name='csrf' value='{app.csrf}'><input type='hidden' name='nonce' value='{__import__('secrets').token_hex(8)}'>"  # noqa: E731
    mine = mb.window(prefs, data["cards"] if ran else [], now, tok, (auto, auto_note)) + (f"<p class='small mut' id='bids-count'>{b1 + b2} in My bids (left out of the results below)</p>" if b1 + b2 else "")
    sg = msug.suggest(results + unchecked, prefs) if ran and results + unchecked and not q["errors"] and data["status"] in ("connected", "imported") else None
    sug = msug.render(sg, tok) if sg else ""      # F-155: engine-ranked panel, display only
    # Facet counts describe the same combined feed the owner sees.  Listings
    # with an unverified distance/price stay selectable and paginate normally;
    # they must not make a category or source look empty.
    fc = mbr.facets(lambda qq, relax: chain(qq, relax)[0] + chain(qq, relax)[1], q, now) if live else None
    back = "/market?" + "&".join(f"{k}={quote(str(v))}" for k, vs in page_qs.items() if k in FILTER_KEYS + ("page",) for v in (vs if isinstance(vs, list) else [vs])) if page_qs else "/market"
    return note + mv.render_page(q, data, results, hidden, saved, app.csrf, bool(app.operator_pin), edit if edit in ids else None, ran, errors, unchecked, prefs, finds, mine, mv.suggest_strip(sug, len(sg['ranked']) if sg else 0),
                                 {"fc": fc, "now": now, "back": back} if fc else None)


def post(app, parts: list[str], f: dict) -> tuple[str | None, list[str] | None]:
    """-> (redirect location, None) on success or (None, errors). parts: ['market','save'] | ['market',cid,'edit'|'pause'|'resume']."""
    try:
        if parts == ["market", "pref"]:
            app._check_csrf(f)                       # a local view preference: CSRF only, no PIN, no money or contact
            msg = mp.act(f.get("act", ""), f.get("lot", ""), f.get("title", ""), f.get("category", ""), f.get("source", ""))
        elif parts == ["market", "bid"]:
            app._check_csrf(f)                       # owner-reported bid tracking in the local prefs file: CSRF only, nothing is placed, fetched or sent
            msg = mb.act(f.get("act", ""), f, __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"))
        elif parts == ["market", "ui"]:
            app._check_csrf(f)                       # F-159: the remembered filters-sidebar state (local prefs file): CSRF only
            msg = mbr.set_collapsed(f.get("act") == "collapse")
            back = f.get("back") or ""
            if back.startswith("/market?") and all(32 <= ord(ch) < 127 for ch in back) and "\\" not in back:
                return back, None
        elif parts == ["market", "resale"]:
            app._check_csrf(f)                       # F-155: owner-set resale price in the local prefs file: CSRF only, nothing is sent or spent
            msg = msug.act_resale(f)
        elif parts == ["market", "find"]:
            app._check_csrf(f)                       # owner-entered text kept in a local file: CSRF only, nothing is fetched, sent or spent
            msg = mf.act(f.get("act", ""), f)
        elif parts == ["market", "save"]:
            msg = app.wanted_change(mv.save_form(f), None, "create")
        elif len(parts) == 3 and parts[2] in ("edit", "pause", "resume"):
            msg = app.wanted_change(mv.save_form(f) if parts[2] == "edit" else f, parts[1], parts[2])
        else:
            raise InputError("unknown marketplace action")
    except (InputError, ValueError) as ex:
        return None, [str(ex)]
    return_to = f.get("return_to") or ""
    target = "/market/bids" if return_to == "/market/bids" else "/market"
    return f"{target}?msg={quote(msg)}", None
