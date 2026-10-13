"""Customer-facing setup instructions derived from the source registry.

This module performs no network requests and accepts no source credentials. It
only explains how a source can truthfully enter DealSniffer today: a proven
alert mailbox, an existing cache, or an owner-pasted original URL.
"""

from __future__ import annotations

import html
from datetime import datetime, timezone

from . import account_delivery, market_sources

e = lambda v: html.escape("" if v is None else str(v))  # noqa: E731

ONBOARD_KEYS = (
    "govdeals", "publicsurplus", "hibid_email", "wooley", "craigslist", "offerup",
    "nahlen", "auctionzip", "half_off_wholesale", "northbay", "bargain_brothers",
)


def entries(account_id: str, now: datetime | None = None) -> list[dict]:
    """Return setup records without upgrading any source's evidence-backed state."""
    now = now or datetime.now(timezone.utc)
    alert = account_delivery.status(account_id, "alerts")
    registry = {info.key: info for info in market_sources.REGISTRY}
    out = []
    for key in ONBOARD_KEYS:
        info = registry[key]
        pr = market_sources.probe(info, now)
        out.append({"info": info, "state": market_sources.source_state(info, pr), "probe": pr,
                    "alert_address": alert["address"], "alert_state": alert["state"]})
    return out


def render(account_id: str, now: datetime | None = None) -> str:
    rs = entries(account_id, now)
    alert = rs[0] if rs else {"alert_address": None, "alert_state": "NOT CONNECTED"}
    mailbox = (f"Your alert address is <code>{e(alert['alert_address'])}</code>, but it remains <b>{e(alert['alert_state'])}</b> until a real provider receipt succeeds."
               if alert["alert_address"] else "Your DealSniffer alert address is <b>NOT CONNECTED</b>. You can create saved searches now; forwarding cannot start until the mailbox provider is configured and proven.")
    cards = []
    for r in rs:
        info = r["info"]
        link = f"<a href='{e(info.setup_url)}' rel='noopener noreferrer'>Open {e(info.name)}</a> · " if info.setup_url else ""
        parser = f"<span class='badge'>{e(info.parser.upper())}</span>" if info.parser else ""
        manual = " <a href='/market#add-find'>Paste an original link</a>." if info.import_key else ""
        cards.append(f"<article class='card source-setup' data-source='{e(info.key)}' data-state='{e(r['state'])}'><h3>{e(info.name)} <span class='badge'>{e(r['state'])}</span></h3>"
                     f"<p>{link}{parser}</p><p>{e(info.user_setup)}{manual}</p><p class='small mut'><b>Constraint:</b> {e(info.constraint)}<br><b>Next:</b> {e(info.next_step)}</p></article>")
    return ("<section class='card' id='source-onboarding'><h2>Add sources</h2><p>DealSniffer never asks for a source password. Set up alerts in your own source account, "
            "or paste an original listing URL. A setup link does not mean the source is connected.</p>"
            f"<p id='alert-onboarding-state'>{mailbox}</p><div class='source-setup-grid'>{''.join(cards)}</div></section>")
