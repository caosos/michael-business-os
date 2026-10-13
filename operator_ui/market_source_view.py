"""F-145: per-source coverage/status line, the FIXTURE / not live labelling and the NOT CONNECTED states for /market. Pure markup; all text escaped.
Only GSA (cached file) is ever called connected. A parser-backed .eml fixture is FIXTURE / not live; every other source is NOT CONNECTED."""

from __future__ import annotations

import html
from datetime import datetime, timezone

from . import market_search as ms
from . import market_sources as msrc
from .deal_ui import classify_url

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731
FIXTURE_BANNER = ("FIXTURE / not live: scrubbed test e-mails read from a local directory on an isolated staging server. These are not Michael's real deals, "
                  "no mailbox is read, and nothing here counts as a connected source.")
ALWAYS_OFF = ("eBay",)


def source_options() -> list[tuple[str, str]]:
    fx = msrc.fixture_dir() is not None
    now = datetime.now(timezone.utc)
    tag = lambda k, n: f"{n} (FIXTURE, not live)" if fx else {"connected": n, "waiting": f"{n} (connected, waiting for alerts)"}.get(msrc.load_alerts(k, None, now)["status"], f"{n} (not connected)")  # noqa: E731
    alerts = [(k, tag(k, n)) for k, (_, n) in msrc.ALERT_SOURCES.items()]
    facebook = msrc.probe(next(i for i in msrc.REGISTRY if i.key == "facebook"), now)
    fb_label = "Facebook Marketplace" + ("" if facebook["status"] == "connected" else " (not connected)")
    return [("gsa", "GSA Auctions")] + [(k, x.name) for k, x in msrc.AUCTION_SITES.items()] + [(msrc.ALL_HOUSES, "All auction houses")] + alerts + [("facebook", fb_label), ("all", "All sources (merged)")] + [(n.lower(), n + " (not connected)") for n in ALWAYS_OFF]


def _row(c: dict) -> str:
    n = e(c["name"])
    if c["status"] == "offline":
        return f"<li data-src='{n}' data-status='offline'><b class='bad'>{n}: offline</b> · {e(c.get('message') or 'no cached read; nothing is shown')}</li>"
    if c["status"] == "connected":
        unit = "auction events (not lots)" if c["name"] in msrc.EVENT_NAMES else "listings" if c["name"] == "Craigslist" else "lots"
        note = f" · {e(c['message'])}" if c.get("message") else ""
        age = f" · last fetched {e(str(c['as_of'])[:16].replace('T', ' '))} UTC ({c['age_h']:g} h ago){' · <b class=bad>STALE</b>' if c['stale'] else ''} · {c['in_scope']} {unit}{note}"
        how = "mailbox read, cached" if c["name"] in {v[1] for v in msrc.ALERT_SOURCES.values()} else "cached file"
        return f"<li data-src='{n}' data-status='connected'><b>{n}: connected ({how})</b>{age}</li>"
    if c["status"] == "waiting":
        return f"<li data-src='{n}' data-status='waiting'><b>{n}: connected, waiting for alerts</b> · mailbox last read {e(str(c['as_of'])[:16].replace('T', ' '))} UTC ({c['age_h']:g} h ago){' · <b class=bad>STALE</b>' if c['stale'] else ''} · no {n} alert yet</li>"
    if c["status"] == "fixture":
        return (f"<li data-src='{n}' data-status='fixture'><b class='bad'>{n}: FIXTURE / not live</b> · {c['in_scope']} test listing(s) · newest test e-mail dated "
                f"{e(str(c['as_of'])[:16].replace('T', ' '))} UTC{' · STALE' if c['stale'] else ''}</li>")
    return f"<li data-src='{n}' data-status='{e(c['status'])}'><b>{n}: NOT CONNECTED</b> · no mailbox read, nothing shown</li>"


def coverage(d: dict, banner_inline: bool = True) -> str:
    """Status block for a non-GSA source page (govdeals | publicsurplus | all)."""
    rows = "".join(_row(c) for c in d.get("coverage") or [{k: d.get(k) for k in ("name", "status", "as_of", "age_h", "stale", "in_scope")}])
    off = "".join(f"<li data-src='{e(n)}' data-status='not_connected'><b>{e(n)}: NOT CONNECTED</b></li>" for n in ALWAYS_OFF)
    banner = f"<div class='flash err' id='fixture-banner' role='note'><b>{e(FIXTURE_BANNER)}</b></div>" if d.get("fixture") and banner_inline else ""
    return f"{banner}<ul class='small' id='source-status' style='margin:6px 0;padding-left:18px'>{rows}{off}</ul>"


def gate(q: dict, d: dict) -> str | None:
    """Refuse only unknown source keys.

    The browse route always loads the unified pool and then applies its source
    checkboxes.  The old single-source gate incorrectly hid Facebook and every
    comma-separated multi-source selection, including genuinely cached rows.
    """
    selected = {v for v in str(q.get("source") or "all").split(",") if v}
    known = {"all", msrc.ALL_HOUSES, *(i.key for i in msrc.REGISTRY)}
    unknown = sorted(selected - known)
    if not unknown:
        return None
    return f"<div class='card'><b>{e(', '.join(unknown))}: not connected.</b> No results are shown for an unknown source; nothing is mocked.</div>"


def card_note(c: dict) -> str:
    return (f"<div class='small'><span class='badge'>FIXTURE / not live</span> {e(c['source'])} · fetched {e(c['fetched_at'])}</div>") if c.get("fixture") else ""


def scope_line(d: dict) -> str:
    if d.get("name") in msrc.EVENT_NAMES or d.get("name") == "All auction houses":
        who = d["name"] if d.get("name") in msrc.EVENT_NAMES else "the auction houses'"
        return (f"Cached copy of {who} own auction pages (auction EVENTS, not lots; refreshed only by an explicit command). Lot numbers, current bids and bid counts are UNKNOWN. "
                "A price range excludes events (they have no price).")
    if d.get("coverage") and any(c["name"] in msrc.EVENT_NAMES and c["status"] == "connected" for c in d["coverage"]) and not d.get("fixture"):
        return "Cached GSA lots plus auction-house events (events have no price or bid; a price range excludes them). Price = current bid, not a sold price or final cost; all-in cost UNKNOWN."
    if d.get("fixture"):
        return "Parser-backed test e-mails (FIXTURE, not live), merged with the cached GSA list when all sources are chosen. Price = alert text, not a sold price or final cost; all-in cost UNKNOWN."
    return "Cached copy of the GSA list, not a fresh fetch (GSA surplus only). Price = current bid, not a sold price or final cost; all-in cost UNKNOWN."


def _kv(label: str, v) -> str:
    return f"<span class='lbl'>{e(label)}</span> {e(v) if v not in (None, '') else 'UNKNOWN'}"


def _platform(c: dict) -> str:
    """A plain link for the human to click; classify_url checks scheme/host. This page never requests it (HiBid / BidWrangler terms)."""
    u = c.get("platform_url") or c.get("hibid_url")
    ok = u and classify_url(u)[0] == "live"
    name = c.get("platform") or "HiBid"
    return f"<a href='{e(u)}' rel='noopener noreferrer nofollow' target='_blank'>View and bid on {e(name)}</a>" if ok else ""


def _links(c: dict, link) -> str:
    pl = f"{_platform(c)} (opens {e(c.get('platform') or 'HiBid')}; this page never loads it)" if _platform(c) else f"{e(c.get('platform') or 'Bidding platform')} link: UNKNOWN"
    return f"<p>Original listing ({e(c['source'])} page): {link(c['url'])} · {pl}</p>"


def when_label(c: dict) -> str:
    """Local human time with the existing countdown style: 'closes Tue Oct 13, 6:00 PM CDT (closes in 2d 4h)'."""
    if c.get("closes_at"):
        left = c.get("left")
        return f"closes {e(c.get('closes_local') or c['closes_at'])}" + (f" ({'closed' if left == 'closed' else 'closes in ' + e(left)})" if left else "")
    if c.get("begins_at"):
        return f"live event starts {e(c.get('begins_local') or c['begins_at'])} (no end time published)"
    return "closes UNKNOWN"


def event_card(c: dict, tok, pref_buttons, link) -> str:
    """List card for an auction EVENT: no price, bid, lot or image is known; the bidding platform is a link for the human only."""
    prem = f"{c['buyer_premium_pct']:g}%" if c.get("buyer_premium_pct") is not None else "not stated"
    where = e(c["city"] or "UNKNOWN") + (f" · {round(c['distance'], 1):g} mi from your base" if c["distance"] is not None else " · distance UNKNOWN")
    stale = " <b class='bad'>STALE: cached event data may be out of date</b>" if c["stale"] else ""
    tags = " ".join(f"<span class='mk-tag'>{e(t)}</span>" for t in c.get("tags") or []) or "none listed"
    return (f"<div class='card mk-res' data-kind='auction-event'><div style='min-width:0'><h3 style='margin:0 0 4px'>{e(c['title'])} <span class='badge'>AUCTION EVENT</span></h3>"
            f"<p class='small'>{e(c['description']) or '<span class=mut>No description</span>'}</p>"
            f"<p>{_kv('Auctioneer', c.get('auctioneer'))} · <span class='when'>{when_label(c)}</span> · {where} · {_kv('Buyer premium', prem)}</p>"
            f"<p class='small' id='event-unknowns'>{_kv('Lot number', None)} · {_kv('Current bid', None)} · {_kv('Bid count', None)} (lot-level data is only on {e(c.get('platform') or 'the bidding platform')}, which this page does not read)</p>"
            f"<p class='small'>Categories: {tags}</p>{_links(c, link)}{pref_buttons(c, tok) if tok else ''}"
            f"<p class='small mut'>Source {e(c['source'])} · fetched {e(c['fetched_at'])} · {e(c['kind'])} · this is an event, not a lot; no price, bid or sold comp is known{stale}</p></div></div>")


def event_gallery(c: dict, tok, pref_buttons, link) -> str:
    town = e(c["city"] or "town UNKNOWN") + (f" · {round(c['distance'], 1):g} mi" if c["distance"] is not None else " · distance UNKNOWN")
    ti = c["title"] if len(c["title"]) <= 60 else c["title"][:59] + "…"
    hb = f" · {_platform(c)}" if _platform(c) else ""
    return (f"<div class='mk-g' data-lot='{e(c['id'])}' data-kind='auction-event'><div class='ph small mut'>No lot image (event)</div><div class='pr'>Auction event</div>"
            f"<div class='small mut'>lot / bid / bid count UNKNOWN</div><div class='ti'><b>{e(ti)}</b></div><div class='small'>{town}</div>"
            f"<div class='small mut'>{e(c['source'])} · {when_label(c)}{' · <b class=bad>STALE</b>' if c['stale'] else ''}</div>"
            f"<div class='small'>{link(c['url'])}{hb}</div>{pref_buttons(c, tok)}</div>")
