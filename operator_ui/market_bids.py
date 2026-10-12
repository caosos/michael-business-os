"""F-147 (implements A-61): 'My bids'. The owner says 'I bid on this' on any result card; the item moves out of the search lineup into a
compact window that stays visible under any filter, radius or source. Marking is OWNER-REPORTED: never inferred from Save, never a bid
placement, no GSA sign-in or sync. Record path: the existing owner-local market prefs file (market_prefs.load/_store, key `bids`,
default var/market_prefs.json, MBOS_MARKET_PREFS_FILE); no second datastore. The optional max bid lives only there (var/ is not
committed) and is never shown outside this page. Current bid / bid count come from the source card WHEN it has them, else UNKNOWN."""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape as e

from . import market_prefs as mp

ACTS = ("bid", "unbid", "setmax")


def _clip(v, n=300) -> str:
    return str(v or "").strip()[:n]


def _num(v):
    try:
        x = float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None
    return x if 0 <= x < 1e9 else None


def act(action: str, f: dict, now: str) -> str:
    if action not in ACTS:
        raise ValueError("unknown bid action")
    lot = re.sub(r"[^A-Za-z0-9._:-]", "", f.get("lot") or "")[:60]
    if not lot:
        raise ValueError("no lot given")
    d = mp.load()
    bids = d["bids"]
    mx = _num(f.get("max_bid")) if str(f.get("max_bid") or "").strip() else None
    if str(f.get("max_bid") or "").strip() and mx is None:
        raise ValueError("max bid must be a plain number")
    if action == "bid":
        bids[lot] = {"title": _clip(f.get("title"), 120), "source": _clip(f.get("source"), 60), "url": _clip(f.get("url")), "closes": _clip(f.get("closes"), 10),
                     "closes_at": _clip(f.get("closes_at"), 40), "bid": _num(f.get("bid")), "bidders": _num(f.get("bidders")), "fetched_at": _clip(f.get("fetched_at"), 40),
                     "marked_at": now, "max_bid": mx}
        msg = "In My bids: owner-reported, nothing was placed or sent. It no longer shows in the search results; stop tracking to bring it back."
    elif action == "unbid":
        bids.pop(lot, None)
        msg = "Stopped tracking. It can appear in search results again if it matches your filters."
    else:
        if lot not in bids:
            raise ValueError("that item is not in My bids")
        bids[lot]["max_bid"] = mx
        msg = "Max bid saved on this computer only." if mx is not None else "Max bid cleared."
    mp._store(d)
    return msg


def exclude(cards: list[dict], d: dict) -> tuple[list[dict], int]:
    keep = [c for c in cards if c["id"] not in d["bids"]]
    return keep, len(cards) - len(keep)


def _end(r: dict):
    s = r.get("closes_at") or r.get("closes") or ""
    try:
        t = datetime.fromisoformat(s.replace("Z", "+00:00")) if "T" in s else datetime.combine(date.fromisoformat(s[:10]), datetime.max.time())
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def countdown(r: dict, now: datetime) -> str:
    t = _end(r)
    if t is None:
        return "closes UNKNOWN"
    s = int((t - now).total_seconds())
    if s <= 0:
        return f"closed (was {e(r.get('closes_at') or r['closes'])})"
    dh = f"{s // 86400}d {s % 86400 // 3600}h" if s >= 86400 else f"{s // 3600}h {s % 3600 // 60}m"
    return f"closes in {dh} ({e((r.get('closes_at') or r['closes'])[:16])}{'' if r.get('closes_at') else ', date only'})"


def window(d: dict, cards: list[dict], now: datetime, tok) -> str:
    """Compact window, closing-soonest first (unknown close last). Live source data (when this source was loaded) wins over the marking-time snapshot."""
    live = {c["id"]: c for c in cards}
    rows = []
    for i, r in d["bids"].items():
        c = live.get(i)
        r = {**r, **({"bid": c["bid"], "bidders": c.get("bidders"), "fetched_at": c.get("fetched_at") or r["fetched_at"]} if c and c.get("kind") != "auction event" else {})}
        rows.append((_end(r) or datetime.max.replace(tzinfo=timezone.utc), i, r))
    rows.sort(key=lambda t: (t[0], t[1]))
    li = []
    for _, i, r in rows:
        bid = f"${r['bid']:,.0f}" if r.get("bid") is not None else "UNKNOWN"
        cnt = f"{r['bidders']:g}" if r.get("bidders") is not None else "UNKNOWN"
        link = f"<a href='{e(r['url'])}' target='_blank' rel='noopener noreferrer'>original listing</a>" if r.get("url", "").startswith(("http://", "https://")) else "no link"
        hid = f"{tok()}<input type='hidden' name='lot' value='{e(i)}'>"
        mx = f"<br>your max: ${r['max_bid']:,.0f} <span class='mut'>(this computer only)</span>" if r.get("max_bid") is not None else ""
        li.append(f"<li data-bid='{e(i)}'><b>{e(r['title'] or i)}</b><br><span class='mut'>{e(r['source'] or 'source UNKNOWN')}</span> · {countdown(r, now)}<br>"
                  f"current bid {bid} · bids {cnt} · as of {e(r.get('fetched_at') or 'marking time')[:16]} · {link}{mx}<br>"
                  f"<form method='post' action='/market/bid' style='display:inline'>{hid}<button name='act' value='unbid'>Stop tracking</button></form> "
                  f"<form method='post' action='/market/bid' style='display:inline'>{hid}<input name='max_bid' size='6' inputmode='decimal' aria-label='Your max bid' placeholder='max $'>"
                  "<button name='act' value='setmax'>Set max</button></form></li>")
    body = f"<ul style='padding-left:16px;margin:4px 0'>{''.join(li)}</ul>" if li else "<p class='small mut'>Nothing tracked. Use 'I bid on this' on a card after you place a bid yourself.</p>"
    return (f"<div class='card small' id='my-bids'><b>My bids ({len(li)})</b><p class='mut' style='margin:2px 0'>You told us you bid. We do not place bids or check your account; "
            f"bid fields show only what the source gave us.</p>{body}</div>")


def button(c: dict, tok) -> str:
    f = lambda k, v: f"<input type='hidden' name='{k}' value='{e(str(v if v is not None else ''))}'>"  # noqa: E731
    hid = "".join(f(k, v) for k, v in (("lot", c["id"]), ("title", c["title"]), ("source", c.get("source")), ("url", c.get("url")), ("closes", c.get("closes")),
                                       ("closes_at", c.get("closes_at")), ("bid", c.get("bid")), ("bidders", c.get("bidders")), ("fetched_at", c.get("fetched_at"))))
    return (f"<form method='post' action='/market/bid' class='mk-pref' data-bidform>{tok()}{hid}<input name='max_bid' size='5' inputmode='decimal' aria-label='Your max bid (optional)' "
            "placeholder='my max $' title='Optional. Stays on this computer.'><button name='act' value='bid' title='You already placed this bid yourself; track it here'>I bid on this</button></form>")
