"""F-45: the owner-liaison fixes (2026-10-09) on the EXISTING deal card and Resale page; no new dashboard.

Links, photos and the seller's ad are rendered defensively (everything escaped; fixture hosts are DEMO and never links); the
glanceable card keeps receipts and raw JSON behind "View proof"; filters and presets are explained, never deleting; the tow vehicle
and its limits are editable user fields. DRY-RUN: nothing here fetches, bids, buys, contacts or publishes.
"""

from __future__ import annotations

import html
import json
import os
from urllib.parse import parse_qsl, quote, urlsplit

e = lambda v: html.escape("" if v is None else str(v), quote=True)  # noqa: E731

LISTING_HOSTS = ("govdeals.com", "publicsurplus.com", "gsaauctions.gov", "ebay.com", "craigslist.org", "facebook.com", "proxibid.com",
                 "bidspotter.com", "auctionzip.com", "hibid.com", "ritchiebros.com", "iaai.com", "copart.com")  # override: MBOS_LISTING_HOSTS=a.com,b.com
DEMO_SUFFIXES = (".invalid", ".example", ".test", ".localhost", ".example.com", ".example.org", ".example.net")
MAX_URL = 2048


def allowed_hosts() -> tuple:
    env = os.environ.get("MBOS_LISTING_HOSTS")
    return tuple(h.strip().lower() for h in env.split(",") if h.strip()) if env else LISTING_HOSTS


def _is_demo_host(h: str) -> bool:
    return h.endswith(DEMO_SUFFIXES) or h in ("example.com", "example.org", "example.net", "localhost", "invalid", "example", "test")


def classify_url(url, hosts=None) -> tuple[str, str]:
    """-> (kind, detail). kind: live (detail = the url) | demo | none | rejected (detail = reason). Never raises."""
    if not url or not isinstance(url, str) or not url.strip():
        return "none", "no link captured"
    u = url.strip()
    if len(u) > MAX_URL or any(c.isspace() or ord(c) < 32 or c in "\\\"'<>" for c in u):
        return "rejected", "malformed link"
    try:
        p = urlsplit(u)
        host, port = (p.hostname or "").lower(), p.port
    except ValueError:
        return "rejected", "malformed link"
    if p.scheme not in ("http", "https") or not host:
        return "rejected", f"scheme '{p.scheme or 'none'}' is not allowed (http or https only)"
    if p.username is not None or p.password is not None or port not in (None, 80, 443):
        return "rejected", "credentials or an unusual port in the link"
    if _is_demo_host(host):
        return "demo", f"{host}{p.path}"
    if any(v.lower().startswith(("http://", "https://", "//", "javascript:", "data:")) for _, v in parse_qsl(p.query)):
        return "rejected", "link carries a redirect target"
    if not any(host == h or host.endswith("." + h) for h in (hosts or allowed_hosts())):
        return "rejected", f"host {host} is not on the allowed listing-site list"
    return "live", u


def render_link(deal: dict) -> str:
    kind, detail = classify_url(deal.get("url"))
    if deal.get("demo") and kind != "none":
        kind, detail = "demo", (detail if kind == "demo" else "fixture")
    if kind == "live":
        host = urlsplit(detail).hostname
        return (f"<a class='listing-link' href=\"{e(detail)}\" target='_blank' rel='noopener noreferrer nofollow'>View original listing</a> "
                f"<span class='small mut'>({e(host)})</span>")
    if kind == "demo":
        return f"<span class='lbl'>DEMO</span> <span class='small mut'>fixture link <code>{e(detail)}</code> is not a live listing and is not clickable</span>"
    why = f" <span class='small mut'>({e(detail)})</span>" if kind == "rejected" else ""
    return f"<span class='small mut'><b>No verified live link</b>{why}</span>"


# ---------------------------------------------------------------- photos
def _photos(deal: dict) -> list[dict]:
    out = []
    for p in deal.get("photos") or []:
        if isinstance(p, str):
            p = {"url": p}
        if isinstance(p, dict):
            out.append({"url": p.get("url"), "kind": "mockup" if str(p.get("kind", "")).lower() == "mockup" else "original",
                        "source": p.get("source") or deal.get("source") or "UNKNOWN", "captured_at": p.get("captured_at") or "UNKNOWN",
                        "expired": bool(p.get("expired"))})
    return out


def _photo_ok(url) -> bool:
    """A photo may load only from a plain http(s) URL on a real host: no credentials, no fixture host, no data/javascript."""
    if not isinstance(url, str) or not url.strip() or len(url.strip()) > MAX_URL:
        return False
    u = url.strip()
    if any(c.isspace() or ord(c) < 32 or c == "\\" for c in u):
        return False
    try:
        p = urlsplit(u)
        host = (p.hostname or "").lower()
        return p.scheme in ("http", "https") and bool(host) and p.username is None and p.password is None and not _is_demo_host(host)
    except ValueError:
        return False


def _img(p: dict, big: bool = False) -> str:
    """The placeholder text sits under the image; if the image fails to load (CSP forbids script handlers) the placeholder stays visible."""
    shown = not p["expired"] and _photo_ok(p["url"])
    msg = ("Photo expired or removed by the source" if p["expired"] else "No photo available" if not p["url"] else
           "DEMO photo placeholder" if not shown and classify_url(p["url"])[0] == "demo" else "Photo unavailable")
    img = f"<img src=\"{e(str(p['url']).strip())}\" alt='' loading='lazy' referrerpolicy='no-referrer'>" if shown else ""
    return f"<div class='ph{' big' if big else ''}' role='img' aria-label='{e(msg)}'><span>{e(msg)}</span>{img}</div>"


def render_gallery(deal: dict) -> str:
    """Cover thumbnail + count + provenance; enlarge shows every ORIGINAL photo; mockups are kept in their own labelled box."""
    ph = _photos(deal)
    orig, mock = [p for p in ph if p["kind"] == "original"], [p for p in ph if p["kind"] == "mockup"]
    if not orig:
        cover = "<div class='ph' role='img' aria-label='No original photo'><span>No original photo</span></div>"
        head = "<span class='small mut'>0 photos</span>"
    else:
        cover = _img(orig[0])
        prov = orig[0]
        head = (f"<span class='small'><b>{len(orig)}</b> original photo{'s' if len(orig) != 1 else ''}</span><br>"
                f"<span class='small mut'>Source: {e(prov['source'])} · captured {e(prov['captured_at'])} · seller's own photos, unedited</span>")
    big = ""
    if len(orig) >= 1:
        big = ("<details class='enl'><summary>Enlarge / all photos</summary>"
               + "".join(f"<figure>{_img(p, True)}<figcaption class='small mut'>Photo {i}: {e(p['source'])}, captured {e(p['captured_at'])}</figcaption></figure>"
                         for i, p in enumerate(orig, 1)) + "</details>")
    mk = ""
    if mock:
        mk = ("<details class='mock'><summary>Mockup (not the real item): " + str(len(mock)) + "</summary>"
              "<p class='small bad'>MOCKUP: an illustration, never the seller's photo and never evidence of condition.</p>"
              + "".join(f"<figure>{_img(p, True)}<figcaption class='small mut'>Mockup · {e(p['source'])}</figcaption></figure>" for p in mock) + "</details>")
    return f"<div class='gallery'>{cover}<div class='gtxt'>{head}{big}{mk}</div></div>"


# ---------------------------------------------------------------- the seller's ad, verbatim
def render_description(deal: dict, limit: int = 280, max_lines: int = 5) -> str:
    raw = deal.get("description")
    if raw is None or not str(raw).strip():
        return "<p class='small mut'><b>Seller's ad:</b> none captured (UNKNOWN).</p>"
    text = str(raw).replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    long = len(text) > limit or len(lines) > max_lines
    box = lambda t: f"<div class='ad'>{e(t)}</div>"  # noqa: E731  (escaped; line breaks kept by CSS pre-wrap)
    if not long:
        return f"<div class='small mut'>Seller's original ad (verbatim)</div>{box(text)}"
    prev = "\n".join(lines[:max_lines])[:limit]
    return (f"<div class='small mut'>Seller's original ad (verbatim)</div>{box(prev + ' …')}"
            f"<details><summary>Show full ad</summary>{box(text)}</details>")


# ---------------------------------------------------------------- tow vehicle (editable user fields)
TOW_FIELDS = ("vehicle", "tow_limit_lb", "max_trailer_length_ft", "notes")


def parse_tow(f: dict) -> dict:
    out = {"vehicle": " ".join(str(f.get("vehicle") or "").split())[:100], "notes": " ".join(str(f.get("notes") or "").split())[:300]}
    for k, hi in (("tow_limit_lb", 100000), ("max_trailer_length_ft", 100)):
        raw = str(f.get(k) or "").replace(",", "").strip()
        if not raw:
            out[k] = None
            continue
        try:
            v = float(raw)
        except ValueError:
            raise ValueError(f"{k}: type a plain number or leave it blank") from None
        if not (0 < v <= hi) or v != v:
            raise ValueError(f"{k}: use a number above 0 and up to {hi:,}")
        out[k] = v
    return out


def transport_status(deal: dict, tow: dict) -> tuple[str, str]:
    """-> ('can_tow' | 'required' | 'unknown', why). Limits are the user's own saved numbers, never hard-coded."""
    if deal.get("transport_required"):
        return "required", "listing says transport is required"
    w, ln = deal.get("weight_lb"), deal.get("length_ft")
    lim, lmax = (tow or {}).get("tow_limit_lb"), (tow or {}).get("max_trailer_length_ft")
    if w is None or lim is None:
        return "unknown", ("your tow limit is not set" if lim is None else "the item's weight is UNKNOWN")
    if w > lim:
        return "required", f"{w:,.0f} lb is over your {lim:,.0f} lb tow limit"
    if ln is not None and lmax is not None and ln > lmax:
        return "required", f"{ln} ft is over your {lmax} ft length limit"
    return "can_tow", f"{w:,.0f} lb is within your {lim:,.0f} lb tow limit"


def render_tow(tow: dict, csrf: str, pin_set: bool) -> str:
    v = lambda k: e((tow or {}).get(k) if (tow or {}).get(k) is not None else "")  # noqa: E731
    pin = "<label>PIN<input name='pin' type='password' autocomplete='off' required></label>" if pin_set else "<p class='bad'>PIN not configured; saving is refused.</p>"
    return ("<details class='card' id='tow'><summary><b>My tow vehicle and limits</b> "
            f"<span class='small mut'>{e((tow or {}).get('vehicle') or 'not set')}, limit {v('tow_limit_lb') or 'UNKNOWN'} lb</span></summary>"
            "<p class='small mut'>Your own numbers, editable any time. They only drive the transport label and filter; they never hide a deal by themselves.</p>"
            f"<form method='post' action='/resale/tow'><input type='hidden' name='csrf' value='{e(csrf)}'>"
            f"<label>Tow vehicle<input name='vehicle' maxlength='100' value=\"{v('vehicle')}\"></label>"
            f"<label>Tow limit (lb)<input name='tow_limit_lb' inputmode='decimal' value=\"{v('tow_limit_lb')}\"></label>"
            f"<label>Longest trailer (ft)<input name='max_trailer_length_ft' inputmode='decimal' value=\"{v('max_trailer_length_ft')}\"></label>"
            f"<label>Notes<input name='notes' maxlength='300' value=\"{v('notes')}\"></label>{pin}<button class='b-HOLD' style='width:auto'>Save tow limits</button></form></details>")


# ---------------------------------------------------------------- filters
FILTER_KEYS = ("category", "subtype", "max_distance", "min_price", "max_price", "condition", "title_status", "sale_type", "closing_soon",
               "profit_at_least", "max_days", "confidence", "transport")
SALE_TYPES, TRANSPORT = ("", "auction", "fixed"), ("", "can_tow", "required")
CONF_RANK = {"UNKNOWN": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}
NUMERIC = {"max_distance", "min_price", "max_price", "profit_at_least", "max_days"}


def parse_filters(qs: dict) -> tuple[dict, list[str]]:
    """qs: {name: [values]} or {name: value}. Returns (clean filters, warnings). A bad number is ignored and named."""
    flt, warn = {}, []
    for k in FILTER_KEYS:
        v = qs.get(k)
        v = (v[0] if isinstance(v, list) and v else v) or ""
        v = " ".join(str(v).split())[:80]
        if not v:
            continue
        if k in NUMERIC:
            try:
                x = float(v.replace(",", "").lstrip("$"))
                if x != x or x in (float("inf"), float("-inf")):
                    raise ValueError
            except ValueError:
                warn.append(f"ignored '{v}' for {k}: type a plain number")
                continue
            v = x
        elif k == "sale_type" and v not in SALE_TYPES[1:] or k == "transport" and v not in TRANSPORT[1:] or k == "confidence" and v.upper() not in CONF_RANK:
            warn.append(f"ignored '{v}' for {k}")
            continue
        elif k == "confidence":
            v = v.upper()
        elif k == "closing_soon":
            v = "1" if v in ("1", "on", "true") else ""
            if not v:
                continue
        flt[k] = v
    return flt, warn


def _attrs(c: dict) -> dict:
    d = c.get("deal") or {}
    sale = d.get("sale_type") or ("auction" if c.get("hours_left") is not None or c.get("bids") is not None else None)
    return {"category": d.get("category") or d.get("asset_class"), "subtype": d.get("trailer_subtype"), "condition": d.get("condition"),
            "title_status": d.get("title_status"), "sale_type": sale}


def apply_filters(cards: list[dict], flt: dict, tow: dict) -> tuple[list[dict], list[tuple[dict, list[str]]]]:
    """Nothing is deleted: returns (kept, [(card, reasons)]). An UNKNOWN field never excludes a deal; confidence is a tier, so UNKNOWN ranks lowest."""
    kept, out = [], []
    for c in cards:
        a, why = _attrs(c), []
        for k in ("category", "subtype", "condition", "title_status"):
            if k in flt and a[k] is not None and str(flt[k]).lower() not in str(a[k]).lower():
                why.append(f"{k.replace('_', ' ')} is {a[k]}, not {flt[k]}")
        if "sale_type" in flt and a["sale_type"] and a["sale_type"] != flt["sale_type"]:
            why.append(f"it is a {a['sale_type']} sale, not {flt['sale_type']}")
        if "max_distance" in flt and c["distance"] is not None and c["distance"] > flt["max_distance"]:
            why.append(f"{c['distance']} mi is farther than {flt['max_distance']:g} mi")
        if "min_price" in flt and c["bid"] is not None and c["bid"] < flt["min_price"]:
            why.append(f"price {c['bid']:g} is under {flt['min_price']:g}")
        if "max_price" in flt and c["bid"] is not None and c["bid"] > flt["max_price"]:
            why.append(f"price {c['bid']:g} is over {flt['max_price']:g}")
        if "profit_at_least" in flt and c["net"] is not None and c["net"] < flt["profit_at_least"]:
            why.append(f"expected net {c['net']:g} is under {flt['profit_at_least']:g}")
        if "max_days" in flt and c["days"] is not None and c["days"] > flt["max_days"]:
            why.append(f"{c['days']:g} days to cash is over {flt['max_days']:g}")
        if flt.get("closing_soon") and not (c["hours_left"] is not None and c["hours_left"] <= 48):
            why.append("it is not closing within 48 hours")
        if "confidence" in flt:
            have = CONF_RANK.get(str(c["confidence"]).split(" ")[0].upper(), 0)
            if have < CONF_RANK[flt["confidence"]]:
                why.append(f"confidence is {str(c['confidence']).split(' (')[0]}, below {flt['confidence']}")
        if "transport" in flt:
            st, tw = transport_status(c.get("deal") or {}, tow)
            if (flt["transport"] == "can_tow" and st == "required") or (flt["transport"] == "required" and st == "can_tow"):
                why.append(tw)
        (out.append((c, why)) if why else kept.append(c))
    return kept, out


def render_filters(flt: dict, presets: dict, csrf: str, preset: str | None, warn: list[str], n_all: int, n_kept: int, found: bool) -> str:
    g = lambda k: e(flt.get(k, ""))  # noqa: E731
    sel = lambda k, opts: "".join(f"<option value='{e(v)}'{' selected' if str(flt.get(k, '')) == v else ''}>{e(t)}</option>" for v, t in opts)  # noqa: E731
    pre = "".join(f"<a class='chip{' on' if p == preset else ''}' href='/resale?preset={quote(p)}'>{e(p)}</a>" for p in presets) or "<span class='small mut'>none saved yet</span>"
    w = "".join(f"<p class='small bad'>{e(x)}</p>" for x in warn)
    ran = (f"<p class='flash'>Find Deals Now ran (DRY-RUN) on the {n_all} stored deal(s). No live source is connected, so nothing was fetched; "
           f"{n_kept} match your filters.</p>") if found else ""
    return (f"<div class='card' id='filters'>{ran}{w}<form method='get' action='/resale' class='filters'>"
            "<p><button class='b-YES' name='find' value='1' style='width:auto'>Find Deals Now</button> "
            f"<span class='small mut'>{n_kept} of {n_all} deals shown</span></p><div class='fgrid'>"
            f"<label>Category<input name='category' value=\"{g('category')}\" placeholder='towable, component_machine'></label>"
            f"<label>Trailer subtype<input name='subtype' value=\"{g('subtype')}\" placeholder='tilt deck, camper'></label>"
            f"<label>Max distance (mi)<input name='max_distance' inputmode='decimal' value=\"{g('max_distance')}\"></label>"
            f"<label>Min price ($)<input name='min_price' inputmode='decimal' value=\"{g('min_price')}\"></label>"
            f"<label>Max price ($)<input name='max_price' inputmode='decimal' value=\"{g('max_price')}\"></label>"
            f"<label>Condition<input name='condition' value=\"{g('condition')}\"></label>"
            f"<label>Title status<input name='title_status' value=\"{g('title_status')}\" placeholder='clean, bill of sale'></label>"
            f"<label>Sale type<select name='sale_type'>{sel('sale_type', [('', 'auction or fixed'), ('auction', 'auction'), ('fixed', 'fixed price')])}</select></label>"
            f"<label>Profit at least ($, optional; no default floor)<input name='profit_at_least' inputmode='decimal' value=\"{g('profit_at_least')}\"></label>"
            f"<label>Max days to cash<input name='max_days' inputmode='decimal' value=\"{g('max_days')}\"></label>"
            f"<label>Min confidence<select name='confidence'>{sel('confidence', [('', 'any'), ('LOW', 'low or better'), ('MEDIUM', 'medium or better'), ('HIGH', 'high only')])}</select></label>"
            f"<label>Transport<select name='transport'>{sel('transport', [('', 'all'), ('can_tow', 'can tow'), ('required', 'transport required')])}</select></label>"
            f"<label><input type='checkbox' name='closing_soon' value='1'{' checked' if flt.get('closing_soon') else ''}> Closing soon (48 h)</label></div>"
            "<p><button class='b-HOLD' style='width:auto'>Apply filters</button> <a href='/resale'>Clear</a></p></form>"
            f"<p class='small'><b>Saved presets:</b> {pre}</p>"
            f"<form method='post' action='/resale/preset' class='row'><input type='hidden' name='csrf' value='{e(csrf)}'>"
            + "".join(f"<input type='hidden' name='{k}' value=\"{e(v)}\">" for k, v in flt.items())
            + "<label class='grow'>Save these filters as<input name='name' maxlength='40' required></label><button class='b-HOLD' style='width:auto'>Save preset</button></form>"
              "<p class='small mut'>Presets live in this running UI (memory); they are not written to disk yet.</p></div>")


def render_filtered_out(out: list[tuple[dict, list[str]]]) -> str:
    if not out:
        return ""
    rows = "".join(f"<li><a href='#out-{e(c['id'])}'>{e(c['title'])}</a> ({e(c['action'])}): {e('; '.join(w))}</li>" for c, w in out)
    return (f"<details class='card' id='filtered-out'><summary><b>{len(out)} deal(s) hidden by your filters</b> (not deleted; clear the filters to see them)</summary>"
            f"<ul class='small'>{rows}</ul></details>")


# ---------------------------------------------------------------- milestones
def render_milestones() -> str:
    li = lambda xs: "".join(f"<li>{e(x)}</li>" for x in xs)  # noqa: E731
    now = ["Deal cards on stored / DEMO lots: BUY, WATCH or PASS from the economics engine (dry-run)", "Filters, saved presets (this session) and your tow limits",
           "Resale ledger intake to sold, with a receipt per step; simulated sales never count as earned", "My notes: add, edit, retract (needs the lane D store)"]
    blocked = ["Daily search: no scheduled job feeds this page yet", "Live auction connector: the auction adapters are fixture-only; a live fetch waits on an owner decision (packet Q3)"]
    future = ["Overnight negotiation: not built; live messaging is disabled until the owner decides on consent and contact rules (MICHAEL_DECISIONS #4)"]
    return ("<details class='card' id='milestones'><summary><b>What works now, what is blocked, what is future</b></summary><div class='grid'>"
            f"<div><h2>Usable now</h2><ul class='small'>{li(now)}</ul></div><div><h2>Blocked</h2><ul class='small'>{li(blocked)}</ul></div>"
            f"<div><h2>Future</h2><ul class='small'>{li(future)}</ul></div></div><p class='small mut'>No dates are promised: none have been committed.</p></details>")


# ---------------------------------------------------------------- the glanceable card
def _med(xs):
    xs = sorted(x for x in xs if isinstance(x, (int, float)))
    return None if not xs else xs[len(xs) // 2]


def _m(v):
    return "UNKNOWN" if v is None else f"${float(v):,.0f}"


def next_action(c: dict) -> str:
    if c["action"] == "BUY":
        return f"Get your approval, then bid no more than {_m(c['max_bid'])}. The system never bids."
    if c["action"] == "PASS":
        return "Skip it. Do not spend."
    if not c["computable"]:
        return "Fill in what is UNKNOWN: " + (c["unknowns"][0] if c["unknowns"] else "inputs") + "."
    return f"Watch it. Bid no more than {_m(c['max_bid'])} if you bid."


def render_deal(c: dict, proof_html: str, tow: dict) -> str:
    d = c.get("deal") or {}
    comps = d.get("comps") or []
    sold, ask = _med([x.get("sold_price") for x in comps]), _med([x.get("asking_price") for x in comps])
    st, why = transport_status(d, tow)
    tr = {"can_tow": "can tow", "required": "transport required", "unknown": "tow check UNKNOWN"}[st]
    tiles = [("Price now", _m(c["bid"])), ("Distance", f"{c['distance']} mi" if c["distance"] is not None else "UNKNOWN"),
             ("Condition", d.get("condition") or "UNKNOWN"), ("SOLD comps", f"{c['sold_comps']} · {_m(sold)}"), ("ASKING comps", f"{c['asking_comps']} · {_m(ask)}"),
             ("Expected net", _m(c["net"])), ("Profit / hour", _m(c["pph"])), ("Days to cash", "UNKNOWN" if c["days"] is None else f"{c['days']:g}"),
             ("Max bid", _m(c["max_bid"])), ("Transport", tr)]
    kp = "".join(f"<div class='kpi'><span class='small mut'>{e(k)}</span><b>{e(v)}</b></div>" for k, v in tiles)
    cls = "YES" if c["action"] == "BUY" else "NO" if c["action"] == "PASS" else "MAYBE"
    raw = json.dumps({k: v for k, v in c.items() if k != "deal"}, indent=1, default=str)
    return (f"<div class='card deal glance' id='deal-{e(c['id'])}'><div class='dealtop'>{render_gallery(d)}<div class='grow'>"
            f"<h2 class='dt'>{e(c['title'])} <span class='badge v-{cls}'>{e(c['action'])}</span>"
            f"{' <span class=lbl>DEMO</span>' if c['demo'] else ''}</h2><p class='small'>{render_link(d)} · {e(c['location'])}</p></div></div>"
            f"<div class='kpis'>{kp}</div><p class='next'><b>Next:</b> {e(next_action(c))}</p>{render_description(d)}"
            f"<details class='proof'><summary>View proof</summary>{proof_html}<h3>Raw JSON</h3><pre>{e(raw)}</pre></details></div>")
