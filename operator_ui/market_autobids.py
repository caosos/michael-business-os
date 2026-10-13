"""F-152 (B-27 wiring): bids detected from the owner's OWN bid e-mails, shown in the My bids window next to the owner-marked ones.
Read-only: `mbos_discovery.bid_events.read_bid_events` over an `EmlDirReader`, and ONLY on the isolated-staging fixture flag
(MBOS_STAGING_FIXTURES=1 + MBOS_BID_MAIL_DIR). Never IMAP, never a network request, no credentials. Without the flag the window says so.
Amounts are owner-local and shown only on this page. 'Stop tracking' is stored in the owner-local market prefs (`auto_stopped`); mail is never touched."""

from __future__ import annotations

import os
from html import escape as e
from pathlib import Path
from urllib.parse import urlsplit

from mbos_discovery.adapters import EmlDirReader
from mbos_discovery.bid_events import read_bid_events

ENV_FLAG, ENV_DIR = "MBOS_STAGING_FIXTURES", "MBOS_BID_MAIL_DIR"
NOT_CONNECTED = "Automatic bid detection is not connected (no mailbox)."
WORDS = {"bid_placed": "bid placed", "outbid": "you were OUTBID", "winning": "you are winning (for now)", "won": "you WON", "lost": "you did not win", "closed": "auction closed"}
NAMES = {"govdeals": "GovDeals", "publicsurplus": "Public Surplus", "gsa_auctions": "GSA Auctions", "gsa": "GSA Auctions", "hibid": "HiBid"}
ENDED = frozenset({"won", "lost", "closed"})
_RANK = {"bid_placed": 0, "outbid": 1, "winning": 1, "closed": 2, "won": 3, "lost": 3}   # later lifecycle stage wins; a tie keeps the later message in the directory
NEXT = {"bid_placed": "Monitor the listing until closing.", "winning": "Monitor the listing until closing.",
        "outbid": "Open the original listing; raise only if it stays within your max.", "won": "Open the source to confirm payment and pickup.",
        "lost": "Review the result and archive this watch.", "closed": "Open the source to confirm the final result."}


def mail_dir() -> str | None:
    d = os.environ.get(ENV_DIR)
    return d if os.environ.get(ENV_FLAG) == "1" and d and Path(d).is_dir() else None


def norm_url(u) -> str:
    s = urlsplit(str(u or "").strip())
    return f"{(s.hostname or '').lower().removeprefix('www.')}{s.path.rstrip('/')}" + (f"?{s.query}" if s.query else "") if s.hostname else ""


def item_id(r: dict) -> str:
    return f"auto:{r['source']}:{r['listing_id'].replace('/', '-')}"


def load(now, prefs: dict) -> tuple[list[dict], str]:
    """-> (auto-detected items not stopped by the owner, one-line note). DKIM-failed / foreign mail yields no item (the parser rejects it)."""
    d = mail_dir()
    if not d:
        return [], f"<p class='small mut' id='auto-bids-note'>{NOT_CONNECTED}</p>"
    best: dict[str, dict] = {}
    closes: dict[str, str] = {}
    for r in read_bid_events(EmlDirReader(d), clock=lambda: now)[0]:
        i = item_id(r)
        if r.get("closes_at"):
            closes[i] = r["closes_at"]
        if i not in best or _RANK[r["event"]] >= _RANK[best[i]["event"]]:
            best[i] = {**r, "earlier": ([best[i]["event"]] + best[i]["earlier"]) if i in best else []}
        else:
            best[i]["earlier"].append(r["event"])
    for i, r in best.items():                          # a close time stated by any e-mail about the listing stands; otherwise UNKNOWN
        r.setdefault("closes_at", closes.get(i))
    return [{**r, "id": i} for i, r in best.items() if i not in prefs["auto_stopped"]], ""


def urls(items) -> frozenset:
    return frozenset(u for u in (norm_url(r["url"]) for r in items) if u)


def rows(items, now, tok, countdown, end, badge=lambda r, n: "", rank=lambda r, n: 2):
    out = []
    for r in items:
        sent = r.get("email_date") or r.get("sent_at")     # the e-mail's own Date header, only if the parser provides it (v1 does not): else the read date
        when = (("ended (per your e-mail, %s)" % e(str(sent)[:10])) if sent else "ended (read %s)" % e(str(r.get("observed_at") or "date UNKNOWN")[:10])) if r["event"] in ENDED else None
        rr = {"closes_at": r.get("closes_at") or "", "closes": ""}
        amt = f"amount in the e-mail: ${r['amount']:,.2f} <span class='mut'>(owner-local, this page only)</span>" if r.get("amount") is not None else "amount not stated"
        link = f"<a href='{e(r['url'])}' target='_blank' rel='noopener noreferrer'>original listing</a>" if r["url"].startswith(("http://", "https://")) else "no link"
        hid = f"{tok()}<input type='hidden' name='lot' value='{e(r['id'])}'>"
        out.append((end(rr) or __import__("datetime").datetime.max.replace(tzinfo=__import__("datetime").timezone.utc), r["id"],
                    f"<li data-bid='{e(r['id'])}' data-auto='1' data-origin='EMAIL ALERT'><b>{e(r['title'])}</b><br><span class='mut'>{e(NAMES.get(r['source'], r['source']))} · auto-detected from your e-mail · EMAIL ALERT · no source-account access</span><br>"
                    f"status <b>{WORDS[r['event']]}</b> · {when or countdown(rr, now) + badge(rr, now)}<br>current bid UNKNOWN · your max UNKNOWN · {amt} · {link}<br>"
                    + (f"earlier e-mails: {e(', '.join(WORDS[x] for x in r['earlier']))}<br>" if r.get("earlier") else "") + f"next action: {e(NEXT[r['event']])}<br><span class='mut'>provenance: e-mail Message-ID {e(r['provenance']['message_id'])}</span><br>"
                    f"<form method='post' action='/market/bid' style='display:inline'>{hid}<button name='act' value='unbid'>Stop tracking</button></form></li>",
                    2 if when else rank(rr, now)))
    return out
