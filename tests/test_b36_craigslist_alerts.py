"""B-36: Craigslist saved-search alert e-mails -> Items. FIXTURE e-mails only; no network; PEEK/EXAMINE only."""

from __future__ import annotations

from conftest import FIX
from mbos_discovery import contract
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import EmailAlertAdapter, EmlDirReader, ImapReader
from mbos_discovery.policy import Disposition, policy_for
from test_b06_email_alerts import FakeImap

MAIL = FIX / "craigslist_mail"
PROFILE = SearchProfile("alerts", "flip")


def _run(world):
    ad = EmailAlertAdapter("craigslist_email", EmlDirReader(MAIL), clock=world.clock)
    return ad, world.run([(ad, PROFILE)]).sources[0]


def _items(world):
    return {s["source_listing_id"]: i for i in world.store.items.values() for s in i["sources"]
            if s["source"] == "craigslist_email"}


def test_policy_allows_alert_email_only():
    assert policy_for("craigslist_email").disposition is Disposition.ALLOWED
    assert policy_for("craigslist").disposition is Disposition.PENDING_MICHAEL      # site itself stays unfetched


def test_multi_result_alert_regions_and_dedupe(world):
    _, s = _run(world)
    items = _items(world)
    # 3 mails; spoof quarantined; 7712345001 repeats across alerts -> one Item; offsite link ignored
    assert set(items) == {"7712345001", "7712345002", "7712345003", "7712345004", "7712345005"}
    assert s.quarantined == 1 and len(world.store.items) == 5
    t = items["7712345001"]
    assert t["sources"][0]["url"] == "https://littlerock.craigslist.org/tla/d/conway-utility-trailer-5x10/7712345001.html"
    assert t["normalized"]["title"] == "Utility trailer 5x10 single axle"
    assert t["normalized"]["price"] == {"currency": "USD", "type": "fixed", "amount": 650.0}
    d = t["normalized"]["description"]
    assert "Craigslist region: littlerock" in d and "(as shown, unverified): Conway" in d
    assert "Alert received: 2026-10-13T12:00:00+00:00" in d       # repeated alert: the newest sighting wins
    assert t["normalized"]["location"] == {"state": "AR"}
    for i in world.store.items.values():
        contract.check_item(i)


def test_thumbnail_from_email_only_tracking_query_dropped(world):
    _run(world)
    d = _items(world)["7712345003"]["normalized"]["description"]
    assert "Thumbnail: https://images.craigslist.org/00b0b_fixture_300x300.jpg\n" in d
    ad = EmailAlertAdapter("craigslist_email", EmlDirReader(MAIL), clock=world.clock)
    from mbos_discovery.adapters.email_alerts import ORIGINS, parse_alert
    _, ls = parse_alert(ORIGINS["craigslist_email"], (MAIL / "01-littlerock-fayar.eml").read_bytes())
    assert ls[0].thumb == "https://images.craigslist.org/00a0a_fixture_300x300.jpg" and ls[1].thumb == ""


def test_region_mapping(world):
    _run(world)
    items = _items(world)
    reg = lambda k: [l for l in items[k]["normalized"]["description"].splitlines() if l.startswith("Craigslist region")][0]
    assert reg("7712345003").endswith("fayar") and items["7712345003"]["normalized"]["price"]["amount"] == 4200.0
    assert reg("7712345004").endswith("texarkana") and "location" not in items["7712345004"]["normalized"]   # AR/TX: UNKNOWN
    assert reg("7712345005").endswith("memphis") and items["7712345005"]["normalized"]["location"] == {"state": "TN"}


def test_missing_price_and_thumbnail_stay_unknown(world):
    _run(world)
    n = _items(world)["7712345002"]["normalized"]
    assert "amount" not in n["price"]
    assert "Thumbnail: UNKNOWN" in n["description"]
    assert "Thumbnail: UNKNOWN" in _items(world)["7712345004"]["normalized"]["description"]


def test_spoof_quarantined_and_reread_idempotent(world):
    ad, _ = _run(world)
    assert "7766666666" not in _items(world)
    world.clock.advance(hours=1)
    _, s = _run(world)
    assert (s.created, s.merged, s.updated) == (0, 0, 0)


def test_imap_peek_examine_only(world, monkeypatch):
    class Imap(FakeImap):
        def fetch(self, num, what):
            self.calls.append(("fetch", num, what))
            return "OK", [(b"1 (BODY[] {n}", (MAIL / "01-littlerock-fayar.eml").read_bytes()), b")"]
    monkeypatch.setenv("MBOS_TEST_IMAP_PW", "x")
    box = {}
    r = ImapReader("imap.example.invalid", "me", "MBOS_TEST_IMAP_PW", folder="DealSniffer/Alerts", live=True,
                   connect=lambda h: box.setdefault("c", Imap(h)))
    s = world.run([(EmailAlertAdapter("craigslist_email", r, clock=world.clock), PROFILE)]).sources[0]
    assert s.created == 3
    calls = box["c"].calls
    assert ("select", "DealSniffer/Alerts", True) in calls and ("fetch", b"1", "(BODY.PEEK[])") in calls
    assert {c[0] for c in calls} <= {"connect", "login", "select", "search", "fetch", "logout"}   # no STORE: \\Seen untouched
