"""Owner's OWN bid notifications -> bid-event records. READY_QUEUE B-27 (owner request 2026-10-12).

Basis: these are the owner's own records (HiBid Terms of Use s.9 exclude "records relating to your auction or bid
history" from the extraction ban). The only route is the dedicated alerts mailbox read through the B-06 read-only
readers (EXAMINE, BODY.PEEK). NO login automation, account scraping or HiBid page fetch: nothing here makes a request.

Trust (reused from B-06): From domain must be the origin's AND `Authentication-Results` dkim=pass for that domain.
Output record (provenance = the e-mail's Message-ID; amounts are OWNER-LOCAL, never for sharing):
  {source, listing_id, title, url, event, amount?, closes_at?, observed_at, provenance, visibility, origin}
event: bid_placed | outbid | winning | won | lost | closed.
UNKNOWN: real notification wording; the keyword rules are generic and fixtures are synthetic. Re-record on the first
real notification.
"""

from __future__ import annotations

import email
import email.policy
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from typing import Callable
from urllib.parse import urlsplit

from .adapter import NormalizationError
from .adapters.email_alerts import MailboxReader, Origin, _Anchors, _authenticated
from .normalize import clean_text, money

EVENTS = ("bid_placed", "outbid", "winning", "won", "lost", "closed")

BID_ORIGINS = {o.source: o for o in [
    Origin("govdeals", "govdeals.com", re.compile(r"/(?:asset|en/asset)/([A-Za-z0-9\-]+(?:/[0-9]+)?)"), "auction_lot"),
    Origin("publicsurplus", "publicsurplus.com", re.compile(r"/auction/view\?auc=([0-9]+)|/auction/view/([0-9]+)"),
           "auction_lot"),
    Origin("gsa_auctions", "gsaauctions.gov", re.compile(r"/auctions?/(?:auction-)?details?/([A-Za-z0-9\-]+)"), "auction_lot"),
    Origin("hibid", "hibid.com", re.compile(r"/lot/([0-9]+)"), "auction_lot"),
]}

# First match wins; order matters ("outbid" and "did not win" before "win"; "bid placed" last).
_RULES = [
    ("outbid", re.compile(r"\bout-?bid\b|no longer the (?:high|winning) bidder", re.I)),
    ("lost", re.compile(r"did not win|not the winning|lost this auction|you lost|were not successful", re.I)),
    ("won", re.compile(r"\byou won\b|you have won|congratulations[,!.]?\s+you (?:have )?won|won this auction", re.I)),
    # "you are the winning bidder" is only a win once the platform says the auction is over.
    ("won", re.compile(r"(?=[\s\S]*you are the winning bidder)(?=[\s\S]*(?:auction (?:has )?(?:closed|ended)|has closed))", re.I)),
    ("winning", re.compile(r"currently (?:the )?(?:high|winning) bidder|you are the (?:high|winning) bidder|you are winning", re.I)),
    ("closed", re.compile(r"auction (?:has )?(?:closed|ended)|has closed|bidding (?:has )?closed", re.I)),
    ("bid_placed", re.compile(r"bid (?:has been |was )?(?:placed|received|confirmed|accepted)|bid confirmation", re.I)),
]
_AMOUNT = re.compile(r"(?:your bid|bid amount|winning bid|high bid|final bid|current bid|you bid)\s*:?\s*\$\s?"
                     r"([0-9][0-9,]*(?:\.[0-9]{2})?)", re.I)
_CLOSES = re.compile(r"(?:ends|closes|closing|end date)\s*:?\s*(20[0-9]{2}-[0-9]{2}-[0-9]{2})"
                     r"(?:[ T]([0-9]{2}:[0-9]{2})(?::[0-9]{2})?\s?(Z|[+-][0-9]{2}:?[0-9]{2}))?", re.I)


def classify_event(subject: str, text: str) -> str | None:
    for event, rx in _RULES:
        if rx.search(subject) or rx.search(text):
            return event
    return None


def _closes_at(text: str) -> str | None:
    m = _CLOSES.search(text)
    if not m:
        return None
    day, hm, tz = m.groups()
    if hm and tz:                                   # a stated instant with an explicit offset
        tz = "+00:00" if tz.upper() == "Z" else (tz if ":" in tz else tz[:3] + ":" + tz[3:])
        dt = datetime.fromisoformat(f"{day}T{hm}:00{tz}")
    else:                                           # date only: the platform's local zone is not stated -> UNKNOWN
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _origin_for(sender_domain: str) -> Origin | None:
    for o in BID_ORIGINS.values():
        if sender_domain == o.domain or sender_domain.endswith("." + o.domain):
            return o
    return None


def parse_bid_notification(source_bytes: bytes, observed_at: datetime) -> list[dict]:
    """Records for one message. Raises NormalizationError for a foreign, unauthenticated or unparseable message."""
    msg = email.message_from_bytes(source_bytes, policy=email.policy.default)
    sender = parseaddr(str(msg.get("From", "")))[1].lower()
    origin = _origin_for(sender.rsplit("@", 1)[-1] if "@" in sender else "")
    if origin is None:
        raise NormalizationError("sender is not a supported auction platform")
    if not _authenticated(msg, origin.domain):
        raise NormalizationError("notification not DKIM-authenticated for its domain (possible spoof); rejected")
    mid = clean_text(str(msg.get("Message-ID", "")), 200)
    if not mid:
        raise NormalizationError("no Message-ID: provenance impossible")
    part = msg.get_body(preferencelist=("html", "plain"))
    body = part.get_content() if part else ""
    if part is not None and part.get_content_type() == "text/plain":
        links, text = [(u, "", "") for u in re.findall(r"https://[^\s<>\"]+", body)], body
    else:
        p = _Anchors()
        p.feed(body)
        links = [tuple(x) for x in p.links]
        text = re.sub(r"<[^>]+>", " ", body)
    subject = clean_text(str(msg.get("Subject", "")), 200)
    plain = clean_text(text, 4000)
    event = classify_event(subject, plain)
    if event is None:
        raise NormalizationError("not a bid notification")
    out: dict[str, dict] = {}
    for href, atext, tail in links:
        u = urlsplit(href or "")
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not (host == origin.domain or host.endswith("." + origin.domain)):
            continue
        m = origin.listing_path.search(u.path + (f"?{u.query}" if u.query else ""))
        title = clean_text(atext, 300)
        if not m or not title:
            continue
        lid = next(g for g in m.groups() if g)
        if lid in out:
            continue
        ctx = clean_text(tail, 600)
        am = _AMOUNT.search(ctx)
        rec = {"source": origin.source, "listing_id": lid, "title": title,
               "url": f"https://{host}{u.path}" + (f"?{u.query}" if u.query else ""), "event": event}
        if am and money(am.group(1)) is not None:
            rec["amount"] = money(am.group(1))
        if (c := _closes_at(ctx)):
            rec["closes_at"] = c
        rec.update(observed_at=observed_at.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                   provenance={"kind": "email", "message_id": mid}, visibility="owner_local", origin="auto_detected")
        out[lid] = rec
    if not out:
        raise NormalizationError("no listing link on the platform's domain")
    return list(out.values())


def read_bid_events(reader: MailboxReader, *, lookback_days: int = 30,
                    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> tuple[list[dict], list[dict]]:
    """(records, rejected). Idempotent: a message read twice yields each (Message-ID, listing) once."""
    now = clock()
    records: dict[tuple[str, str], dict] = {}
    rejected: list[dict] = []
    for raw in reader.messages(now - timedelta(days=lookback_days)):
        try:
            recs = parse_bid_notification(raw, now)
        except NormalizationError as e:
            rejected.append({"reason": str(e)})
            continue
        for r in recs:
            records.setdefault((r["provenance"]["message_id"], r["listing_id"]), r)
    return list(records.values()), rejected
