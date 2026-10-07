"""Saved-search alert e-mails — ADR-02-0202 tier 2 (sanctioned: we read our OWN inbox). READY_QUEUE B-06.

One adapter instance per origin, so each keeps its own platform identity, health and freeze:

    govdeals_email · publicsurplus_email · estatesales_net_email   (scraping EstateSales.NET stays FORBIDDEN)

Mailbox access is read-only by construction:
* `EmlDirReader(dir)` — fixtures / exported mail (`*.eml`), no network.
* `ImapReader(...)` — IMAP4_SSL, `select(folder, readonly=True)`, `SEARCH SINCE`, `FETCH (BODY.PEEK[])`
  (PEEK: not even \\Seen is set). No STORE, COPY, MOVE, EXPUNGE or APPEND exist in this module. Runs only with
  `live=True`; password from an env var, never from config.

Trust: an alert is accepted only if the From domain is the origin's AND `Authentication-Results` reports
`dkim=pass` for that domain (spoofed "alerts" are quarantined). Listing links must be https on the origin's
domain. Text is untrusted input (prompt-injection flags apply).

Replay: each listing's raw payload is `{"origin", "email_source", "listing_index"}` — the whole message plus
which listing — so `normalize` re-parses deterministically from `raw_ref`.

UNKNOWN (research §12): real alert layouts. The parsers are deliberately generic (anchor + nearby text) and the
fixtures are hand-built; re-record real alerts on first live run and tighten per origin.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr, parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable, Protocol
from urllib.parse import urlsplit

from ..adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..canonical import CanonicalError, raw_json_bytes
from ..normalize import MAX_DESCRIPTION, base_flags, classify, clean_text, match_text, money, norm_ts

MAX_MESSAGE_BYTES = 512 * 1024


@dataclass(frozen=True)
class Origin:
    source: str
    domain: str                     # From-domain and link-domain suffix
    listing_path: re.Pattern        # matches a listing URL path; group 1 = listing id
    opportunity_kind: str
    event_sale: bool = False        # a sale EVENT (estate sale), not one item: never keyword-classified


ORIGINS = {o.source: o for o in [
    Origin("govdeals_email", "govdeals.com", re.compile(r"/(?:asset|en/asset)/([A-Za-z0-9\-]+(?:/[0-9]+)?)"), "auction_lot"),
    Origin("publicsurplus_email", "publicsurplus.com", re.compile(r"/auction/view\?auc=([0-9]+)|/auction/view/([0-9]+)"),
           "auction_lot"),
    Origin("estatesales_net_email", "estatesales.net", re.compile(r"/[A-Z]{2}/[^/]+/[0-9]{5}/([0-9]+)"), "buy_item",
           event_sale=True),
]}


# ---------------------------------------------------------------- mailbox readers (read-only)
class MailboxReader(Protocol):
    def messages(self, since: datetime) -> Iterable[bytes]: ...


class EmlDirReader:
    def __init__(self, directory: str | Path) -> None:
        self.dir = Path(directory)

    def messages(self, since: datetime) -> Iterable[bytes]:
        if not self.dir.is_dir():
            raise FileNotFoundError(f"mail directory not found: {self.dir}")
        for p in sorted(self.dir.glob("*.eml")):
            yield p.read_bytes()[:MAX_MESSAGE_BYTES]


class ImapReader:
    """Read-only IMAP. `connect` is injectable for tests (default: imaplib.IMAP4_SSL)."""

    def __init__(self, host: str, user: str, password_env: str, folder: str = "INBOX", *, live: bool = False,
                 connect: Callable[[str], object] | None = None, password: str | None = None) -> None:
        self.host, self.user, self.password_env, self.folder, self.live = host, user, password_env, folder, live
        self._password = password                       # explicit override (dry-run placeholder); never from config files
        self.connect = connect or (lambda h: imaplib.IMAP4_SSL(h))

    def messages(self, since: datetime) -> Iterable[bytes]:
        if not self.live:
            raise PermissionError("live mailbox access not enabled (set live = true)")
        password = self._password or os.environ.get(self.password_env)
        if not password:
            raise PermissionError(f"{self.password_env} not set")
        conn = self.connect(self.host)
        try:
            conn.login(self.user, password)
            typ, _ = conn.select(self.folder, readonly=True)          # EXAMINE: the server enforces read-only
            if typ != "OK":
                raise ConnectionError(f"cannot open {self.folder} read-only")
            typ, data = conn.search(None, "SINCE", since.strftime("%d-%b-%Y"))
            if typ != "OK":
                raise ConnectionError("IMAP SEARCH failed")
            for num in (data[0] or b"").split():
                typ, parts = conn.fetch(num, "(BODY.PEEK[])")         # PEEK: no \\Seen flag change
                if typ == "OK":
                    for part in parts:
                        if isinstance(part, tuple):
                            yield part[1][:MAX_MESSAGE_BYTES]
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- parsing (pure)
class _Anchors(HTMLParser):
    """Collect (href, anchor text, text after the anchor up to the next anchor)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[list[str]] = []
        self._in_a = False

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.links.append([dict(attrs).get("href") or "", "", ""])
            self._in_a = True

    def handle_endtag(self, tag):
        if tag == "a":
            self._in_a = False

    def handle_data(self, data):
        if not self.links:
            return
        slot = 1 if self._in_a else 2
        self.links[-1][slot] = (self.links[-1][slot] + " " + data)[:600]


@dataclass(frozen=True)
class ParsedListing:
    listing_id: str
    url: str
    title: str
    context: str


def _authenticated(msg, domain: str) -> bool:
    for h in msg.get_all("Authentication-Results", []) or []:
        for m in re.finditer(r"dkim=(\w+)[^;]*?header\.d=([\w.\-]+)", str(h), re.IGNORECASE):
            if m.group(1).lower() == "pass" and (m.group(2).lower() == domain or m.group(2).lower().endswith("." + domain)):
                return True
    return False


def parse_alert(origin: Origin, source_bytes: bytes) -> tuple[dict, list[ParsedListing]]:
    """Return (header facts, listings). Raises NormalizationError for an untrusted or foreign message."""
    msg = email.message_from_bytes(source_bytes, policy=email.policy.default)
    sender = parseaddr(str(msg.get("From", "")))[1].lower()
    sender_domain = sender.rsplit("@", 1)[-1] if "@" in sender else ""
    if not (sender_domain == origin.domain or sender_domain.endswith("." + origin.domain)):
        raise NormalizationError(f"sender {sender_domain or '?'} is not {origin.domain}")
    if not _authenticated(msg, origin.domain):
        raise NormalizationError("alert not DKIM-authenticated for its domain (possible spoof); quarantined")
    try:
        sent = parsedate_to_datetime(str(msg.get("Date"))).astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise NormalizationError("alert has no valid Date header") from None
    part = msg.get_body(preferencelist=("html", "plain"))
    body = part.get_content() if part else ""
    if part is not None and part.get_content_type() == "text/plain":
        links = [(u, "", "") for u in re.findall(r"https://[^\s<>\"]+", body)]
    else:
        p = _Anchors()
        p.feed(body)
        links = [tuple(x) for x in p.links]
    seen: dict[str, ParsedListing] = {}
    for href, text, tail in links:
        u = urlsplit(href or "")
        host = (u.hostname or "").lower()
        if u.scheme != "https" or not (host == origin.domain or host.endswith("." + origin.domain)):
            continue
        m = origin.listing_path.search(u.path + (f"?{u.query}" if u.query else ""))
        if not m:
            continue
        lid = next(g for g in m.groups() if g)
        title = clean_text(text, 300)
        if lid not in seen and title:
            seen[lid] = ParsedListing(lid, f"https://{host}{u.path}" + (f"?{u.query}" if u.query else ""),
                                      title, clean_text(tail, 600))
    facts = {"from": sender, "subject": clean_text(str(msg.get("Subject", "")), 200), "date": sent.isoformat(),
             "message_id": clean_text(str(msg.get("Message-ID", "")), 200)}
    return facts, [seen[k] for k in seen]           # document order


_PRICE = re.compile(r"(current bid|high bid|bid|price|starting at|opening bid)\s*:?\s*\$\s?([0-9][0-9,]*(?:\.[0-9]{2})?)",
                    re.IGNORECASE)
_ENDS = re.compile(r"(?:ends|closes|closing|end date)\s*:?\s*(20[0-9]{2}-[0-9]{2}-[0-9]{2})", re.IGNORECASE)
_PLACE = re.compile(r"\b([A-Z][a-zA-Z .'-]{1,30}),\s*([A-Z]{2})\b(?:\s+([0-9]{5}))?")


# ---------------------------------------------------------------- adapter
class EmailAlertAdapter(SourceAdapter):
    ingestion_method = "email"
    tos_risk = "low"
    access_tier = 2
    lanes = frozenset({"flip"})
    adapter_version = "1.0.0"

    def __init__(self, source: str, reader: MailboxReader, *, lookback_days: int = 7,
                 clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> None:
        if source not in ORIGINS:
            raise ValueError(f"email alert source must be one of {sorted(ORIGINS)}")
        self.source, self.origin, self.reader, self.lookback, self.clock = source, ORIGINS[source], reader, lookback_days, clock

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        now = self.clock()
        try:
            messages = list(self.reader.messages(now - timedelta(days=self.lookback)))
        except PermissionError as e:
            res.error = SourceError("config", str(e))
            return res
        except FileNotFoundError as e:
            res.error = SourceError("config", str(e))
            return res
        except (OSError, ConnectionError, imaplib.IMAP4.error) as e:
            res.error = SourceError("network", f"mailbox: {type(e).__name__}: {e}")
            return res
        res.requests_made = len(messages)
        for raw in messages:
            if not self._from_origin(raw):
                continue                                # another sender's mail: not ours to read or retain
            src = raw.decode("utf-8", "replace")
            try:
                _, listings = parse_alert(self.origin, raw)
            except NormalizationError:
                listings = [None]                       # keep one record so the message is retained + quarantined
            except Exception:  # noqa: BLE001
                listings = [None]
            for i, _ in enumerate(listings):
                payload = {"origin": self.source, "email_source": src, "listing_index": i}
                try:
                    res.records.append(RawRecord(raw_json_bytes(payload), payload, now, f"mailbox://{self.source}"))
                except CanonicalError:
                    res.records.append(RawRecord(raw, None, now, f"mailbox://{self.source}"))
        return res

    def _from_origin(self, raw: bytes) -> bool:
        try:
            sender = parseaddr(str(email.message_from_bytes(raw, policy=email.policy.default).get("From", "")))[1]
        except Exception:  # noqa: BLE001
            return False
        dom = sender.lower().rsplit("@", 1)[-1]
        return dom == self.origin.domain or dom.endswith("." + self.origin.domain)

    def normalize(self, payload: dict, fetched_at: datetime) -> Normalized:
        if not isinstance(payload, dict) or payload.get("origin") != self.source:
            raise NormalizationError("not an alert payload for this origin")
        facts, listings = parse_alert(self.origin, payload["email_source"].encode("utf-8"))
        i = payload.get("listing_index")
        if not isinstance(i, int) or not (0 <= i < len(listings)):
            raise NormalizationError("alert contains no listing at this index")
        lst = listings[i]
        ctx = lst.context
        if self.origin.event_sale:
            category, matched = "other_asset", False        # an estate sale is an event; needs_review
        else:
            category, matched = classify("flip", match_text(lst.title), match_text(lst.title, ctx))
        pm = _PRICE.search(ctx)
        amount = money(pm.group(2)) if pm else None
        if self.origin.opportunity_kind == "auction_lot":
            kind_word = (pm.group(1).lower() if pm else "")
            ptype = "auction_current" if "current" in kind_word or "high" in kind_word else "starting_bid"
        else:
            ptype = "fixed"
        price = {"currency": "USD", "type": ptype} | ({"amount": amount} if amount is not None else {})
        em = _ENDS.search(ctx)
        # INFERENCE: alert times carry no reliable timezone, so the date is used as an end-of-day UTC upper bound
        # (as for GSA); RESEARCH confirms the exact close before any bid recommendation.
        ends_at = norm_ts(f"{em.group(1)}T23:59:59+00:00") if em else None
        loc = {}
        lm = _PLACE.search(ctx)
        if lm:
            loc = {k: v for k, v in {"city": lm.group(1).strip(), "state": lm.group(2), "zip": lm.group(3)}.items() if v}
        normalized = {"title": lst.title, "condition": "unknown", "price": price,
                      "counterparty": {"role": "agency" if self.origin.opportunity_kind == "auction_lot" else "seller",
                                       "contact_method": "platform"},
                      "listing_status": "active", "images": []}
        if ctx:
            normalized["description"] = clean_text(ctx, MAX_DESCRIPTION)
        if ends_at:
            normalized["ends_at"] = ends_at
        if loc:
            normalized["location"] = loc
        flags = base_flags(price=price, bid_count=None, ends_at=ends_at, fetched_at=fetched_at, matched=matched,
                           tier=None, texts=(lst.title, ctx, facts["subject"]))
        if flags:
            normalized["flags"] = flags
        return Normalized(source_listing_id=lst.listing_id, url=lst.url, type="flip", category=category,
                          opportunity_kind=self.origin.opportunity_kind, normalized=normalized,
                          subcategory="estate sale" if self.origin.event_sale else None)
