"""Service-lane intake adapter — inbound website-form and referral leads (tier 1: our own channel).

Reads JSON submissions from a local inbox directory (written by the website form handler,
or by Michael recording a referral). Strictly read-only: files are never moved, renamed
or deleted — re-reading is idempotent because the store dedups on submission_id.
The customer's contact details stay in the retained raw payload; the Item carries only
the contact *method*. An unsalted sha256 contact fingerprint lives in the store index for dedup only.

Submission format (intake v1):
    {"submission_id": "...", "received_at": "<ISO-8601 with tz>",
     "service_requested": "...", "description": "...",
     "name": "...", "email": "...", "phone": "...", "preferred_contact": "email|phone|sms",
     "city": "...", "state": "AR", "zip": "72034", "budget": 150}
Customer text is untrusted input: it is scanned for prompt-injection patterns and flagged.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from ..adapter import FetchResult, NormalizationError, Normalized, RawRecord, SearchProfile, SourceAdapter, SourceError
from ..normalize import MAX_DESCRIPTION, base_flags, classify, clean_text, match_text, money, norm_ts

MAX_FILE_BYTES = 256 * 1024
CHANNELS = {"website_lead": "website_form", "referral": "referral"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ServiceIntakeAdapter(SourceAdapter):
    ingestion_method = "inbound_form"
    tos_risk = "low"
    access_tier = 1
    lanes = frozenset({"service"})
    adapter_version = "1.0.0"

    def __init__(self, source: str, inbox_dir: str | Path, clock: Callable[[], datetime] = _utcnow) -> None:
        if source not in CHANNELS:
            raise ValueError(f"intake source must be one of {sorted(CHANNELS)}")
        self.source = source
        self.inbox = Path(inbox_dir)
        self.clock = clock

    def fetch(self, profile: SearchProfile) -> FetchResult:
        res = FetchResult(self.source)
        if not self.inbox.is_dir():
            res.error = SourceError("config", f"intake inbox not found: {self.inbox}")
            return res
        fetched_at = self.clock()
        try:
            paths = sorted(p for p in self.inbox.iterdir() if p.suffix == ".json" and p.is_file())
        except OSError as e:
            res.error = SourceError("network", f"cannot list inbox: {e}")
            return res
        for p in paths:
            try:
                raw = p.read_bytes()[:MAX_FILE_BYTES + 1]
            except OSError:
                continue                            # vanished between list and read; next run picks it up
            res.requests_made += 1
            payload = None
            if len(raw) <= MAX_FILE_BYTES:
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = None                  # retained raw, then quarantined by the pipeline
            res.records.append(RawRecord(raw, payload, fetched_at, f"intake://{CHANNELS[self.source]}/{p.name}"))
        return res

    def normalize(self, sub: dict, fetched_at: datetime) -> Normalized:
        if not isinstance(sub, dict):
            raise NormalizationError("submission is not a JSON object")
        sid = clean_text(sub.get("submission_id"), 100)
        received = norm_ts(sub.get("received_at"))
        if not sid or not received:
            raise NormalizationError("submission_id and timezone-aware received_at are required")
        requested = clean_text(sub.get("service_requested"), 200)
        desc = clean_text(sub.get("description"), MAX_DESCRIPTION)
        if not (requested or desc):
            raise NormalizationError("empty lead: no service_requested or description")
        category, matched = classify("service", match_text(requested), match_text(requested, desc))

        budget = money(sub.get("budget"))
        price = ({"amount": budget, "currency": "USD", "type": "customer_budget"} if budget is not None
                 else {"type": "quote_requested"})
        email = (sub.get("email") or "").strip().lower()
        phone = re.sub(r"\D", "", str(sub.get("phone") or ""))[-10:]
        pref = (sub.get("preferred_contact") or "").lower()
        method = ("phone" if pref in ("phone", "sms") and phone else "email" if email
                  else "phone" if phone else "none")
        counterparty = {"role": "customer", "contact_method": method}
        if sub.get("name"):
            counterparty["name"] = clean_text(sub["name"], 100)

        location = {k: v for k, v in {"city": clean_text(sub.get("city")) or None,
                                      "state": clean_text(sub.get("state")).upper() or None,
                                      "zip": clean_text(sub.get("zip"))[:10] or None}.items() if v}
        normalized = {
            "title": requested or desc[:80],
            "condition": "n/a",
            "price": price,
            "counterparty": counterparty,
            "listing_status": "open",
        }
        if desc:
            normalized["description"] = desc
        if location:
            normalized["location"] = location
        flags = base_flags(price=price, bid_count=None, ends_at=None, fetched_at=fetched_at,
                           matched=matched, tier=None, texts=(requested, desc, clean_text(sub.get("name"))))
        if flags:
            normalized["flags"] = flags

        fp_basis = f"email:{email}" if email else f"phone:{phone}" if phone else None
        hints = {"contact_fp": hashlib.sha256(fp_basis.encode()).hexdigest()} if fp_basis else {}
        return Normalized(source_listing_id=sid, url=f"intake://{CHANNELS[self.source]}/{sid}",
                          type="service", category=category, opportunity_kind="service_lead",
                          normalized=normalized, subcategory=requested[:120] or None, match_hints=hints)
