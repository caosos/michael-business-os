"""F-147 (implements A-61): 'My bids'. The owner says 'I bid on this' on any result card; the item moves out of the search lineup into a
compact window that stays visible under any filter, radius or source. Marking is OWNER-REPORTED: never inferred from Save, never a bid
placement, no source-account sign-in or sync. Records may be entered manually or imported from a listing card. Record path: the existing owner-local market prefs file (market_prefs.load/_store, key `bids`,
default var/market_prefs.json, MBOS_MARKET_PREFS_FILE); no second datastore. The optional max bid lives only there (var/ is not
committed) and is never shown outside this page. Current bid / bid count come from the source card WHEN it has them, else UNKNOWN."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from html import escape as e
from urllib.parse import unquote, urlsplit, urlunsplit

from . import market_autobids as mba
from . import market_prefs as mp

ACTS = ("bid", "add", "update", "unbid", "setmax")
STATUSES = ("watching", "bid placed", "winning", "outbid", "won", "lost", "closed")
HIBID_HOST = re.compile(r"^(?:(?P<auctioneer>[a-z0-9-]+)\.)?hibid\.com$", re.I)


def _clip(v, n=300) -> str:
    return str(v or "").strip()[:n]


def _num(v):
    try:
        x = float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None
    return x if 0 <= x < 1e9 else None


def _status(v, default="watching") -> str:
    s = _clip(v, 30).lower().replace("_", " ")
    if not s:
        return default
    if s not in STATUSES:
        raise ValueError("unknown bid status")
    return s


def _url(v) -> str:
    s = _clip(v)
    if s and not s.startswith(("http://", "https://")):
        raise ValueError("original link must start with http:// or https://")
    return s


def parse_watch_link(v) -> dict:
    """Normalize a pasted public auction link without fetching or signing in.

    HiBid lot URLs have enough stable information for a useful manual watch:
    the lot id, auctioneer subdomain and human-readable slug.  Bid state,
    price and closing time are deliberately not inferred from the URL.
    """
    raw = _url(v)
    if not raw:
        raise ValueError("original link is required")
    p = urlsplit(raw)
    host = (p.hostname or "").lower().rstrip(".")
    m = HIBID_HOST.fullmatch(host)
    lot = re.fullmatch(r"/lot/(\d{1,20})/([^/?#]+?)/?", p.path, re.I)
    if not (m and lot):
        return {"url": raw, "title": "", "source": "", "lot": ""}
    lot_id, slug = lot.groups()
    words = re.sub(r"[-_]+", " ", unquote(slug)).strip()
    title = " ".join("CountyLine" if word.lower() == "countyline" else
                     (word.upper() if word.lower() in {"pto", "utv", "atv"} else word.capitalize()) for word in words.split())
    auctioneer = m.group("auctioneer") or ""
    source = ("Wooley Auctioneers / HiBid" if auctioneer == "wooleyauctioneers" else
              (re.sub(r"[-_]+", " ", auctioneer).title() + " / HiBid" if auctioneer else "HiBid"))
    return {"url": urlunsplit((p.scheme.lower(), host, p.path.rstrip("/"), "", "")),
            "title": title or f"HiBid lot {lot_id}", "source": source, "lot": f"hibid:{host}:{lot_id}"}


def _manual_id(f: dict, now: str) -> str:
    raw = "\n".join((now, _clip(f.get("source")), _clip(f.get("title")), _clip(f.get("url"))))
    return "manual:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def act(action: str, f: dict, now: str) -> str:
    if action not in ACTS:
        raise ValueError("unknown bid action")
    lot = re.sub(r"[^A-Za-z0-9._:-]", "", f.get("lot") or "")[:200]
    link = parse_watch_link(f.get("url")) if action == "add" else None
    if action == "add":
        lot = link["lot"] or _manual_id(f, now)
    if not lot:
        raise ValueError("no lot given")
    d = mp.load()
    bids = d["bids"]
    mx = _num(f.get("max_bid")) if str(f.get("max_bid") or "").strip() else None
    if str(f.get("max_bid") or "").strip() and mx is None:
        raise ValueError("max bid must be a plain number")
    if action in ("bid", "add"):
        title = _clip(f.get("title") or (link or {}).get("title"), 120)
        source = _clip(f.get("source") or (link or {}).get("source"), 60)
        url = (link or {}).get("url") or _url(f.get("url"))
        if action == "add" and not title:
            raise ValueError("title is required")
        if action == "add" and not source:
            raise ValueError("source is required")
        if action == "add" and not url:
            raise ValueError("original link is required")
        closes, closes_at = _clip(f.get("closes"), 10), _clip(f.get("closes_at"), 40)
        current = _num(f.get("current_bid") if "current_bid" in f else f.get("bid"))
        for field in ("current_bid", "bid"):
            if field in f and str(f.get(field) or "").strip() and current is None:
                raise ValueError("current bid must be a plain number")
        rec = {"title": title, "source": source, "url": url, "closes": closes, "closes_at": closes_at,
               "bid": current, "bidders": _num(f.get("bidders")), "fetched_at": _clip(f.get("fetched_at"), 40),
               "marked_at": now, "max_bid": mx, "status": _status(f.get("status"), "bid placed" if action == "bid" else "watching"),
               "next_action": _clip(f.get("next_action"), 200), "origin": "IMPORTED" if action == "bid" else "MANUAL",
               "provenance": {"kind": "listing_snapshot" if action == "bid" else "owner_entry",
                              "observed_at": _clip(f.get("fetched_at"), 40) or now, "source_account_access": "NONE"}}
        if (closes or closes_at) and _end(rec) is None:
            raise ValueError("closing must be an ISO date or date-time")
        bids[lot] = rec
        msg = ("Added to My bids from the link. Nothing was placed or sent. "
               + ("Add the closing time to turn on countdown alerts." if _end(rec) is None else "Countdown alerts are active while DealSniffer is open."))
    elif action == "unbid":
        bids.pop(lot, None)
        if lot.startswith("auto:") and lot not in d["auto_stopped"]:      # F-152: hides an auto-detected item; the e-mail is never touched
            d["auto_stopped"].append(lot)
        msg = "Stopped tracking. It can appear in search results again if it matches your filters."
    elif action == "setmax":
        if lot not in bids:
            raise ValueError("that item is not in My bids")
        bids[lot]["max_bid"] = mx
        msg = "Max bid saved on this computer only." if mx is not None else "Max bid cleared."
    else:
        if lot not in bids:
            raise ValueError("that item is not in My bids")
        r = bids[lot]
        current = _num(f.get("current_bid")) if str(f.get("current_bid") or "").strip() else None
        if str(f.get("current_bid") or "").strip() and current is None:
            raise ValueError("current bid must be a plain number")
        closes_at = _clip(f.get("closes_at"), 40)
        candidate = {**r, "closes_at": closes_at, "closes": ""}
        if closes_at and _end(candidate) is None:
            raise ValueError("closing must be an ISO date or date-time")
        r.update({"status": _status(f.get("status")), "bid": current, "max_bid": mx, "closes_at": closes_at,
                  "closes": "", "next_action": _clip(f.get("next_action"), 200), "updated_at": now})
        msg = "Bid watch updated. Nothing was placed and no source account was accessed."
    mp._store(d)
    return msg


def exclude(cards: list[dict], d: dict, auto_urls: frozenset = frozenset()) -> tuple[list[dict], int]:
    keep = [c for c in cards if c["id"] not in d["bids"] and mba.norm_url(c.get("url")) not in auto_urls]
    return keep, len(cards) - len(keep)


def _end(r: dict):
    s = r.get("closes_at") or r.get("closes") or ""
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00")) if "T" in s else datetime.combine(date.fromisoformat(s[:10]), time(23, 59, 59), ZoneInfo("America/Chicago"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def closing(r: dict, now: datetime) -> str:
    """F-154 (display only): 'closing within 2 h' (0 < left <= 2 h) else 'closing today' (the close falls on today's America/Chicago date, still ahead). '' otherwise or when the close is UNKNOWN."""
    t = _end(r)
    if t is None or t <= now:
        return ""
    if t - now <= timedelta(hours=2):
        return "closing within 2 h"
    tz = ZoneInfo("America/Chicago")
    return "closing today" if t.astimezone(tz).date() == now.astimezone(tz).date() else ""


def badge(r: dict, now: datetime) -> str:
    b = closing(r, now)
    return f" <span class='badge' data-closing='{b}'>{b.upper()}</span>" if b else ""


def _rank(r: dict, now: datetime) -> int:
    return {"closing within 2 h": 0, "closing today": 1}.get(closing(r, now), 2)


def countdown(r: dict, now: datetime) -> str:
    t = _end(r)
    if t is None:
        return "closes UNKNOWN"
    s = int((t - now).total_seconds())
    if s <= 0:
        return f"closed (was {e(r.get('closes_at') or r['closes'])})"
    dh = f"{s // 86400}d {s % 86400 // 3600}h" if s >= 86400 else f"{s // 3600}h {s % 3600 // 60}m"
    return f"closes in {dh} ({e((r.get('closes_at') or r['closes'])[:16])}{'' if r.get('closes_at') else ', date only'})"


def nav_summary(now: datetime) -> dict:
    """Small account-local summary for the customer navigation bar."""
    rows = list(mp.load().get("bids", {}).values())
    active = [r for r in rows if r.get("status") not in ("won", "lost", "closed")]
    urgent = 0
    for r in active:
        end = _end(r)
        if r.get("status") == "outbid" or (end and timedelta(0) < end - now <= timedelta(minutes=15)):
            urgent += 1
    return {"active": len(active), "urgent": urgent}


def window(d: dict, cards: list[dict], now: datetime, tok, auto: tuple = ((), ""), *, expanded: bool = False,
           return_to: str = "") -> str:
    """Compact window, closing-soonest first (unknown close last). Live source data (when this source was loaded) wins over the marking-time snapshot."""
    live = {c["id"]: c for c in cards}
    rows = []
    for i, r in d["bids"].items():
        c = live.get(i)
        r = {**r, **({"bid": c["bid"], "bidders": c.get("bidders"), "fetched_at": c.get("fetched_at") or r.get("fetched_at", "")} if c and c.get("kind") != "auction event" else {})}
        rows.append((_end(r) or datetime.max.replace(tzinfo=timezone.utc), i, r))
    rows.sort(key=lambda t: (_rank(t[2], now), t[0], t[1]))
    li = []
    mixed = sorted([(k, i, None, h, rk) for k, i, h, rk in mba.rows(auto[0], now, tok, countdown, _end, badge, _rank, return_to)] + [(k, i, r, None, _rank(r, now)) for k, i, r in rows], key=lambda t: (t[4], t[0], t[1]))
    for _, i, r, html, _rk in mixed:
        if html:
            li.append(html)
            continue
        bid = f"${r['bid']:,.0f}" if r.get("bid") is not None else "UNKNOWN"
        cnt = f"{r['bidders']:g}" if r.get("bidders") is not None else "UNKNOWN"
        link = f"<a href='{e(r['url'])}' target='_blank' rel='noopener noreferrer'>original listing</a>" if r.get("url", "").startswith(("http://", "https://")) else "no link"
        back = f"<input type='hidden' name='return_to' value='{e(return_to)}'>" if return_to else ""
        hid = f"{tok()}{back}<input type='hidden' name='lot' value='{e(i)}'>"
        mx = f"${r['max_bid']:,.0f}" if r.get("max_bid") is not None else "UNKNOWN"
        status = r.get("status") if r.get("status") in STATUSES else "bid placed"
        next_action = _clip(r.get("next_action"), 200) or "Review the original listing before its close."
        origin = r.get("origin") if r.get("origin") in ("MANUAL", "IMPORTED") else "MANUAL"
        provenance = r.get("provenance") if isinstance(r.get("provenance"), dict) else {}
        proof = "listing feed snapshot; no source-account access" if provenance.get("kind") == "listing_snapshot" else "entered by you; no source-account access"
        opts = "".join(f"<option value='{e(s)}'{' selected' if s == status else ''}>{e(s)}</option>" for s in STATUSES)
        end = _end(r)
        end_attr = end.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z") if end else ""
        li.append(f"<li class='bid-row' data-bid='{e(i)}' data-origin='{origin}' data-status='{e(status)}' data-end='{e(end_attr)}'><span class='bid-title'><b>{e(r['title'] or i)}</b> "
                  f"<span class='badge bid-origin'>{origin}</span></span><br><span class='mut'>{e(r['source'] or 'source UNKNOWN')} · {origin} · {e(proof)}</span><br>"
                  f"status <b>{e(status)}</b> · <span class='bid-countdown'>{countdown(r, now)}</span>{badge(r, now)}<br>"
                  f"current bid {bid} · your max: {mx} · bids {cnt} · as of {e(r.get('fetched_at') or r.get('updated_at') or r.get('marked_at') or 'marking time')[:16]} · {link}<br>"
                  f"<span class='bid-alert' role='status' aria-live='polite'></span>next action: {e(next_action)}<br>"
                  f"<form method='post' action='/market/bid' style='display:inline'>{hid}<button name='act' value='unbid'>Stop tracking</button></form> "
                  f"<details class='small bid-update'><summary>Update status, amounts, closing or next action</summary><form method='post' action='/market/bid'>{hid}"
                  f"<label>Status <select name='status'>{opts}</select></label> "
                  f"<label>Current bid $ <input name='current_bid' size='7' inputmode='decimal' value='{'' if r.get('bid') is None else r['bid']:}'></label> "
                  f"<label>Your max $ <input name='max_bid' size='7' inputmode='decimal' value='{'' if r.get('max_bid') is None else r['max_bid']:}'></label> "
                  f"<label>Closing <input name='closes_at' size='22' value='{e(r.get('closes_at') or r.get('closes') or '')}' placeholder='2026-10-15T19:00:00-05:00'></label> "
                  f"<label>Next action <input name='next_action' size='32' maxlength='200' value='{e(r.get('next_action') or '')}'></label>"
                  "<button name='act' value='update'>Update</button></form></details></li>")
    body = f"<ul style='padding-left:16px;margin:4px 0'>{''.join(li)}</ul>" if li else "<p class='small mut'>Nothing tracked. Use 'I bid on this' on a card after you place a bid yourself.</p>"
    back = f"<input type='hidden' name='return_to' value='{e(return_to)}'>" if return_to else ""
    add = (f"<details class='small' id='add-bid-watch'{' open' if expanded and not li else ''}><summary><b>Add a bid to watch</b></summary><p class='mut'>Paste a HiBid lot link and DealSniffer fills in its title and source without signing in or fetching the site. Add the close time when known so the on-page countdown can alert you.</p>"
           f"<form method='post' action='/market/bid' class='bid-form'>{tok()}{back}<label class='bid-link'>Auction link <input name='url' type='url' maxlength='300' required placeholder='Paste the original lot link'></label> "
           "<details class='bid-more'><summary>Optional details</summary><label>Listing title <input name='title' maxlength='120'></label> "
           "<label>Source <input name='source' maxlength='60'></label> "
           "<label>Status <select name='status'>" + "".join(f"<option value='{e(s)}'>{e(s)}</option>" for s in STATUSES) + "</select></label> "
           "<label>Current bid $ <input name='current_bid' size='7' inputmode='decimal'></label> <label>Your max $ <input name='max_bid' size='7' inputmode='decimal'></label> "
           "<label>Closing <input name='closes_at' size='22' placeholder='2026-10-15T19:00:00-05:00'></label> <label>Next action <input name='next_action' maxlength='200'></label> "
           "</details><button name='act' value='add'>Watch this auction</button></form></details>")
    state = "open" if expanded else ""
    hint = "" if expanded else " <span class='mut'>(collapsed; click to open)</span>"
    return (f"<details class='card small' id='my-bids' {state}><summary><b>My bids ({len(li)})</b>{hint}</summary><p class='mut' style='margin:2px 0'>Manual and imported bid watches stay with this account only. We do not place bids or access source accounts; "
            f"email-alert rows appear only when a mailbox feed is connected.</p>{auto[1]}{add}{body}</details>")


def page_body(app, now: datetime) -> str:
    """Dedicated, usable My Bids page without refreshing or widening the listing feed."""
    d = mp.load()
    auto = mba.load(now, d)
    tok = lambda: (f"<input type='hidden' name='csrf' value='{app.csrf}'>"
                   f"<input type='hidden' name='nonce' value='{__import__('secrets').token_hex(8)}'>")  # noqa: E731
    manual = sum(1 for r in d["bids"].values() if r.get("origin") == "MANUAL")
    imported = sum(1 for r in d["bids"].values() if r.get("origin") == "IMPORTED") + len(auto[0])
    email = 0  # the only reader currently available is explicitly fixture/import mode, never a live mailbox
    return ("<style>.bid-head{display:flex;gap:10px;align-items:center;flex-wrap:wrap}.bid-kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px;margin:10px 0}"
            ".bid-kpi,.bid-row{border:1px solid var(--line);border-radius:8px;padding:10px}.bid-row{margin:8px 0;list-style:none}.bid-row.bid-urgent{border:3px solid #c0222c;box-shadow:0 0 0 4px rgba(192,34,44,.13)}.bid-title{font-size:16px}.bid-origin{margin-left:5px}.bid-alert:not(:empty){display:block;background:#c0222c;color:#fff;font-weight:800;padding:8px;margin:6px 0;border-radius:6px}.bid-form,.bid-update form{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:6px 12px}.bid-link{grid-column:1/-1}.bid-more{grid-column:1/-1}.bid-form button,.bid-update button{align-self:end}@media(prefers-reduced-motion:no-preference){.bid-urgent{animation:bidpulse 1s ease-in-out infinite alternate}@keyframes bidpulse{to{filter:brightness(1.18)}}}</style>"
            "<div class='bid-head'><h1 class='pagehead'>My Bids</h1><a href='/market'>Back to listings</a></div>"
            "<p>Track bids you placed on the original source. DealSniffer watches the facts you record or import; it never logs into a source or places a bid.</p>"
            f"<div class='bid-kpis'><div class='bid-kpi'><b>{manual}</b><br><span class='badge'>MANUAL</span><br><span class='small mut'>entered by you</span></div>"
            f"<div class='bid-kpi'><b>{imported}</b><br><span class='badge'>IMPORTED</span><br><span class='small mut'>listing snapshot</span></div>"
            f"<div class='bid-kpi'><b>{email}</b><br><span class='badge'>EMAIL CONNECTED — NOT ACTIVE</span><br><span class='small mut'>requires a proven mailbox connection</span></div></div>"
            + window(d, [], now, tok, auto, expanded=True, return_to="/market/bids")
            + "<script src='/static/market_bids.js' defer></script>")


def button(c: dict, tok) -> str:
    f = lambda k, v: f"<input type='hidden' name='{k}' value='{e(str(v if v is not None else ''))}'>"  # noqa: E731
    hid = "".join(f(k, v) for k, v in (("lot", c["id"]), ("title", c["title"]), ("source", c.get("source")), ("url", c.get("url")), ("closes", c.get("closes")),
                                       ("closes_at", c.get("closes_at")), ("bid", c.get("bid")), ("bidders", c.get("bidders")), ("fetched_at", c.get("fetched_at"))))
    return (f"<form method='post' action='/market/bid' class='mk-pref' data-bidform>{tok()}{hid}<input name='max_bid' size='5' inputmode='decimal' aria-label='Your max bid (optional)' "
            "placeholder='my max $' title='Optional. Stays on this computer.'><button name='act' value='bid' title='You already placed this bid yourself; track it here'>I bid on this</button></form>")
