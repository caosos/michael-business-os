"""Per-user alert-mail ingest (ADR-0015 section 5, B-40).

One dedicated alerts mailbox receives every user's saved-search alerts. The `To:` plus tag
(`alerts+<handle>@...`) resolves to a user. Mail with a missing or unknown tag is quarantined: counted,
never parsed into any feed, and visible only to the owner. A listing's public facts are stored once
(keyed by source + listing id); each user gets a separate interest row. Read-only: the readers used here
PEEK/EXAMINE, so `\\Seen` is never changed. Nothing is fetched from the listing sites.
"""
from __future__ import annotations

import email
import email.policy
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import getaddresses, parseaddr
from typing import Callable, Optional

from .adapters.email_alerts import ORIGINS, MailboxReader, ParsedListing, parse_alert

_TAG = re.compile(r"^([^+@]+)\+([A-Za-z0-9._-]{1,40})@", re.ASCII)
_RECIPIENT_HEADERS = ("Delivered-To", "X-Original-To", "To")


@dataclass(frozen=True)
class Interest:
    user_id: str
    source_id: str
    listing_id: str
    received_at: str


@dataclass(frozen=True)
class QuarantinedMail:
    reason: str
    received_at: str
    message_id: str
    to_tag: str                 # the plus tag as written ("" if none); no body or address is kept


@dataclass
class IngestResult:
    facts: dict[tuple[str, str], ParsedListing] = field(default_factory=dict)       # shared, deduped
    interests: list[Interest] = field(default_factory=list)
    quarantine: list[QuarantinedMail] = field(default_factory=list)
    alert_state: dict[tuple[str, str], str] = field(default_factory=dict)           # (user, source) -> last received

    def feed(self, user_id: str) -> list[tuple[Interest, ParsedListing]]:
        """Only this user's own alerts' listings."""
        return [(i, self.facts[(i.source_id, i.listing_id)]) for i in self.interests if i.user_id == user_id]

    def quarantine_view(self, viewer_is_owner: bool) -> list[QuarantinedMail]:
        return list(self.quarantine) if viewer_is_owner else []


def plus_tag(msg, base_local: str = "alerts") -> Optional[str]:
    """The tag of the first recipient `base_local+<tag>@...`, else None."""
    for h in _RECIPIENT_HEADERS:
        for _, addr in getaddresses([str(v) for v in msg.get_all(h, []) or []]):
            m = _TAG.match(addr.lower())
            if m and m.group(1) == base_local:
                return m.group(2)
    return None


def addressed_untagged(msg, base_local: str) -> bool:
    """True when a recipient is the plain mailbox address `base_local@...` (no plus tag)."""
    for h in _RECIPIENT_HEADERS:
        for _, addr in getaddresses([str(v) for v in msg.get_all(h, []) or []]):
            if addr.lower().rsplit("@", 1)[0] == base_local:
                return True
    return False


def ingest_from_config(reader: MailboxReader, cfg: dict, **kw) -> IngestResult:
    """`cfg` is the `[peruser_alerts]` table: base_local, untagged_user (optional), handles {tag: user_id}."""
    return ingest(reader, cfg.get("handles", {}), base_local=cfg["base_local"],
                  untagged_user=cfg.get("untagged_user"), **kw)


def _origin_for(sender_domain: str):
    for o in ORIGINS.values():
        if sender_domain == o.domain or sender_domain.endswith("." + o.domain):
            return o
    return None


def ingest(reader: MailboxReader, handles: dict[str, str], *, base_local: str = "alerts", untagged_user: Optional[str] = None,
           lookback_days: int = 7,
           clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)) -> IngestResult:
    """`handles` maps plus tag -> user_id. Newest alert wins for a repeated posting's shared facts.

    `untagged_user` (default None: quarantine) receives alerts sent to the plain `base_local@` address, but only
    from authenticated alert senders (parse_alert still DKIM-gates); unknown tags are always quarantined."""
    res = IngestResult()
    handles = {k.lower(): v for k, v in handles.items()}
    newest: dict[tuple[str, str], str] = {}
    for raw in reader.messages(clock() - timedelta(days=lookback_days)):
        try:
            msg = email.message_from_bytes(raw, policy=email.policy.default)
        except Exception:  # noqa: BLE001
            res.quarantine.append(QuarantinedMail("malformed message", "", "", ""))
            continue
        mid, tag = str(msg.get("Message-ID", ""))[:200], plus_tag(msg, base_local)
        domain = parseaddr(str(msg.get("From", "")))[1].lower().rsplit("@", 1)[-1]
        origin = _origin_for(domain)
        if origin is None:
            continue                                    # not an alert sender: not ours to read or retain
        untagged_ok = tag is None and untagged_user is not None and addressed_untagged(msg, base_local)
        if not untagged_ok and (tag is None or tag not in handles):
            res.quarantine.append(QuarantinedMail("no plus tag" if tag is None else "unknown plus tag",
                                                  str(msg.get("Date", ""))[:60], mid, tag or ""))
            continue                                    # body never parsed
        try:
            facts, listings = parse_alert(origin, raw)
        except Exception as e:  # noqa: BLE001
            res.quarantine.append(QuarantinedMail(f"unauthenticated or unparsable: {str(e)[:80]}",
                                                  str(msg.get("Date", ""))[:60], mid, tag or ""))
            continue
        user, received = untagged_user if untagged_ok else handles[tag], facts["date"]
        res.alert_state[(user, origin.source)] = max(res.alert_state.get((user, origin.source), ""), received)
        for l in listings:
            key = (origin.source, l.listing_id)
            if key not in newest or received >= newest[key]:
                newest[key], res.facts[key] = received, l
            res.interests.append(Interest(user, origin.source, l.listing_id, received))
    return res
