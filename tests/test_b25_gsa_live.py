"""B-25: GSA live adapter on a recorded slice of the real active-auctions.json (2026-10-09; contact fields redacted)."""
import socket
from datetime import datetime, timedelta, timezone

from conftest import FIX
from mbos_discovery import gsa_live as G
from mbos_discovery.adapter import SearchProfile
from mbos_discovery.http import CallbackTransport, HttpResponse

NOW = datetime(2026, 10, 9, 19, 30, tzinfo=timezone.utc)
BODY = (FIX / "gsa_live" / "active-auctions.json").read_bytes()
S3 = "https://gsa-ppms.s3.us-east-1.amazonaws.com/active-auctions.json?X-Amz-Signature=x"
P = SearchProfile("gsa", "flip")
TRAILER = "3-1-QSC-I-27-006-005"


def _t(redirect=S3, status=303):
    def h(method, url, headers, body):
        if "api.gsa.gov" in url:
            return HttpResponse(status, b"", {"Location": redirect})
        return HttpResponse(200, BODY)
    return CallbackTransport(h)


def _ad(tmp_path, t=None, live=True, now=NOW):
    return G.GsaLiveAdapter(tmp_path / "c.json", live=live, transport=t or _t(), clock=lambda: now)


def test_follows_303_one_fetch_filters_states_and_caches(tmp_path):
    t = _t()
    ad = _ad(tmp_path, t)
    res = ad.fetch(P)
    assert res.ok and res.requests_made == 1 and len(t.calls) == 2           # API hop + its 303 target
    assert "DEMO_KEY" in t.calls[0][1] and "amazonaws.com" in t.calls[1][1]
    assert len(res.records) == 8 and ad.summary["lots_in_file"] == 9         # California lot dropped, TX + AR kept
    assert all(r.payload["propertyState"] in G.NEARBY_STATES for r in res.records)
    # second run inside the TTL: cache, zero requests
    t2 = _t()
    res2 = _ad(tmp_path, t2, now=NOW + timedelta(minutes=10)).fetch(P)
    assert res2.requests_made == 0 and not t2.calls and len(res2.records) == 8


def test_real_arkansas_trailer_is_an_item_with_url_photo_provenance(tmp_path):
    ad = _ad(tmp_path)
    recs = {ad.lot(r.payload, NOW).lot_id: r for r in ad.fetch(P).records}
    r = recs[TRAILER]
    n = ad.normalize(r.payload, NOW)
    assert n.source_listing_id == TRAILER and n.category == "trailer" and n.opportunity_kind == "auction_lot"
    assert n.url == "https://www.gsaauctions.gov/auctions/preview/378501"
    assert n.match_hints["image_urls"][0].startswith("https://www.ppms.gov/")
    assert n.normalized["price"] == {"currency": "USD", "type": "auction_current", "amount": 25.0}
    assert n.normalized["bid_count"] == 1 and n.normalized["location"]["city"] == "Marianna"
    assert n.normalized["location"]["state"] == "AR" and n.normalized["ends_at"] == "2026-10-12T23:59:59Z"
    lot = ad.lot(r.payload, NOW)
    assert lot.get("lot_info") == r.payload["lotInfo"]                       # verbatim
    assert all(f.source.startswith("https://api.gsa.gov/") and "DEMO_KEY" not in f.source and f.observed_at
               for f in lot.fields.values())


def test_never_invents_premium_or_sold(tmp_path):
    ad = _ad(tmp_path)
    for r in ad.fetch(P).records:
        lot, n = ad.lot(r.payload, NOW), ad.normalize(r.payload, NOW)
        assert "buyer_premium_pct" not in n.normalized["price"]
        assert lot.get("buyer_premium_pct") == G.UNKNOWN and lot.get("sold_price") == G.UNKNOWN
        assert n.normalized["price"]["type"] in ("auction_current", "starting_bid")    # never sold
    nobid = next(ad.normalize(r.payload, NOW) for r in ad.fetch(P).records if r.payload["highBidAmount"] is None)
    assert nobid.normalized["price"] == {"currency": "USD", "type": "starting_bid"}


def test_zero_results_and_errors_truthful(tmp_path):
    ad = G.GsaLiveAdapter(tmp_path / "z.json", live=True, states=frozenset({"ZZ"}),
                          transport=_t(), clock=lambda: NOW)
    res = ad.fetch(P)
    assert res.ok and res.records == [] and ad.summary["lots_in_scope"] == 0 and ad.summary["lots_in_file"] == 9
    assert _ad(tmp_path / "x", live=False).fetch(P).error.kind == "config"          # no live, no cache: refuses
    bad = _ad(tmp_path / "y", _t(redirect="https://evil.example/x"))
    assert bad.fetch(P).error.kind == "parse"
    rl = G.GsaLiveAdapter(tmp_path / "r.json", live=True, clock=lambda: NOW,
                          transport=CallbackTransport(lambda *a: HttpResponse(429, b"over limit")))
    assert rl.fetch(P).error.kind == "rate_limited" and rl.fetch(P).requests_made == 1


def test_stale_cache_flags_review_and_offline(tmp_path, monkeypatch):
    _ad(tmp_path).fetch(P)
    def boom(*a, **k):
        raise AssertionError("network touched")
    monkeypatch.setattr(socket, "create_connection", boom)
    later = NOW + timedelta(minutes=30)
    ad = _ad(tmp_path, _t(), live=False, now=later)
    recs = ad.fetch(P).records
    assert recs and not [m for m in ("bid", "place_bid", "contact") if hasattr(ad, m)]
    n = ad.normalize(next(r for r in recs if r.payload["highBidAmount"]).payload, NOW + timedelta(hours=7))
    assert "needs_review" in n.normalized["flags"]
