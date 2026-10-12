"""F-145: per-source coverage/status line, the FIXTURE / not live labelling and the NOT CONNECTED states for /market. Pure markup; all text escaped.
Only GSA (cached file) is ever called connected. A parser-backed .eml fixture is FIXTURE / not live; every other source is NOT CONNECTED."""

from __future__ import annotations

import html

from . import market_search as ms
from . import market_sources as msrc
from .deal_ui import classify_url

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
FIXTURE_BANNER = ("FIXTURE / not live: scrubbed test e-mails read from a local directory on an isolated staging server. These are not Michael's real deals, "
                  "no mailbox is read, and nothing here counts as a connected source.")
ALWAYS_OFF = ("Craigslist", "eBay", "Facebook Marketplace")


def source_options() -> list[tuple[str, str]]:
    fx = msrc.fixture_dir() is not None
    alerts = [(k, f"{n} (FIXTURE, not live)" if fx else f"{n} (not connected)") for k, (_, n) in msrc.ALERT_SOURCES.items()]
    return [("gsa", "GSA Auctions"), ("wooley", "Wooley Auctioneers")] + alerts + [("all", "All sources (merged)")] + [(n.lower(), n + " (not connected)") for n in ALWAYS_OFF]


def _row(c: dict) -> str:
    n = e(c["name"])
    if c["status"] == "offline":
        return f"<li data-src='{n}' data-status='offline'><b class='bad'>{n}: offline</b> · {e(c.get('message') or 'no cached read; nothing is shown')}</li>"
    if c["status"] == "connected":
        unit = "auction events (not lots)" if c["name"] == msrc.WOOLEY_NAME else "lots"
        note = f" · {e(c['message'])}" if c.get("message") else ""
        age = f" · last fetched {e(str(c['as_of'])[:16].replace('T', ' '))} UTC ({c['age_h']:g} h ago){' · <b class=bad>STALE</b>' if c['stale'] else ''} · {c['in_scope']} {unit}{note}"
        return f"<li data-src='{n}' data-status='connected'><b>{n}: connected (cached file)</b>{age}</li>"
    if c["status"] == "fixture":
        return (f"<li data-src='{n}' data-status='fixture'><b class='bad'>{n}: FIXTURE / not live</b> · {c['in_scope']} test listing(s) · newest test e-mail dated "
                f"{e(str(c['as_of'])[:16].replace('T', ' '))} UTC{' · STALE' if c['stale'] else ''}</li>")
    return f"<li data-src='{n}' data-status='{e(c['status'])}'><b>{n}: NOT CONNECTED</b> · no mailbox read, nothing shown</li>"


def coverage(d: dict) -> str:
    """Status block for a non-GSA source page (govdeals | publicsurplus | all)."""
    rows = "".join(_row(c) for c in d.get("coverage") or [{k: d.get(k) for k in ("name", "status", "as_of", "age_h", "stale", "in_scope")}])
    off = "".join(f"<li data-src='{e(n)}' data-status='not_connected'><b>{e(n)}: NOT CONNECTED</b></li>" for n in ALWAYS_OFF)
    banner = f"<div class='flash err' id='fixture-banner' role='note'><b>{e(FIXTURE_BANNER)}</b></div>" if d.get("fixture") else ""
    return f"{banner}<ul class='small' id='source-status' style='margin:6px 0;padding-left:18px'>{rows}{off}</ul>"


def gate(q: dict, d: dict) -> str | None:
    """The body for a source that has no read to show, else None. A single alert source without the staging fixtures is NOT CONNECTED."""
    s = q["source"]
    if s in ("gsa", "all", "wooley"):
        return None
    if s in msrc.ALERT_SOURCES and d["status"] == "fixture":
        return None
    return f"<div class='card'><b>{e(msrc.ALERT_SOURCES[s][1] if s in msrc.ALERT_SOURCES else s)}: not connected.</b> No results are shown for a source that is not wired; nothing is mocked.</div>"


def card_note(c: dict) -> str:
    return (f"<div class='small'><span class='badge'>FIXTURE / not live</span> {e(c['source'])} · fetched {e(c['fetched_at'])}</div>") if c.get("fixture") else ""


def scope_line(d: dict) -> str:
    if d.get("name") == msrc.WOOLEY_NAME:
        return ("Cached copy of Wooley's own auction pages (auction EVENTS, not lots; refreshed only by an explicit command). Lot numbers, current bids and bid counts are UNKNOWN. "
                "A price range excludes events (they have no price).")
    if d.get("coverage") and any(c["name"] == msrc.WOOLEY_NAME and c["status"] == "connected" for c in d["coverage"]) and not d.get("fixture"):
        return "Cached GSA lots plus Wooley auction events (events have no price or bid; a price range excludes them). Price = current bid, not a sold price or final cost; all-in cost UNKNOWN."
    if d.get("fixture"):
        return "Parser-backed test e-mails (FIXTURE, not live), merged with the cached GSA list when all sources are chosen. Price = alert text, not a sold price or final cost; all-in cost UNKNOWN."
    return "Cached copy of the GSA list, not a fresh fetch (GSA surplus only). Price = current bid, not a sold price or final cost; all-in cost UNKNOWN."


def _kv(label: str, v) -> str:
    return f"<span class='lbl'>{e(label)}</span> {e(v) if v not in (None, '') else 'UNKNOWN'}"


def _hibid(c: dict) -> str:
    """A plain link for the human to click; classify_url checks scheme/host. This page never requests it."""
    ok = c.get("hibid_url") and classify_url(c["hibid_url"])[0] == "live"
    return f"<a href='{e(c['hibid_url'])}' rel='noopener noreferrer nofollow' target='_blank'>View and bid on HiBid</a>" if ok else ""


def _links(c: dict, link) -> str:
    hb = f"{_hibid(c)} (opens HiBid; this page never loads it)" if _hibid(c) else "HiBid catalog link: UNKNOWN"
    return f"<p>Original listing (Wooley auction page): {link(c['url'])} · {hb}</p>"


def event_card(c: dict, tok, pref_buttons, link) -> str:
    """List card for a Wooley auction EVENT: no price, bid, lot or image is known; HiBid is a link for the human only."""
    prem = f"{c['buyer_premium_pct']:g}%" if c.get("buyer_premium_pct") is not None else "not stated"
    where = e(c["city"] or "UNKNOWN") + (f" · {round(c['distance'], 1):g} mi from your base" if c["distance"] is not None else " · distance UNKNOWN")
    stale = " <b class='bad'>STALE: cached event data may be out of date</b>" if c["stale"] else ""
    tags = " ".join(f"<span class='mk-tag'>{e(t)}</span>" for t in c.get("tags") or []) or "none listed"
    return (f"<div class='card mk-res' data-kind='auction-event'><div style='min-width:0'><h3 style='margin:0 0 4px'>{e(c['title'])} <span class='badge'>AUCTION EVENT</span></h3>"
            f"<p class='small'>{e(c['description']) or '<span class=mut>No description</span>'}</p>"
            f"<p>{_kv('Auctioneer', c.get('auctioneer'))} · closes {e(c.get('closes_at') or 'UNKNOWN')} · {where} · {_kv('Buyer premium', prem)}</p>"
            f"<p class='small' id='event-unknowns'>{_kv('Lot number', None)} · {_kv('Current bid', None)} · {_kv('Bid count', None)} (lot-level data is only on HiBid, which this page does not read)</p>"
            f"<p class='small'>Categories: {tags}</p>{_links(c, link)}{pref_buttons(c, tok) if tok else ''}"
            f"<p class='small mut'>Source {e(c['source'])} · fetched {e(c['fetched_at'])} · {e(c['kind'])} · this is an event, not a lot; no price, bid or sold comp is known{stale}</p></div></div>")


def event_gallery(c: dict, tok, pref_buttons, link) -> str:
    town = e(c["city"] or "town UNKNOWN") + (f" · {round(c['distance'], 1):g} mi" if c["distance"] is not None else " · distance UNKNOWN")
    ti = c["title"] if len(c["title"]) <= 60 else c["title"][:59] + "…"
    hb = f" · {_hibid(c)}" if _hibid(c) else ""
    return (f"<div class='mk-g' data-lot='{e(c['id'])}' data-kind='auction-event'><div class='ph small mut'>No lot image (event)</div><div class='pr'>Auction event</div>"
            f"<div class='small mut'>lot / bid / bid count UNKNOWN</div><div class='ti'><b>{e(ti)}</b></div><div class='small'>{town}</div>"
            f"<div class='small mut'>{e(c['source'])} · closes {e(c.get('closes_at') or 'UNKNOWN')}{' · <b class=bad>STALE</b>' if c['stale'] else ''}</div>"
            f"<div class='small'>{link(c['url'])}{hb}</div>{pref_buttons(c, tok)}</div>")
