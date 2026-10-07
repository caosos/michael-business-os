"""B-06: saved-search alert e-mails (tier 2). Fixture e-mails → listings; read-only mailbox; spoofed alerts
quarantined; no network in tests."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from conftest import FIX, T0, World
from mbos_discovery import contract
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import EmailAlertAdapter, EmlDirReader, ImapReader
from mbos_discovery.ids import parse_ts
from mbos_discovery.policy import Disposition, policy_for

MAIL = FIX / "email"
ALERTS = SearchProfile("alerts", "flip")


def _run(world, source):
    ad = EmailAlertAdapter(source, EmlDirReader(MAIL), clock=world.clock)
    return ad, world.run([(ad, ALERTS)]).sources[0]


def _items(world, source):
    return {s["source_listing_id"]: i for i in world.store.items.values() for s in i["sources"] if s["source"] == source}


def test_policy_email_is_sanctioned_while_site_scraping_stays_forbidden():
    for s in ("govdeals_email", "publicsurplus_email", "estatesales_net_email"):
        assert policy_for(s).disposition is Disposition.ALLOWED and policy_for(s).tier == 2
    assert policy_for("estatesales_net_site").disposition is Disposition.FORBIDDEN


def test_govdeals_alert_to_items_and_spoof_quarantined(world):
    _, s = _run(world, "govdeals_email")
    assert (s.fetched, s.created, s.quarantined) == (3, 2, 1)       # 2 real listings + the spoofed alert
    items = _items(world, "govdeals_email")
    assert set(items) == {"1234/5678", "2222/5678"}                  # off-domain + unsubscribe links ignored
    t = items["1234/5678"]
    n = t["normalized"]
    assert (t["category"], t["opportunity_kind"]) == ("trailer", "auction_lot")
    assert n["price"] == {"currency": "USD", "type": "auction_current", "amount": 350.0}
    assert n["ends_at"] == "2026-10-08T23:59:59Z" and n["location"] == {"city": "Conway", "state": "AR", "zip": "72032"}
    assert t["sources"][0]["ingestion_method"] == "email" and t["sources"][0]["url"] == "https://www.govdeals.com/asset/1234/5678"
    m = items["2222/5678"]["normalized"]
    assert m["price"] == {"currency": "USD", "type": "starting_bid", "amount": 500.0}
    assert items["2222/5678"]["category"] == "mower"
    assert not any("6666" in k for k in items)                       # spoofed alert produced no Item
    for i in world.store.items.values():
        contract.check_item(i)


def test_spoofed_alert_raw_is_retained_for_audit(world):
    ad = EmailAlertAdapter("govdeals_email", EmlDirReader(MAIL), clock=world.clock)
    rep = world.run([(ad, ALERTS)])
    q, = rep.quarantine
    assert "DKIM" in q["error"]
    assert b"attacker.invalid" in world.raw.get(q["raw_ref"])


def test_publicsurplus_and_estatesales(world):
    _, s = _run(world, "publicsurplus_email")
    assert (s.created, s.quarantined) == (1, 0)
    w = _items(world, "publicsurplus_email")["3456789"]
    assert w["category"] == "welder" and w["normalized"]["price"]["type"] == "auction_current"
    _, s = _run(world, "estatesales_net_email")
    e = _items(world, "estatesales_net_email")["4567890"]
    assert (e["category"], e["subcategory"], e["opportunity_kind"]) == ("other_asset", "estate sale", "buy_item")
    assert "needs_review" in e["normalized"]["flags"]


def test_other_senders_are_skipped_not_retained(world):
    for src in ("govdeals_email", "publicsurplus_email", "estatesales_net_email"):
        ad, _ = _run(world, src)
    blob = b"".join(world.raw.get(r) for r in list(world.raw._objs))
    assert b"news@example.com" not in blob                           # newsletter never read into storage


def test_replay_and_repeat_idempotent(world):
    ad, _ = _run(world, "govdeals_email")
    for item in world.store.items.values():
        s0 = item["sources"][0]
        prov = world.store.provenance[s0["provenance_id"]]
        n = ad.normalize(json.loads(world.raw.get(s0["raw_ref"])), parse_ts(prov["fetched_at"]))
        assert n.normalized == item["normalized"]
    world.clock.advance(hours=1)
    _, s = _run(world, "govdeals_email")
    assert (s.created, s.merged, s.updated) == (0, 0, 0)


# ---------------------------------------------------------------- IMAP is read-only and gated
class FakeImap:
    """Implements only read commands. Any write command (store/copy/move/expunge/append) is an AttributeError."""
    def __init__(self, host):
        self.calls = [("connect", host)]

    def login(self, u, p):
        self.calls.append(("login", u))

    def select(self, folder, readonly=False):
        self.calls.append(("select", folder, readonly))
        return "OK", [b"1"]

    def search(self, charset, *crit):
        self.calls.append(("search",) + crit)
        return "OK", [b"1"]

    def fetch(self, num, what):
        self.calls.append(("fetch", num, what))
        return "OK", [(b"1 (BODY[] {n}", (MAIL / "01-govdeals.eml").read_bytes()), b")"]

    def logout(self):
        self.calls.append(("logout",))


def test_imap_requires_live_flag_and_password(world, monkeypatch):
    made = []
    r = ImapReader("imap.example.invalid", "me", "MBOS_TEST_IMAP_PW", connect=lambda h: made.append(h))
    ad = EmailAlertAdapter("govdeals_email", r, clock=world.clock)
    assert world.run([(ad, ALERTS)]).sources[0].error["kind"] == "config" and made == []
    monkeypatch.delenv("MBOS_TEST_IMAP_PW", raising=False)
    r.live = True
    assert world.run([(ad, ALERTS)]).sources[0].error["kind"] == "config" and made == []


def test_imap_uses_only_readonly_commands(world, monkeypatch):
    monkeypatch.setenv("MBOS_TEST_IMAP_PW", "secret")
    box = {}
    r = ImapReader("imap.example.invalid", "me", "MBOS_TEST_IMAP_PW", live=True,
                   connect=lambda h: box.setdefault("c", FakeImap(h)))
    ad = EmailAlertAdapter("govdeals_email", r, clock=world.clock)
    s = world.run([(ad, ALERTS)]).sources[0]
    assert s.created == 2
    calls = box["c"].calls
    assert ("select", "INBOX", True) in calls                         # EXAMINE (read-only)
    assert ("fetch", b"1", "(BODY.PEEK[])") in calls                   # PEEK: \\Seen untouched
    assert {c[0] for c in calls} <= {"connect", "login", "select", "search", "fetch", "logout"}
    assert all("secret" not in str(c) for c in calls)


def test_email_items_through_spine_seam(tmp_path):
    pytest.importorskip("mbos")
    from conftest import Clock
    from mbos_discovery.spine import discovery_components
    clock = Clock()
    adapters, normalizer, _, _ = discovery_components(
        [(EmailAlertAdapter("govdeals_email", EmlDirReader(MAIL), clock=clock), ALERTS)], raw_dir=tmp_path / "raw",
        clock=clock)
    raws = next(iter(adapters.values())).fetch()
    assert {r.source_listing_id for r in raws} == {"1234/5678", "2222/5678"}
    assert all(normalizer.normalize(r).category in ("trailer", "mower") for r in raws)
