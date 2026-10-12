"""B-26: Wooley Auctioneers auction EVENTS from archived real pages (tests/fixtures/wooley, scrubbed; sha256 in
ORIGINAL_SHA256.txt). Offline only: no test makes a network request, and none names a hibid.com URL to fetch."""
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import FIX
from mbos_discovery import auctions as A
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import wooley_site as W
from mbos_discovery.http import CallbackTransport, HttpResponse
from mbos_discovery.policy import Disposition, policy_for

PAGES = FIX / "wooley"
NOW = datetime(2026, 10, 11, 23, 0, tzinfo=timezone.utc)
P = SearchProfile("wooley", "flip")
BRUCK = "t-j-bruck-estate-heavy-equipment-machinery-auction-perryville-arkansas"
SH = "sh-systems-inc-chapter-7-bankruptcy-asset-liquidation-phase-ii-jonesboro-ar"


def _ad(**kw):
    return W.WooleySiteAdapter(PAGES, clock=lambda: NOW, **kw)


def _events():
    ad = _ad()
    return ad, {r.payload["slug"]: ad.lot(r.payload, NOW) for r in ad.fetch(P).records}


def test_both_current_auctions_parsed_past_ones_ignored():
    ad, ev = _events()
    assert set(ev) == {BRUCK, SH}                                   # 12 posts on the page, only 2 are live-auction
    assert ad.summary["events"] == 2 and ad.summary["requests"] == 0


def test_bruck_event_fields():
    _, ev = _events()
    b = ev[BRUCK]
    assert b.get("auctioneer") == "Wooley Auctioneers" and b.get("sale_type") == "ONLINE BIDDING ONLY"
    assert b.get("title").startswith("T.J. Bruck Estate Heavy Equipment")
    assert b.get("begins_at") == "2026-10-01T10:00:00-05:00" and b.get("closes_at") == "2026-10-13T18:00:00-05:00"
    assert b.fields["closes_at"].basis == "FACT"
    assert b.get("buyer_premium_pct") == 10.0
    assert "4 Wagon Track Road" in b.get("address") and "Perryville" in b.get("address")
    assert b.get("location")["city"] == "Perryville" and b.get("location")["state"] == "AR" and b.get("location")["zip"] == "72126"
    assert "Monday, October 12" in b.get("preview") and "10:00 a.m." in b.get("preview")
    assert "Heavy Equipment" in b.get("category_headline") and "Tractors" in b.get("category_headline")
    assert {"Vehicle", "Truck", "RV", "Equipment"} <= set(b.get("category_tags")) and "Active Auctions" not in b.get("category_tags")
    assert b.get("rules_url") == f"https://wooleyauctioneers.com/{BRUCK}/"
    assert b.get("hibid_catalog_url").startswith("https://wooleyauctioneers.hibid.com/catalog/")   # link text only
    assert b.fields["closes_at"].source == b.get("rules_url") and b.fields["closes_at"].observed_at == "2026-10-11T23:00:00Z"
    assert b.distance_miles is not None and b.distance_miles < 100


def test_sh_systems_event_from_card_only():
    _, ev = _events()
    s = ev[SH]
    assert s.get("sale_type") == "ONLINE BIDDING ONLY"
    assert s.get("closes_at") == "2026-10-21T14:00:00-05:00"        # '2:00 PM CT' on 10/21 = CDT (INFERENCE)
    assert s.fields["closes_at"].basis == "INFERENCE" and s.get("begins_at") == "2026-10-07T10:00:00-05:00"
    assert s.get("location") == {"city": "Jonesboro", "state": "AR"} and s.fields["location"].basis == "INFERENCE"
    assert {"Bankruptcy", "Fixtures", "Industrial Equipment"} <= set(s.get("category_tags"))
    for unread in ("buyer_premium_pct", "address", "preview", "hibid_catalog_url"):
        assert s.get(unread) == A.UNKNOWN                            # no detail page archived: never guessed


def test_lot_level_fields_are_unknown():
    _, ev = _events()
    for e in ev.values():
        for name in W.LOT_LEVEL_UNKNOWN:
            f = e.fields[name]
            assert f.value == A.UNKNOWN and f.basis == "UNKNOWN"


def test_repeat_parse_dedups_by_slug_and_is_byte_identical():
    a, b = _ad().fetch(P).records, _ad().fetch(P).records
    assert [r.raw_bytes for r in a] == [r.raw_bytes for r in b]
    assert len({r.payload["slug"] for r in a + b}) == 2
    ad = _ad()
    ids = [ad.normalize(r.payload, NOW).source_listing_id for r in a + b]
    assert sorted(set(ids)) == sorted([BRUCK, SH]) and len(ids) == 4


def test_normalize_item_shape():
    ad = _ad()
    n = {r.payload["slug"]: ad.normalize(r.payload, NOW) for r in ad.fetch(P).records}[BRUCK]
    assert n.url == f"https://wooleyauctioneers.com/{BRUCK}/" and n.opportunity_kind == "auction_lot"
    assert n.normalized["ends_at"] == "2026-10-13T23:00:00Z" and n.normalized["price"]["buyer_premium_pct"] == 10.0
    assert "amount" not in n.normalized["price"] and "bid_count" not in n.normalized and n.normalized["images"] == []
    assert "needs_review" in n.normalized["flags"] and n.normalized["counterparty"]["name"] == "Wooley Auctioneers"


def test_policy_and_house_registered():
    assert policy_for("wooley_auctioneers").disposition is Disposition.ALLOWED
    assert policy_for("hibid").disposition is Disposition.PENDING_MICHAEL
    assert "wooley_auctioneers" in A.HOUSES


# ---- live path: OFF by default, hibid refused, crawl-delay, honest errors --------------------------------------------
def test_live_flag_off_by_default_and_no_request_made():
    ct = CallbackTransport(lambda *a: pytest.fail("network used with live off"))
    ad = W.WooleySiteAdapter(PAGES, transport=ct, clock=lambda: NOW)
    assert ad.live is False and ad.fetch(P).ok and ct.calls == []
    res = W.WooleySiteAdapter(None, transport=ct).fetch(P)          # live off and no archive: honest config error
    assert res.error and res.error.kind == "config" and ct.calls == []


@pytest.mark.parametrize("url", ["https://wooleyauctioneers.hibid.com/catalog/1", "https://hibid.com/x", "https://www.hibid.com/y"])
def test_adapter_refuses_any_hibid_fetch(url):
    ct = CallbackTransport(lambda *a: HttpResponse(200, b""))
    ad = W.WooleySiteAdapter(PAGES, live=True, transport=ct, sleep=lambda s: None)
    with pytest.raises(W.HibidRefused):
        ad._get(url)
    assert ct.calls == []
    body, err = ad._get("https://example.com/")                      # any other host: refused too, no request
    assert body is None and err.kind == "config" and ct.calls == []


def _live(handler=None, **kw):
    pages = {"https://wooleyauctioneers.com/auctions/": (PAGES / "auctions.html").read_bytes(),
             f"https://wooleyauctioneers.com/{BRUCK}/": (PAGES / f"{BRUCK}.html").read_bytes(),
             f"https://wooleyauctioneers.com/{SH}/": b"<html>no detail</html>"}
    t = {"now": 1000.0}
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t["now"] += s

    def h(method, url, headers, body):
        t["now"] += 0.5
        return handler(method, url, headers, body) if handler else HttpResponse(200, pages[url])
    ct = CallbackTransport(h)
    ad = W.WooleySiteAdapter(None, live=True, transport=ct, clock=lambda: NOW, sleep=sleep, monotonic=lambda: t["now"], **kw)
    return ad, ct, sleeps


def test_crawl_delay_enforced_with_fake_clock_and_ua_sent():
    seen = []
    ad, ct, sleeps = _live(lambda m, u, hd, b: (seen.append(hd), HttpResponse(200, (PAGES / "auctions.html").read_bytes()
                           if u.endswith("/auctions/") else (PAGES / f"{BRUCK}.html").read_bytes()))[1])
    res = ad.fetch(P)
    assert res.ok and res.requests_made == 3 and [u for _, u in ct.calls][0] == W.LISTING_URL
    assert len(sleeps) == 2 and all(9.4 <= s <= 10.0 for s in sleeps)            # 10 s minus the 0.5 s the request itself took
    assert all(h["User-Agent"] == W.USER_AGENT for h in seen)
    assert all(u.startswith("https://wooleyauctioneers.com/") and "hibid" not in u for _, u in ct.calls)
    assert {r.payload["slug"] for r in res.records} == {BRUCK, SH}
    assert _live(crawl_delay=1.0)[0].crawl_delay == 10.0                          # cannot be configured below robots.txt


def test_http_errors_and_timeouts_are_honest_offline_status():
    ad, ct, _ = _live(lambda *a: HttpResponse(503, b"down"))
    res = ad.fetch(P)
    assert res.error and res.error.kind == "http" and res.error.status == 503 and res.records == [] and len(ct.calls) == 1
    from mbos_discovery.http import TransportError

    def boom(*a):
        raise TransportError("timed out")
    res = _live(boom)[0].fetch(P)
    assert res.error and res.error.kind == "network" and "offline" in res.error.message
    res = _live(lambda *a: HttpResponse(429, b"slow down"))[0].fetch(P)
    assert res.error.kind == "rate_limited" and res.error.is_block


def test_detail_failure_keeps_card_and_429_stops_the_crawl():
    def h(m, u, hd, b):
        return HttpResponse(200, (PAGES / "auctions.html").read_bytes()) if u.endswith("/auctions/") else HttpResponse(404, b"gone")
    ad, ct, _ = _live(h)
    res = ad.fetch(P)
    assert res.ok and len(res.records) == 2 and set(ad.summary["detail_errors"]) == {BRUCK, SH}
    ad, ct, _ = _live(lambda m, u, hd, b: HttpResponse(200, (PAGES / "auctions.html").read_bytes()) if u.endswith("/auctions/") else HttpResponse(429, b"x"))
    res = ad.fetch(P)
    assert res.error and res.error.kind == "rate_limited" and len(ct.calls) == 2   # listing + first detail only


def test_no_hibid_request_anywhere_in_code_or_tests():
    src = Path(W.__file__).read_text()
    assert "hibid" not in W.LISTING_URL and W.SITE_HOST == "wooleyauctioneers.com"
    for needle in ("urlopen(", "requests.", "httpx"):
        assert needle not in src
    assert "http.client" not in src and "socket" not in src


def test_offline_guarantee(monkeypatch):
    def deny(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", deny)
    assert _ad().fetch(P).ok


def test_user_agent_has_no_personal_identity():
    assert W.USER_AGENT == "DealSnifferBot/1.0 (read-only; auction events only)" and "@" not in W.USER_AGENT
    assert "mailto" not in W.USER_AGENT


def test_normalize_premium_only_when_stated_and_no_invented_price_or_condition():
    ad = _ad()
    n = {r.payload["slug"]: ad.normalize(r.payload, NOW) for r in ad.fetch(P).records}
    b, s = n[BRUCK].normalized, n[SH].normalized
    assert b["price"]["buyer_premium_pct"] == 10.0                  # stated on the archived Bruck page
    assert "buyer_premium_pct" not in s["price"]                     # card only: absent, not 0
    for x in (b, s):
        assert "type" not in x["price"] and "amount" not in x["price"] and x["condition"] == "unknown"
        assert "zero_bid" not in x["flags"]


def test_b30_highlights_list_headline_and_event_category():
    ad = _ad()
    recs = {r.payload["slug"]: r for r in ad.fetch(P).records}
    hl = recs[BRUCK].payload["highlights"]
    assert "John Deere 750 crawler dozer" in hl and isinstance(hl, list)
    b = ad.lot(recs[BRUCK].payload, NOW)
    text = " ".join(b.get("highlights")).lower()
    assert "dozer" in text and "john deere" in text
    assert b.get("category_headline").startswith("Heavy Equipment")
    assert b.get("event_category") == "auction event: heavy equipment"
    assert b.get("category") != "trailers"
    n = ad.normalize(recs[BRUCK].payload, NOW)
    assert n.category != "trailers" and "John Deere 750" in n.normalized["description"]
    assert ad.http.log == []                                        # no request at all, so none to hibid
