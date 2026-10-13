"""B-28: Wilson Auctioneers auction EVENTS from the archived real /auctions/ list page (tests/fixtures/wilson, scrubbed; sha256 in
ORIGINAL_SHA256.txt). Offline only: no test makes a network request, and no bidwrangler.com URL is ever fetched."""
import socket
from datetime import datetime, timezone
from pathlib import Path

import pytest

from conftest import FIX
from mbos_discovery import auctions as A
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.adapters import wilson_site as W
from mbos_discovery.http import CallbackTransport, HttpResponse, TransportError
from mbos_discovery.policy import Disposition, policy_for

PAGES = FIX / "wilson"
NOW = datetime(2026, 10, 12, 1, 7, tzinfo=timezone.utc)
P = SearchProfile("wilson", "flip")
CAMPERS = "personal-property-1082"


def _ad(**kw):
    return W.WilsonSiteAdapter(PAGES, clock=lambda: NOW, **kw)


def _events():
    ad = _ad()
    return ad, {r.payload["slug"]: ad.lot(r.payload, NOW) for r in ad.fetch(P).records}


def test_all_seventeen_events_parsed_from_list_page_without_a_request():
    ad, ev = _events()
    assert len(ev) == 17 and ad.summary["events"] == 17 and ad.summary["requests"] == 0
    assert CAMPERS in ev and "lakefront-1090" in ev


def test_all_events_capture_allowlisted_event_gallery_cover_only():
    records = [r.payload for r in _ad().fetch(P).records]
    assert len(records) == 17 and all("event_image_url" in r for r in records)
    assert all(r["event_image_url"].startswith("https://d37cbsn538t2ha.cloudfront.net/") for r in records)
    assert W._event_image_url("http://d37cbsn538t2ha.cloudfront.net/x.jpg") is None
    assert W._event_image_url("https://evil.example/x.jpg") is None
    assert W._event_image_url("https://wilson.bidwrangler.com/x.jpg") is None


def test_online_only_event_fields_and_cst_is_chicago_local_inference():
    _, ev = _events()
    c = ev[CAMPERS]
    assert c.get("auctioneer") == "Wilson Auctioneers" and c.get("sale_type") == "Online Only"
    assert c.get("title").startswith("ONLINE ONLY NO RESERVE FALL CONSIGNMENT CAMPERS")
    assert c.get("closes_at") == "2026-10-13T19:00:00-05:00"        # page says 'CST' but October is daylight time: -05:00, not -06:00
    assert c.fields["closes_at"].basis == "INFERENCE"
    assert c.get("begins_at") == A.UNKNOWN                           # 'Active': already open, no date stated
    assert c.get("location") == {"city": "Hot Springs", "state": "AR", "zip": "71913"} and "929 Airport Road" in c.get("address")
    assert c.get("highlights") == ["Bumper Pull Campers, Trucks, Jeep Wrangler, Trailers, Farm Tractor, Implements, Side-by-Side, 4-Wheeler"]
    assert c.get("category_tags") == ["personal property"]
    assert c.get("rules_url") == "https://wilsonauctioneers.com/auctions/personal-property/1082"
    assert c.get("event_image_url").startswith("https://d37cbsn538t2ha.cloudfront.net/")
    assert c.distance_miles is not None and c.distance_miles < 100
    assert c.fields["closes_at"].source == c.get("rules_url") and c.fields["closes_at"].observed_at == "2026-10-12T01:07:00Z"


def test_live_simulcast_event_has_start_only_and_standard_time_in_november():
    _, ev = _events()
    h, lr = ev["lakefront-1090"], ev["residential-1069"]
    assert h.get("sale_type") == "Live / Simulcast" and h.get("closes_at") == A.UNKNOWN
    assert h.get("begins_at") == "2026-11-20T11:00:00-06:00"         # November: real CST, so the zone is derived, not fixed
    assert lr.get("begins_at") == "2026-10-14T11:00:00-05:00" and lr.fields["begins_at"].basis == "INFERENCE"


def test_parse_when_variants():
    assert W.parse_when("Oct 13 2026 &ndash;\n\t7:00pm CST") == "2026-10-13T19:00:00-05:00"
    assert W.parse_when("Jan 5 2027 – 12:00am CST") == "2027-01-05T00:00:00-06:00"
    assert W.parse_when("Active") is None and W.parse_when("") is None and W.parse_when("Foo 13 2026 – 7:00pm CST") is None


def test_lot_level_and_unstated_fields_are_unknown():
    _, ev = _events()
    for e in ev.values():
        for name in (*W.LOT_LEVEL_UNKNOWN, "buyer_premium_pct", "preview", "pickup"):
            assert e.fields[name].value == A.UNKNOWN and e.fields[name].basis == "UNKNOWN"


def test_repeat_parse_dedups_by_slug_and_is_byte_identical():
    a, b = _ad().fetch(P).records, _ad().fetch(P).records
    assert [r.raw_bytes for r in a] == [r.raw_bytes for r in b]
    assert len({r.payload["slug"] for r in a}) == 17


def test_normalize_item_shape():
    ad = _ad()
    n = {r.payload["slug"]: ad.normalize(r.payload, NOW) for r in ad.fetch(P).records}[CAMPERS]
    assert n.url.endswith("/auctions/personal-property/1082") and n.opportunity_kind == "auction_lot"
    assert n.normalized["ends_at"] == "2026-10-14T00:00:00Z"
    assert n.normalized["price"] == {"currency": "USD"} and n.normalized["images"] == [] and n.normalized["condition"] == "unknown"
    assert "needs_review" in n.normalized["flags"] and n.normalized["counterparty"]["name"] == "Wilson Auctioneers"


def test_policy_and_house_registered_bidwrangler_forbidden():
    assert policy_for("wilson_auctioneers").disposition is Disposition.ALLOWED
    assert policy_for("bidwrangler").disposition is Disposition.FORBIDDEN
    assert "wilson_auctioneers" in A.HOUSES


# ---- live path: OFF by default, bidwrangler refused, one request, crawl-delay, hourly, honest errors -------------------
def test_live_flag_off_by_default_and_no_request_made():
    ct = CallbackTransport(lambda *a: pytest.fail("network used with live off"))
    ad = W.WilsonSiteAdapter(PAGES, transport=ct, clock=lambda: NOW)
    assert ad.live is False and ad.fetch(P).ok and ct.calls == []
    res = W.WilsonSiteAdapter(None, transport=ct).fetch(P)
    assert res.error and res.error.kind == "config" and ct.calls == []


@pytest.mark.parametrize("url", ["https://wilson.bidwrangler.com/x", "https://bidwrangler.com/y", "https://www.bidwrangler.com/accounts/sign_in"])
def test_adapter_refuses_any_bidwrangler_fetch(url):
    ct = CallbackTransport(lambda *a: HttpResponse(200, b""))
    ad = W.WilsonSiteAdapter(PAGES, live=True, transport=ct, sleep=lambda s: None)
    with pytest.raises(W.BidWranglerRefused):
        ad._get(url)
    body, err = ad._get("https://example.com/")
    assert body is None and err.kind == "config" and ct.calls == []


def _live(handler=None, **kw):
    t = {"now": 1000.0}
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t["now"] += s

    def h(method, url, headers, body):
        t["now"] += 0.5
        return handler(method, url, headers, body) if handler else HttpResponse(200, (PAGES / "auctions.html").read_bytes())
    ct = CallbackTransport(h)
    return W.WilsonSiteAdapter(None, live=True, transport=ct, clock=lambda: NOW, sleep=sleep, monotonic=lambda: t["now"], **kw), ct, sleeps, t


def test_live_makes_exactly_one_request_with_anonymous_ua_and_never_bidwrangler():
    seen = []
    ad, ct, _, _ = _live(lambda m, u, hd, b: (seen.append(hd), HttpResponse(200, (PAGES / "auctions.html").read_bytes()))[1])
    res = ad.fetch(P)
    assert res.ok and res.requests_made == 1 and len(res.records) == 17 and [u for _, u in ct.calls] == [W.LISTING_URL]
    assert seen[0]["User-Agent"] == W.USER_AGENT and "@" not in W.USER_AGENT
    assert all("bidwrangler" not in u for _, u in ct.calls)
    assert ad.crawl_delay == 10.0 and _live(crawl_delay=1.0)[0].crawl_delay == 10.0


def test_at_most_one_live_run_per_hour_and_ten_second_floor():
    ad, ct, sleeps, t = _live(min_run_interval=60.0)                 # cannot be configured below an hour
    assert ad.fetch(P).ok
    again = ad.fetch(P)
    assert again.error and again.error.kind == "config" and again.records == [] and len(ct.calls) == 1
    t["now"] += 3600
    assert ad.fetch(P).ok and len(ct.calls) == 2 and sleeps == []   # the hourly gap already exceeds the 10 s crawl delay


def test_http_errors_and_timeouts_are_honest_offline_status():
    res = _live(lambda *a: HttpResponse(503, b"down"))[0].fetch(P)
    assert res.error and res.error.kind == "http" and res.error.status == 503 and res.records == []

    def boom(*a):
        raise TransportError("timed out")
    res = _live(boom)[0].fetch(P)
    assert res.error and res.error.kind == "network" and "offline" in res.error.message
    res = _live(lambda *a: HttpResponse(429, b"slow down"))[0].fetch(P)
    assert res.error.kind == "rate_limited" and res.error.is_block


def test_no_bidwrangler_request_anywhere_in_code():
    src = Path(W.__file__).read_text()
    assert "bidwrangler" not in W.LISTING_URL and W.SITE_HOST == "wilsonauctioneers.com"
    for needle in ("urlopen(", "requests.", "httpx", "http.client", "socket"):
        assert needle not in src


def test_bidwrangler_link_kept_as_text_only():
    page = (PAGES / "auctions.html").read_text().replace('<a href="/auctions/land/1065">View Auction',
                                                        '<a href="https://wilson.bidwrangler.com/auctions/1065">View Auction', 1)
    evs = W.parse_listing(page)
    assert any(e.get("bidwrangler_url") == "https://wilson.bidwrangler.com/auctions/1065" for e in evs)


def test_offline_guarantee(monkeypatch):
    def deny(*a, **k):
        raise AssertionError("network used")
    monkeypatch.setattr(socket, "socket", deny)
    assert _ad().fetch(P).ok


def test_b31_every_live_simulcast_event_has_parsed_start_and_explicit_unknown_end_reason():
    ad = _ad()
    live = [r.payload for r in ad.fetch(P).records if "live" in r.payload["sale_type"].lower()]
    assert len(live) == 11
    for p in live:
        lot = ad.lot(p, NOW)
        assert lot.get("begins_at") != A.UNKNOWN and lot.fields["begins_at"].basis == "INFERENCE"
        assert lot.get("closes_at") == A.UNKNOWN
        assert "no end time" in lot.get("date_unknown_reason") and "begins_at" not in lot.get("date_unknown_reason")
    assert ad.summary["requests"] == 0


def test_b31_unparseable_or_absent_dates_stay_unknown_with_reason():
    assert W.date_reasons({"sale_type": "Live / Simulcast", "starts_text": "Oct 14 2026 – 11:00am CST"}).keys() == {"closes_at"}
    r = W.date_reasons({"sale_type": "Live / Simulcast", "starts_text": "Oct 14 Live / Simulcast"})
    assert "not parseable" in r["begins_at"]
    assert "no date line" in W.date_reasons({"sale_type": "Live"})["begins_at"]
    assert "Active" in W.date_reasons({"sale_type": "Online Only", "starts_text": "Active", "ends_text": "Oct 13 2026 – 7:00pm CST"})["begins_at"]
    assert W.date_reasons({"sale_type": "Online Only", "starts_text": "Oct 12 2026 – 2:00pm CST", "ends_text": "Oct 14 2026 – 2:00pm CST"}) == {}
