"""B-27: owner's own bid notifications -> bid events (synthetic fixtures; no network, no mailbox)."""

from __future__ import annotations

from datetime import datetime, timezone

from conftest import FIX
from mbos_discovery.adapters import EmlDirReader, ImapReader
from mbos_discovery.bid_events import BID_ORIGINS, EVENTS, read_bid_events

NOW = datetime(2026, 10, 11, 20, 0, tzinfo=timezone.utc)
DIR = FIX / "bid_mail"


def _all():
    return read_bid_events(EmlDirReader(DIR), clock=lambda: NOW)


def _by(recs):
    return {(r["source"], r["listing_id"], r["event"]): r for r in recs}


def test_every_event_type_and_source_parsed():
    recs, rej = _all()
    by = _by(recs)
    assert {r["event"] for r in recs} == set(EVENTS)
    assert {r["source"] for r in recs} == set(BID_ORIGINS)
    a = by[("govdeals", "1234/5678", "bid_placed")]
    assert a["amount"] == 425.0 and a["closes_at"] == "2026-10-14T20:00:00Z" and a["title"].startswith("Utility Trailer")
    assert a["provenance"] == {"kind": "email", "message_id": "<syn-gd-1@govdeals.com>"}
    assert (a["visibility"], a["origin"], a["observed_at"]) == ("owner_local", "auto_detected", "2026-10-11T20:00:00Z")
    assert by[("govdeals", "1234/5678", "outbid")]["closes_at"] == "2026-10-14T23:59:59Z"
    assert by[("govdeals", "2222/5678", "won")]["amount"] == 1310.5
    assert by[("publicsurplus", "4455667", "winning")]["amount"] == 210.0
    assert "amount" not in by[("publicsurplus", "4455667", "lost")]
    assert by[("gsa_auctions", "24QSCI-001", "bid_placed")]["closes_at"] == "2026-10-20T18:00:00Z"
    assert "amount" not in by[("gsa_auctions", "24QSCI-001", "closed")]
    assert by[("hibid", "98765", "outbid")]["amount"] == 95.0
    assert by[("hibid", "98765", "won")]["url"] == "https://hibid.com/lot/98765/pallet-jack"
    assert len(recs) == 9


def test_dkim_failure_rejected_and_makes_no_record():
    recs, rej = _all()
    assert len(rej) == 1 and "DKIM" in rej[0]["reason"]
    assert not any(r["listing_id"] == "9999/1" for r in recs)


def test_repeat_read_is_idempotent_even_with_duplicate_delivery(tmp_path):
    for p in DIR.glob("*.eml"):
        (tmp_path / p.name).write_bytes(p.read_bytes())
    (tmp_path / "dup.eml").write_bytes((DIR / "01-govdeals-bid-placed.eml").read_bytes())
    first, _ = read_bid_events(EmlDirReader(tmp_path), clock=lambda: NOW)
    second, _ = read_bid_events(EmlDirReader(tmp_path), clock=lambda: NOW)
    assert first == second and len(first) == 9


class _FakeConn:
    def __init__(self):
        self.calls = []
        self.msgs = {b"1": (DIR / "09-hibid-outbid.eml").read_bytes()}

    def login(self, u, p): self.calls.append(("login",))
    def select(self, folder, readonly=False): self.calls.append(("select", folder, readonly)); return "OK", [b"1"]
    def search(self, *a): self.calls.append(("search",) + a); return "OK", [b"1"]
    def fetch(self, num, spec): self.calls.append(("fetch", spec)); return "OK", [(b"1 (BODY[] {1}", self.msgs[num])]
    def logout(self): self.calls.append(("logout",))
    def store(self, *a): raise AssertionError("STORE must never be called")
    def copy(self, *a): raise AssertionError("COPY must never be called")
    def expunge(self): raise AssertionError("EXPUNGE must never be called")


def test_imap_path_is_examine_and_peek_so_seen_is_unchanged():
    conn = _FakeConn()
    rd = ImapReader("imap.invalid", "u", "UNSET_ENV", "DealSniffer/Alerts", live=True, connect=lambda h: conn, password="x")
    recs, _ = read_bid_events(rd, clock=lambda: NOW)
    assert [r["event"] for r in recs] == ["outbid"]
    assert ("select", "DealSniffer/Alerts", True) in conn.calls
    assert ("fetch", "(BODY.PEEK[])") in conn.calls
    assert {c[0] for c in conn.calls} <= {"login", "select", "search", "fetch", "logout"}


def test_off_platform_links_and_foreign_senders_ignored(tmp_path):
    (tmp_path / "x.eml").write_bytes(b"From: a <a@evil.example>\nDate: Sun, 11 Oct 2026 09:00:00 -0500\n"
                                     b"Message-ID: <x@evil.example>\nSubject: You won\n\n<a href=\"https://evil.example/lot/1\">x</a>")
    recs, rej = read_bid_events(EmlDirReader(tmp_path), clock=lambda: NOW)
    assert recs == [] and len(rej) == 1
