"""B-23: Arkansas auction fixtures normalize with every field + freshness; distance filter; offline guarantee."""
import socket
from datetime import datetime, timezone

import pytest

from conftest import FIX
from mbos_discovery import auctions as A
from mbos_discovery.adapter import SearchProfile

NOW = datetime(2026, 10, 9, 13, 0, tzinfo=timezone.utc)
P = SearchProfile("auctions", "flip")


def _ad(**kw):
    return A.AuctionFixtureAdapter("govdeals", FIX / "auctions", clock=lambda: NOW, **kw)


def test_distance_filter_keeps_100_miles_drops_rest():
    recs = _ad().fetch(P).records
    ids = {r.payload["lot_id"] for r in recs}
    assert ids == {"A1", "A2", "A3"}          # Fayetteville, Jonesboro (~105mi) and Memphis (TN) out
    assert not ids & {"A4", "A5", "A6"}


def test_statewide_only_when_exceptional():
    ids = {r.payload["lot_id"] for r in _ad(exceptional=lambda l: l["lot_id"] == "A4").fetch(P).records}
    assert "A4" in ids and "A6" not in ids           # exceptional margin lifts AR only, never other states


def test_all_fields_with_source_and_freshness():
    ad = _ad()
    lot = {r.payload["lot_id"]: ad.lot(r.payload, NOW) for r in ad.fetch(P).records}
    a1 = lot["A1"]
    assert set(A.LOT_FIELDS) <= set(a1.fields)
    assert a1.get("current_bid") == 450 and a1.get("bid_count") == 3 and a1.get("buyer_premium_pct") == 10
    assert a1.get("sales_tax_pct") == 6.5 and a1.get("closes_at") == "2026-10-12T20:00:00Z"
    assert all(f.source.startswith("fixture://") and f.observed_at for f in a1.fields.values())
    assert a1.fields["current_bid"].age_seconds == 3600 and not a1.fields["current_bid"].stale
    assert lot["A3"].fields["current_bid"].stale                      # observed 12h earlier
    assert lot["A2"].get("sales_tax_pct") == A.UNKNOWN and lot["A2"].fields["sales_tax_pct"].basis == "UNKNOWN"
    assert a1.distance_miles < 1


def test_vehicle_category_and_item_normalization():
    ad = _ad()
    out = {r.payload["lot_id"]: ad.normalize(r.payload, NOW) for r in ad.fetch(P).records}
    v = out["A2"]
    assert v.category == "project_vehicle" and v.subcategory == "vehicle" and v.opportunity_kind == "auction_lot"
    assert out["A1"].category == "mower" and out["A1"].normalized["price"]["buyer_premium_pct"] == 10
    assert "zero_bid" in out["A3"].normalized["flags"] and "needs_review" in out["A3"].normalized["flags"]  # stale
    assert out["A1"].normalized["location"]["geo_tier"] == 0


def test_house_terms_inventory_is_honest():
    assert "govdeals" in A.HOUSES and "ar_state_surplus" in A.HOUSES
    h = A.HOUSES["govdeals"]
    assert not h.terms_verified and "deposit" in h.unknown_terms() and "online_bidding_public" in h.unknown_terms()
    assert A.house_terms_gap("nope") == ["house not in inventory"]


def test_offline_guarantee(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("network touched")
    monkeypatch.setattr(socket.socket, "connect", boom)
    monkeypatch.setattr(socket, "create_connection", boom)
    monkeypatch.setattr(socket, "getaddrinfo", boom)
    ad = _ad()
    res = ad.fetch(P)
    assert res.ok and res.requests_made == 0
    for r in res.records:
        ad.normalize(r.payload, NOW)
    assert not hasattr(ad, "http") and not any(m in dir(ad) for m in ("bid", "place_bid", "contact"))


def test_missing_fixture_is_error_not_crash():
    res = A.AuctionFixtureAdapter("hibid", FIX / "auctions").fetch(P)
    assert res.error and res.error.kind == "parse"
