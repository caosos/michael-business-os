"""F-46: live vs demo. Training (TRAIN-*) and fixture items are DEMO: hidden from the normal landing and queue, shown only
behind the DEMO switch, always with the banner, and never as a clickable link. Owner-supplied listings carry provenance.

Pure functions plus small renderers; no write path. Everything is DRY-RUN.
"""

from __future__ import annotations

import html
import json
from urllib.parse import urlsplit

from .deal_ui import classify_url, render_link

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

BANNER = ("<div class='flash err' id='demo-banner'><b>DEMO / TRAINING DATA, NOT REAL LISTINGS, DO NOT BUY.</b> "
          "These items are invented examples used to test the system. Nothing here can be bought, bid on or sold.</div>")
NO_REAL_LISTING = "No real listing, training example"
MAX_TEXT, MAX_PHOTOS = 5000, 8


def is_training(item: dict | None) -> bool:
    """TRAIN-* fixtures, or any item whose every source is a reserved/fixture host. An item with no verified source is not live."""
    if not item:
        return False
    srcs = item.get("sources") or []
    if "train-" in str(item.get("dedup_key") or "").lower() or str(item.get("item_id") or "").upper().startswith("TRAIN-"):
        return True
    for s in srcs:
        if str(s.get("source_listing_id") or s.get("listing_id") or "").upper().startswith("TRAIN-"):
            return True
    return False


def has_verified_source(item: dict | None) -> bool:
    """A real http(s) URL on a non-reserved host. Hosts are not checked against the allow-list here: that is for links only."""
    for s in (item or {}).get("sources") or []:
        if classify_url(s.get("url"), hosts=_any_host(s.get("url")))[0] == "live":
            return True
    return False


def _any_host(url):
    try:
        return [urlsplit(str(url)).hostname or ""]
    except ValueError:
        return []


def is_demo(item: dict | None) -> bool:
    return is_training(item) or not has_verified_source(item)


def hidden_note(n: int, demo: bool) -> str:
    if demo:
        return "<p class='small'><a href='/'>Hide demo / training data</a></p>"
    return (f"<p class='small mut'>Demo / training data is hidden ({n} item{'s' if n != 1 else ''}). "
            "<a href='/?demo=1'>Show demo data</a> (never real listings).</p>")


def split_queue(store, q: dict) -> tuple[dict, dict]:
    """-> (live queue, demo queue): demo rows are never in the live lists, so never under Needs your decision."""
    cache: dict = {}

    def demo_row(r):
        if r["item_id"] not in cache:
            cache[r["item_id"]] = is_demo(store.item(r["item_id"]))
        return cache[r["item_id"]]

    return ({k: [r for r in rows if not demo_row(r)] for k, rows in q.items()},
            {k: [r for r in rows if demo_row(r)] for k, rows in q.items()})


def render_demo_section(dq: dict, deals_html: str = "") -> str:
    """The DEMO switch's page section: banner, then training rows by title only (no decision buttons, no 'Needs you')."""
    rows = [r for v in dq.values() for r in v]
    items = "".join(f"<li><a href='/item/{e(r['item_id'])}'>{e(r['title'])}</a> <span class='lbl'>DEMO</span> "
                    f"<span class='small mut'>{e(r['status'])}</span></li>" for r in rows) or "<li class='mut'>No demo items.</li>"
    return (f"<div id='demo-section'>{BANNER}<h2>Demo / training examples ({len(rows)})</h2><ul>{items}</ul>{deals_html}"
            "<p class='small'><a href='/'>Hide demo / training data</a></p></div>")


def link_html(url) -> str:
    """The only way a listing URL becomes markup here: live -> link; fixture host -> plain text; otherwise no link."""
    return render_link({"url": url}) if url else "<span class='mut'>No verified live link</span>"


def collapse_unknown(rows: list[tuple[str, str]], is_unknown) -> str:
    """Known rows as a table; every UNKNOWN row folded into one line plus a collapsed list (no 15 UNKNOWN rows)."""
    known = [(k, v) for k, v in rows if not is_unknown(v)]
    unk = [k for k, v in rows if is_unknown(v)]
    out = "<table>" + "".join(f"<tr><td>{e(k)}</td><td>{v}</td></tr>" for k, v in known) + "</table>" if known else ""
    if unk:
        out += (f"<details><summary>{len(unk)} unknown field{'s' if len(unk) != 1 else ''} (not established)</summary>"
                f"<p class='small'>{e(', '.join(unk))}</p></details>")
    return out


RESEARCH_NEEDED = ("<p style='font-size:18px'><b class='bad'>RESEARCH NEEDED, DO NOT BUY YET.</b> "
                   "No sold-price evidence for this kind of item is on file, so the system cannot judge it.</p>")


# ---------------------------------------------------------------- owner-supplied intake
def parse_owner_listing(f: dict, author: str, now_iso: str) -> dict:
    """URL + photo URLs + pasted ad text from the owner. Stored as given (escaped on render), marked OWNER-SUPPLIED."""
    url = (f.get("url") or "").strip()
    kind, detail = classify_url(url) if url else ("none", "")
    if url and kind == "rejected":
        raise ValueError(f"Link not accepted: {detail}")
    photos = []
    for line in (f.get("photos") or "").splitlines()[:MAX_PHOTOS]:
        line = line.strip()
        if not line:
            continue
        pk, pd = classify_url(line)
        if pk == "rejected":
            raise ValueError(f"Photo link not accepted: {pd}")
        photos.append(line)
    text = (f.get("text") or "")[:MAX_TEXT]
    if not (url or photos or text.strip()):
        raise ValueError("Give at least a link, a photo link or the ad text.")
    return {"provenance": "OWNER-SUPPLIED", "supplied_by": author, "supplied_at": now_iso, "url": url or None,
            "url_kind": kind, "photos": photos, "text": text,
            "status": "RESEARCH NEEDED, DO NOT BUY YET", "sold_evidence": None}


def render_owner_listing(d: dict) -> str:
    imgs = "".join(f"<li>{link_html(p)}</li>" for p in d["photos"]) or "<li class='mut'>No photos supplied</li>"
    return (f"<div class='card'><h2>Your listing <span class='lbl'>OWNER-SUPPLIED</span></h2>"
            f"<p class='small mut'>Supplied by {e(d['supplied_by'])} at {e(d['supplied_at'])}. Not checked by the system; nothing fetched.</p>"
            f"{RESEARCH_NEEDED}<p>Original listing: {link_html(d['url'])}</p><ul>{imgs}</ul>"
            f"<details open><summary>Pasted ad text (verbatim)</summary><pre style='white-space:pre-wrap'>{e(d['text'])}</pre></details></div>")


def render_owner_form(csrf: str, flash: str = "") -> str:
    return (f"{flash}<div class='card'><h2>Add a listing I found</h2><form method='post' action='/owner-listing'>"
            f"<input type='hidden' name='csrf' value='{e(csrf)}'>"
            "<label>Link to the listing<input name='url' maxlength='500'></label>"
            "<label>Photo links, one per line<textarea name='photos' rows='3'></textarea></label>"
            "<label>Paste the ad text<textarea name='text' rows='6'></textarea></label>"
            "<button>Save (nothing is sent or bought)</button></form></div>")


# ---------------------------------------------------------------- GSA lots (B-25 / B-23 auction-lot shape)
def render_gsa_lot(lot: dict) -> str:
    """A GSA Auctions lot: original link and photo, source and as-of time. Asking/high bid is never sold evidence."""
    lid = lot.get("id") or lot.get("lot_id")
    link = lot.get("itemDescURL") or lot.get("url")
    img = lot.get("imageURL") or lot.get("image_url")
    pk = classify_url(img)[0] if img else "none"
    from . import landing_fix  # F-48: ppms.gov photos need a GSA login (401): tile, never a broken <img>
    photo = (landing_fix.photo_tile(img, link) if landing_fix.is_gsa_image(img) else
             f"<img src='{e(img)}' alt='Lot photo' loading='lazy' style='max-width:160px' referrerpolicy='no-referrer'>"
             if pk == "live" else "<span class='mut small'>Photo unavailable</span>")
    return (f"<div class='card'><h2>{e(lot.get('itemName') or lot.get('title') or lid)} <span class='lbl'>GSA</span></h2>{photo}"
            f"<p>Lot {e(lid)} · {e(lot.get('location') or 'UNKNOWN')} · high bid {e(lot.get('highBidAmount', 'UNKNOWN'))} "
            f"({e(lot.get('biddersCount', 'UNKNOWN'))} bidders) · ends {e(lot.get('aucEndDt') or 'UNKNOWN')}</p>"
            f"<p>Original listing: {link_html(link)}</p>"
            f"<p class='small mut'>Source GSA Auctions · as of {e(lot.get('as_of') or 'UNKNOWN')} · a bid is not a sold price; "
            "buyer premium and sold comps UNKNOWN.</p></div>")


def load_gsa_lots(path) -> list[dict]:
    try:
        d = json.loads(open(path, encoding="utf-8").read()) if path else []
    except (OSError, ValueError):
        return []
    return [x for x in (d.get("lots") if isinstance(d, dict) else d) or [] if isinstance(x, dict)]
