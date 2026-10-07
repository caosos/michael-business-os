"""F-07: consent ledger + DNC scrub store. Data only, dry-run. Nothing here contacts anyone.

* Insert-only tables in schema `mbos_comms` (`sql/0001_comms_ledger.sql`; PROPOSED for lane D to adopt).
* Every consent change and every DNC scrub result is written in ONE transaction with a hash-chained
  receipt in `mbos.receipts` (`mbos.ledger.append_receipt`), plus provenance. No receipt carries a raw
  contact value: they reference `contact_ref` only.
* `ConsentLedger.consent_lookup` / `.dnc_lookup` match the `CommsDryRunEffector` hooks. With the ledger
  wired, a missing consent record means "not_found", which BLOCKS. That is how E2 grades PASS/FAIL
  instead of DRY_RUN_EXEMPT.

Receipt types: frozen v1.0.0 has no consent/DNC event types. Consent is recorded as GRANT_CREATED (granted)
or GRANT_REVOKED (revoked or STOP), with `entity_type="consent"`. A DNC scrub is GRANT_CREATED (clear) or
GRANT_REVOKED (listed), with `entity_type="dnc_scrub"`. ADR-0009 is asked for CONSENT_RECORDED /
CONSENT_REVOKED / DNC_SCRUB_RECORDED.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import sqlalchemy as sa
from ulid import ULID

import comms_spec as cs
from mbos.clock import iso, utcnow
from mbos.ledger import append_receipt, record_provenance

SQL = Path(__file__).resolve().parent / "sql" / "0001_comms_ledger.sql"
ACTOR = {"type": "agent", "id": "agent-06-communications"}
TOOL = "comms_spec.ledger"
VERSION = "0.1.0"


def ensure_schema(engine: sa.Engine) -> None:
    with engine.begin() as conn:  # raw driver call: no parameter parsing, so plpgsql '%' format specs survive
        conn.connection.driver_connection.execute(SQL.read_text())


def _norm(channel: str, value: str) -> str:
    v = value.strip()
    if channel == "email":
        return v.lower()
    digits = "".join(ch for ch in v if ch.isdigit())
    return "+1" + digits[-10:] if len(digits) >= 10 else digits


def register_contact(conn: sa.Connection, subject_ref: str, channel: str, value: str) -> str:
    """Store a raw contact value once; return its opaque contact_ref. Idempotent on (channel, value)."""
    if channel not in cs.CHANNELS:
        raise ValueError(f"unknown channel {channel!r}")
    v = _norm(channel, value)
    row = conn.execute(sa.text("SELECT contact_ref FROM mbos_comms.contacts WHERE channel = :c AND value = :v"),
                       {"c": channel, "v": v}).one_or_none()
    if row:
        return row.contact_ref
    ref = f"cref_{ULID()}"
    conn.execute(sa.text("INSERT INTO mbos_comms.contacts (contact_ref, subject_ref, channel, value) "
                         "VALUES (:r, :s, :c, :v)"), {"r": ref, "s": subject_ref, "c": channel, "v": v})
    return ref


def _receipt(conn, rtype: str, entity_type: str, contact_ref: str, intent: str, prov: str, after: dict) -> dict:
    return append_receipt(conn, type=rtype, intent=intent, provenance_ids=[prov], actor=ACTOR,
                          entity_type=entity_type, entity_id=contact_ref, effect="create", tool_name=f"{TOOL}@{VERSION}",
                          after_state=after, details={"kind": "comms", "dry_run": True, "contact_ref": contact_ref})


def record_consent(conn: sa.Connection, contact_ref: str, basis: str, evidence_uri: str,
                   at: Optional[datetime] = None) -> dict:
    """Record that the contact consented (with evidence). One transaction: event + provenance + receipt."""
    at = at or utcnow()
    prov = record_provenance(conn, actor_type="agent", agent_name=ACTOR["id"], basis="FACT",
                             source_uri=evidence_uri, fetched_at=iso(at))
    r = _receipt(conn, "GRANT_CREATED", "consent", contact_ref, f"consent recorded ({basis})", prov,
                 {"consent": "granted", "basis": basis})
    conn.execute(sa.text("INSERT INTO mbos_comms.consent_events (contact_ref, event, basis, evidence_uri, recorded_at, receipt_id) "
                         "VALUES (:c, 'granted', :b, :e, :t, :r)"),
                 {"c": contact_ref, "b": basis, "e": evidence_uri, "t": at, "r": r["receipt_id"]})
    return r


def revoke_consent(conn: sa.Connection, contact_ref: str, basis: str = "stop_keyword",
                   evidence_uri: Optional[str] = None, at: Optional[datetime] = None) -> dict:
    """Opt-out / revocation. Permanent until a NEW written opt-in is recorded."""
    at = at or utcnow()
    prov = record_provenance(conn, actor_type="system", agent_name=ACTOR["id"], basis="FACT",
                             tool_name=TOOL, tool_version=VERSION)
    r = _receipt(conn, "GRANT_REVOKED", "consent", contact_ref, f"consent revoked ({basis})", prov,
                 {"consent": "revoked", "basis": basis})
    conn.execute(sa.text("INSERT INTO mbos_comms.consent_events (contact_ref, event, basis, evidence_uri, recorded_at, receipt_id) "
                         "VALUES (:c, 'revoked', :b, :e, :t, :r)"),
                 {"c": contact_ref, "b": basis, "e": evidence_uri, "t": at, "r": r["receipt_id"]})
    return r


def handle_inbound(conn: sa.Connection, contact_ref: str, text: str, at: Optional[datetime] = None) -> Optional[dict]:
    """E4: an inbound STOP-class message revokes consent in the same transaction it is processed."""
    return revoke_consent(conn, contact_ref, "stop_keyword", at=at) if cs.is_opt_out(text) else None


def record_dnc_scrub(conn: sa.Connection, contact_ref: str, listed: bool, source: str = "national_dnc_registry",
                     at: Optional[datetime] = None) -> dict:
    at = at or utcnow()
    prov = record_provenance(conn, actor_type="system", agent_name=ACTOR["id"], basis="FACT",
                             tool_name=f"dnc_scrub:{source}", tool_version=VERSION)
    r = _receipt(conn, "GRANT_REVOKED" if listed else "GRANT_CREATED", "dnc_scrub", contact_ref,
                 f"DNC scrub against {source}: {'LISTED' if listed else 'not listed'}", prov,
                 {"dnc": "listed" if listed else "clear", "source": source, "scrubbed_at": iso(at)})
    conn.execute(sa.text("INSERT INTO mbos_comms.dnc_scrubs (contact_ref, scrubbed_at, listed, source, receipt_id) "
                         "VALUES (:c, :t, :l, :s, :r)"),
                 {"c": contact_ref, "t": at, "l": listed, "s": source, "r": r["receipt_id"]})
    return r


class ConsentLedger:
    """Read side, shaped for `CommsDryRunEffector(consent_lookup=…, dnc_lookup=…)`. Keys: (recipient.ref, channel)."""

    def __init__(self, engine: sa.Engine):
        self.engine = engine

    def _contact(self, conn, ref: str, channel: str) -> Optional[str]:
        row = conn.execute(sa.text("SELECT contact_ref FROM mbos_comms.contacts WHERE subject_ref = :s AND channel = :c "
                                   "ORDER BY created_at DESC LIMIT 1"), {"s": ref, "c": channel}).one_or_none()
        return row.contact_ref if row else None

    def consent_lookup(self, ref: str, channel: str) -> dict[str, Any]:
        with self.engine.connect() as conn:
            cref = self._contact(conn, ref, channel)
            if cref is None:
                return {"result": "not_found", "reason": "no contact on file for this recipient/channel"}
            ev = conn.execute(sa.text("SELECT event, basis, evidence_uri, receipt_id FROM mbos_comms.consent_events "
                                      "WHERE contact_ref = :c ORDER BY seq DESC LIMIT 1"), {"c": cref}).one_or_none()
        if ev is None:
            return {"result": "not_found", "reason": "no consent recorded", "contact_ref": cref}
        if ev.event == "revoked":
            return {"result": "fail", "reason": f"consent revoked ({ev.basis})", "contact_ref": cref, "receipt_id": ev.receipt_id}
        return {"result": "pass", "reason": f"consent on file ({ev.basis})", "basis": ev.basis,
                "evidence_uri": ev.evidence_uri, "contact_ref": cref, "receipt_id": ev.receipt_id}

    def dnc_lookup(self, ref: str, channel: str) -> tuple[Optional[datetime], Optional[bool], bool]:
        with self.engine.connect() as conn:
            cref = self._contact(conn, ref, channel)
            if cref is None:
                return None, None, False
            scrub = conn.execute(sa.text("SELECT scrubbed_at, listed FROM mbos_comms.dnc_scrubs WHERE contact_ref = :c "
                                         "ORDER BY seq DESC LIMIT 1"), {"c": cref}).one_or_none()
            last = conn.execute(sa.text("SELECT event FROM mbos_comms.consent_events WHERE contact_ref = :c "
                                        "ORDER BY seq DESC LIMIT 1"), {"c": cref}).scalar_one_or_none()
        suppressed = last == "revoked"
        return (scrub.scrubbed_at, scrub.listed, suppressed) if scrub else (None, None, suppressed)
