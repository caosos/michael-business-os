"""F-160: the listing detail page /market/item/<source>/<id> (GSA-style layout) for every Marketplace card, built ONLY from the cached record already on this computer.
No fetch happens here. 'Bid on the original site' is a link for the human; nothing is ever bid, sent or bought from this page. Unknown fields are labelled UNKNOWN."""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from html import escape as e
from html.parser import HTMLParser
from urllib.parse import quote, urlsplit

from . import landing_fix
from . import market_bids as mb
from . import market_finds as mf
from . import market_prefs as mp
from . import market_search as ms
from . import market_sources as msrc
from . import market_suggest as msug
from .deal_ui import classify_url

OSM = "https://www.openstreetmap.org/search?query="
SIMILAR_N = 8


def slug(c: dict) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(c.get("source") or "source").lower()).strip("-") or "source"


def href(c: dict) -> str:
    return f"/market/item/{slug(c)}/{quote(str(c['id']), safe='')}"


def search_query() -> dict:
    """The owner's current search scope, resolved exactly as the Marketplace page does (last remembered filters, else their home)."""
    from . import market_browse as mbr, market_routes as mr
    return ms.parse_query(mbr.with_home(mp.recall(mr.FILTER_KEYS)))


def all_cards(now: datetime, gsa_path: str | None = None, origin=None) -> list[dict]:
    cards = list(ms.load_source("all", now, origin, gsa_path)["cards"])
    cards += [mf.card(r, None) for r in mf.load().values() if not r.get("deleted")]
    return cards


def in_scope(o: dict, q: dict) -> bool:
    """Inside the owner's current location mode: By State -> a known matching state (radius too when ticked); By Distance -> a KNOWN distance within the radius."""
    by_state = q.get("loc_mode") == "state"
    if by_state and o.get("state") not in (q.get("states") or []):
        return False
    if q["radius"] is not None and (not by_state or q.get("also_radius")):
        return o.get("distance") is not None and o["distance"] <= q["radius"]
    return True


def place_line(c: dict) -> str:
    """'City, ST ZIP · N mi' as the search card shows it; 'distance unknown' only when the distance truly is."""
    where = " ".join(x for x in (c.get("city"), c.get("zip")) if x) or "town UNKNOWN"
    return where + (f" · {round(c['distance'], 1):g} mi" if c.get("distance") is not None else " · distance unknown")


def raw_gsa(card_id: str, path: str | None = None) -> dict | None:
    """The cached GSA record for this lot (read from the local cache file only), or None."""
    try:
        d = json.loads(open(path or ms.cache_path(), encoding="utf-8").read())
    except (OSError, ValueError):
        return None
    rows = d.get("Results") or d.get("records") or [] if isinstance(d, dict) else d
    for r in rows if isinstance(rows, list) else []:
        if isinstance(r, dict) and f"{r.get('saleNo')}-{r.get('lotNo')}" == card_id:
            return r
    return None


class _Clean(HTMLParser):
    """lotInfo HTML -> a safe subset (headings, paragraphs, lists, bold); attributes and every other tag are dropped, text is escaped."""
    OK = {"h4": "h4", "h3": "h4", "p": "p", "ul": "ul", "ol": "ul", "li": "li", "strong": "b", "b": "b", "br": "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.OK:
            self.out.append(f"<{self.OK[tag]}>")

    def handle_endtag(self, tag):
        if tag in self.OK and tag != "br":
            self.out.append(f"</{self.OK[tag]}>")

    def handle_data(self, data):
        self.out.append(e(data))


def clean_html(raw) -> str:
    p = _Clean()
    try:
        p.feed(str(raw or ""))
        p.close()
    except Exception:  # noqa: BLE001  malformed seller HTML never breaks the page
        return e(re.sub(r"<[^>]+>", " ", str(raw or "")))
    return "".join(p.out)


def sections(raw) -> dict[str, str]:
    """lotInfo -> {heading: text} split on <h4> (e.g. 'Condition & Markings', 'Inspection and Removal'); '' key = text before the first heading."""
    parts = re.split(r"(?is)<h4[^>]*>(.*?)</h4>", str(raw or ""))
    out = {"": parts[0]}
    for i in range(1, len(parts) - 1, 2):
        out[re.sub(r"<[^>]+>", "", parts[i]).strip()] = parts[i + 1]
    return out


def _txt(v) -> str | None:
    s = " ".join(str(v).split()) if v is not None else ""
    return s if s and s.lower() != "null" else None


def kv(label: str, v, note: str = "") -> str:
    val = e(str(v)) if v not in (None, "") else "<span class='lbl'>UNKNOWN</span>"
    return f"<tr><th>{e(label)}</th><td>{val}{note}</td></tr>"


def status_of(c: dict, raw: dict | None, now: datetime) -> str:
    s = _txt((raw or {}).get("auctionStatus"))
    if s:
        return s
    t = mb._end(c)
    if t is None:
        return "UNKNOWN"
    return "Closed" if t <= now else "Active"


def countdown_parts(c: dict, now: datetime) -> tuple[int, str] | None:
    t = mb._end(c)
    if t is None:
        return None
    s = max(0, int((t - now).total_seconds()))
    d, r = divmod(s, 86400)
    h, r = divmod(r, 3600)
    m, sec = divmod(r, 60)
    return s, f"{d} days {h} hrs {m} min {sec} sec"


def _live_link(url, text: str, *, exact_host: bool = False) -> str:
    hosts = None
    if exact_host:
        try:
            hosts = [urlsplit(url or "").hostname or ""]
        except ValueError:
            hosts = []
    if url and classify_url(url, hosts=hosts)[0] == "live":
        return f"<a class='mk-view' href='{e(url)}' rel='noopener noreferrer nofollow' target='_blank'>{e(text)}</a>"
    return "<span class='mut small'>No verified live link for the original listing</span>"


def _address(c: dict, raw: dict | None) -> str:
    r = raw or {}
    line = ", ".join(x for x in (_txt(r.get("propertyAddr1")), _txt(r.get("propertyAddr2")), _txt(r.get("propertyAddr3")), _txt(r.get("propertyCity")),
                                 " ".join(x for x in (_txt(r.get("propertyState")), _txt(r.get("propertyZip"))) if x)) if x)
    return line or _txt(c.get("address")) or _txt(c.get("city")) or ""


def _photos(c: dict) -> str | None:
    img = c.get("image")
    if img and landing_fix.is_gsa_image(img):
        main = landing_fix.photo_tile(img, c.get("url"))
        thumbs = ""
    else:
        try:
            image_hosts = [urlsplit(img or "").hostname or ""]
        except ValueError:
            image_hosts = []
    if img and not landing_fix.is_gsa_image(img) and classify_url(img, hosts=image_hosts)[0] == "live":
        main = f"<a href='{e(img)}' target='_blank' rel='noopener noreferrer nofollow' title='Full screen'><img src='{e(img)}' alt='Listing photo' referrerpolicy='no-referrer' style='max-width:100%'></a>"
        thumbs = f"<div class='small'><a href='{e(img)}' target='_blank' rel='noopener noreferrer nofollow'><img src='{e(img)}' alt='Thumbnail 1' width='60' referrerpolicy='no-referrer'></a> <a href='{e(img)}' target='_blank' rel='noopener noreferrer nofollow'>Full screen</a></div>"
    elif not (img and landing_fix.is_gsa_image(img)):
        return None
    return f"<div class='dt-photos'>{main}{thumbs}</div>"


def _similar(c: dict, pool: list[dict], now: datetime, q: dict | None = None) -> str:
    cat = c.get("category")
    rows = []
    if cat:
        for o in pool:
            if o is c or (o["id"] == c["id"] and slug(o) == slug(c)) or o.get("category") != cat or o.get("event"):
                continue
            if not ms.cat_ok(o, ms.DEFAULT_CATS):         # Land / Real Estate is off by default here too
                continue
            if q is not None and not in_scope(o, q):
                continue
            rows.append(o)
        rows.sort(key=lambda o: (o["distance"] is None, o["distance"] if o["distance"] is not None else 0, o.get("closes") or "9999", o["title"]))
    if not rows:
        return "<h2>Similar listings</h2><p class='small mut'>None in the cached lists with the same category" + (" (category UNKNOWN for this listing)" if not cat else "") + ".</p>"
    li = "".join(f"<li><a href='{e(href(o))}'>{e(o['title'])}</a> <span class='small mut'>{e(o['source'])} · "
                 f"{e(o['city'] or 'town UNKNOWN')} · " + (f"{round(o['distance'], 1):g} mi" if o["distance"] is not None else "distance unknown")
                 + f" · {'$' + format(o['bid'], ',.0f') + ' bid' if o['bid'] is not None else 'no bids yet'}</span></li>" for o in rows[:SIMILAR_N])
    return f"<h2>Similar listings</h2><p class='small mut'>Same category ({e(str(cat))}), nearest first.</p><ul id='similar'>{li}</ul>"


def _helpers(c: dict, prefs: dict, tok, asof: str) -> str:
    if c.get("event") or c.get("fixture"):
        return "<h2>Our decision helpers</h2><p class='small mut'>Not scored: an auction event or an alert fixture has no price to score.</p>"
    sg = msug.suggest([c], prefs, asof)
    row = next((r for k in ("ranked", "outside", "research") for r in sg[k] if r["card"]["id"] == c["id"]), None)
    if row is None:
        why = "Not scored (pallet / non-lot listing)."
    elif "unknown" in row:
        why = "Needs research, the engine cannot score it yet: " + "; ".join(row["unknown"])
    elif row in sg["outside"]:
        why = "Outside your rules: " + "; ".join(row["why_not"])
    else:
        why = f"Ranked by the engine. Walk-away max bid {msug._m(row.get('max_bid'))} (display only; this page bids nothing)."
    tgt = (prefs.get("resale_targets") or {}).get(c["id"])
    return (f"<h2>Our decision helpers</h2><p id='sg-reason'><b>Suggestions:</b> {e(why)}</p><p>{msug.resale_form(c, tgt, tok)}</p>"
            f"<div>{mb.button(c, tok)}</div>")


def event_page(c: dict, now: datetime) -> str:
    plat = c.get("platform_url") or c.get("hibid_url")
    prem = f"{c['buyer_premium_pct']:g}%" if c.get("buyer_premium_pct") is not None else None
    tags = ", ".join(c.get("tags") or []) or None
    rows = "".join((kv("Begins", c.get("begins_local") or msrc.local_when(c.get("begins_at"))), kv("Ends / closes", c.get("closes_local") or msrc.local_when(c.get("closes_at") or c.get("closes"))),
                    kv("Address", c.get("address") or c.get("city")), kv("Auctioneer", c.get("auctioneer")), kv("Buyer premium", prem), kv("Categories", tags)))
    ar = c.get("address") or c.get("city")
    osm = f" <a href='{OSM}{quote(ar)}' target='_blank' rel='noopener noreferrer'>OpenStreetMap</a>" if ar else ""
    return (f"<table>{rows}</table>{osm}<p id='lots-na'><b>Lots not available:</b> see the auctioneer. Lot-level data (lot numbers, current bids, bid counts) is only on the bidding platform, which this page does not read.</p>"
            f"<p>{_live_link(c.get('url'), 'Auctioneer page')} {_live_link(plat, 'View and bid on ' + (c.get('platform') or 'the platform')) if plat else ''}</p>")


def local_deal_page(c: dict, now: datetime) -> str:
    """Relevant facts for reviewed local offers; auction-only bid fields do not apply."""
    price = c.get("price")
    unit = f" {c['unit']}" if c.get("unit") else ""
    regular = c.get("regular_price")
    rows = "".join((
        kv("Status", status_of(c, None, now)),
        kv("Deal price", f"${price:,.2f}{unit}" if price is not None else None),
        kv("Regular price", f"${regular:,.2f}{unit}" if regular is not None else None),
        kv("Business", c.get("business_name")),
        kv("Availability", c.get("availability")),
        kv("Location", place_line(c)),
        kv("Expires", c.get("closes_at") or c.get("closes")),
        kv("Observed", c.get("posted")),
        kv("Imported", c.get("fetched_at")),
    ))
    terms = f"<h2>Terms</h2><p>{e(c['terms'])}</p>" if c.get("terms") else ""
    method = (c.get("provenance") or {}).get("method") or "UNKNOWN"
    provenance = (f"<p class='small mut'><b>Provenance:</b> {e(method)} · state IMPORTED, not a live vendor connection. "
                  "The offer is hidden automatically after its stated expiration.</p>")
    facts = (f"<table id='dt-status'>{rows}</table><h2>Offer</h2><p>{e(c.get('description') or '')}</p>{terms}"
             f"<p>{_live_link(c.get('url'), 'Open original offer', exact_host=True)}</p>{provenance}")
    photo = _photos(c)
    return f"<div class='dt-grid'>{photo or ''}<div>{facts}</div></div>"


def render(c: dict, raw: dict | None, pool: list[dict], prefs: dict, now: datetime, tok, q: dict | None = None) -> str:
    kind = "Auction event" if c.get("event") else "Local deal" if c.get("source_key") == "local_deals" else "Listing"
    stale = " <b class='bad'>STALE: cached data may be out of date</b>" if c.get("stale") else ""
    head = (f"<p class='small'><a href='/market'>&larr; Back to Marketplace</a></p><h1>{e(c['title'])}</h1>"
            f"<p class='small mut'>{e(c['source'])} · {kind} · cached {e(str(c.get('fetched_at') or 'UNKNOWN'))}{stale} · DRY-RUN, nothing is bid, sent or bought here</p>")
    if c.get("event"):
        return head + event_page(c, now) + _similar(c, pool, now, q)
    if c.get("source_key") == "local_deals":
        return head + local_deal_page(c, now) + _similar(c, pool, now, q)
    L = c.get("labels") or ms.auction_labels({})
    st = status_of(c, raw, now)
    cd = countdown_parts(c, now)
    end = mb._end(c)
    cd_html = (f"<span id='dt-cd' data-end='{e(end.astimezone(timezone.utc).isoformat())}'>{e(cd[1])}</span>" + ("" if c.get("closes_at") else " <span class='small mut'>(date-only close, time UNKNOWN: counted to 11:59 PM Central)</span>")) if cd else "<span class='lbl'>UNKNOWN</span>"
    bd = c.get("bidders")
    inc = ms._amt((raw or {}).get("aucIncrement"))
    nxt = f"ESTIMATED ${L['est_next_bid']:,.2f}" if L.get("est_next_bid") is not None else None
    fixed_price = c.get("price") if c.get("price_type") == "fixed" else None
    price_value = (f"${fixed_price:,.2f}" + (f" {c['unit']}" if c.get("unit") else "")) if fixed_price is not None else (f"${c['bid']:,.2f}" if c["bid"] is not None else None)
    price_label = "Deal price" if c.get("source_key") == "local_deals" else "Price" if fixed_price is not None else "Current bid"
    no_price_note = "" if price_value is not None or fixed_price is not None else " <span class='small mut'>(no bids yet)</span>"
    box = ("<table id='dt-status'>" + kv("Status", st) + kv(price_label, price_value, no_price_note)
           + f"<tr><th>Time left</th><td>{cd_html}</td></tr>" + kv("Next minimum bid", nxt, " <span class='small mut'>(cached bid + increment; live minimum unverified)</span>" if nxt else " <span class='small mut'>" + e(L.get("next_min_text", "")) + "</span>")
           + kv("Bid increment", f"${inc:,.2f}" if inc is not None else None) + kv("Bidders", bd if isinstance(bd, int) and not isinstance(bd, bool) else None)
           + kv("Location", place_line(c)) + kv("Reserve", L.get("reserve_text")) + kv("Closes", c.get("closes")) + kv("Opened", c.get("posted")) + "</table>")
    r = raw or {}
    sec = sections(r.get("lotInfo"))
    cond = next((v for k, v in sec.items() if k.lower().startswith("condition")), None)
    insp = next((v for k, v in sec.items() if k.lower().startswith("inspection")), None)
    ins_txt = _txt(r.get("instruction"))
    pay = re.search(r"pay\s*by\W+([\d/.\-]+)", ins_txt or "", re.I)
    rem = re.search(r"remove\s*by\W+([\d/.\-]+)", ins_txt or "", re.I)
    desc = clean_html(r.get("lotInfo")) if r.get("lotInfo") else (f"<p>{e(c['description'])}</p>" if c.get("description") else "<p class='mut'>No description from the seller</p>")
    addr = _address(c, raw)
    osm = f" <a href='{OSM}{quote(addr)}' target='_blank' rel='noopener noreferrer'>View on OpenStreetMap</a>" if addr else ""
    spec = "<table>" + kv("Sale / lot", f"{r.get('saleNo')} / {r.get('lotNo')}" if r.get("saleNo") else c["id"]) + kv("Category", c.get("category")) + kv("Agency", _txt(r.get("agencyName"))) + "</table>"
    cond_html = f"<div id='dt-cond'>{clean_html(cond)}</div>" if cond else f"<p id='dt-cond'>Condition (seller says): {e(c['condition']) if c.get('condition') else '<span class=lbl>UNKNOWN</span>'}</p>"
    insp_html = (f"<div>{clean_html(insp)}</div>" if insp else "") + (f"<p><b>Instruction (as published):</b> {e(ins_txt)}</p>" if ins_txt else "")
    if not insp_html:
        insp_html = "<p><span class='lbl'>UNKNOWN</span> no inspection or removal text in the cached record</p>"
    dates = "<table>" + kv("Pay by", pay.group(1) if pay else None) + kv("Remove by", rem.group(1) if rem else None) + "</table>"
    cust = "<table>" + kv("Custodian / sales office", _txt(r.get("locationOrg"))) + kv("Office address", ", ".join(x for x in (_txt(r.get("locationStAddr")), _txt(r.get("locationCity")), _txt(r.get("locationST")), _txt(r.get("locationZip"))) if x) or None) \
        + kv("Sale location", _txt(r.get("saleLocation"))) + kv("Contracting officer (as published)", _txt(r.get("contractOfficer"))) + kv("Contact e-mail (as published)", _txt(r.get("coEmail"))) \
        + kv("Contact phone (as published)", _txt(r.get("coPhone"))) + "</table>"
    ph = _photos(c)
    return (head + f"<div class='dt-grid'>{ph or ''}<div>{box}<p>{_live_link(c.get('url') or r.get('itemDescURL'), 'Bid on the original site')}</p>"
            "<p class='small mut'>Bidding happens only on the original site. This page never places a bid.</p></div></div>"
            f"<h2>Description</h2><div id='dt-desc'>{desc}</div>{spec}<h2>Condition</h2>{cond_html}<h2>Inspection and removal</h2>{insp_html}{dates}"
            f"<h2>Property address</h2><p id='dt-addr'>{e(addr) if addr else '<span class=lbl>UNKNOWN</span>'}{osm}</p><h2>Custodian and contacts</h2>{cust}"
            + _helpers(c, prefs, tok, str(c.get("fetched_at") or now.isoformat())) + _similar(c, pool, now, q))


CSS = ("<style>.dt-grid{display:flex;gap:16px;flex-wrap:wrap}.dt-grid>*{flex:1 1 300px;min-width:0}.dt-photos img{max-width:100%}"
       "#dt-desc,#dt-cond{overflow-wrap:anywhere}main table th{text-align:left;padding-right:12px;vertical-align:top}"
       "@media(max-width:700px){.dt-grid{flex-direction:column}header{padding:6px 12px}header nav{display:flex;flex-wrap:nowrap;overflow-x:auto;white-space:nowrap;max-width:100%}main h1{font-size:20px;margin:6px 0}main>p{margin:4px 0}}</style>")


def page_body(app, source: str, item: str, now: datetime) -> str | None:
    """-> the page HTML, or None when no cached listing matches (-> 404)."""
    gsa = os.environ.get("MBOS_GSA_CACHE") or None
    q = search_query()
    pool = all_cards(now, gsa, ms._origin(q["base"]))
    c = next((x for x in pool if x["id"] == item and slug(x) == source), None)
    if c is None:
        return None
    raw = raw_gsa(item, gsa) if c.get("source") == "GSA Auctions" else None
    tok = lambda: f"<input type='hidden' name='csrf' value='{app.csrf}'><input type='hidden' name='nonce' value='{__import__('secrets').token_hex(8)}'>"  # noqa: E731
    return CSS + render(c, raw, pool, mp.load(), now, tok, q) + "<script src='/static/market_detail.js'></script>"
