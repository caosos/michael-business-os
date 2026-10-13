"""Reviewed everyday-local-deal source registry and import seam."""

from datetime import datetime, timezone

import pytest

from operator_ui import accounts, local_deal_sources as lds, market_detail, market_search, market_source_panel, market_sources

NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)
BASE = {
    "method": "public_offer",
    "source_id": "conway-family-butcher",
    "source_name": "Conway Family Butcher",
    "source_class": "butcher",
    "geography": "Conway, AR",
    "source_offer_id": "beef-2026-10-13",
    "source_url": "https://example.com/specials/beef",
    "title": "Fresh ground beef",
    "category": "food_grocery",
    "description": "Fresh daily",
    "deal_price": "1.99",
    "regular_price": "4.99",
    "unit": "per pound",
    "location": "Conway, AR 72032",
    "availability": "First 100 pounds",
    "terms": "While supplies last",
    "observed_at": "2026-10-13T17:30:00Z",
    "expires_at": "2026-10-14T23:00:00Z",
}


def _row(payload=BASE, import_id="import-1", account=None):
    return lds.normalize(payload, "2026-10-13T18:00:00Z", import_id, account=account)


def test_public_import_is_expiring_imported_and_keeps_provenance():
    row = _row()
    assert row["state"] == "IMPORTED"
    assert row["offer"]["category"] == "food_grocery"
    assert row["offer"]["expires_at"] == "2026-10-14T23:00:00Z"
    assert row["provenance"] == {
        "method": "public_offer", "original_url": BASE["source_url"], "vendor_submission_id": None,
        "authority_attested": None, "recorded_at": "2026-10-13T18:00:00Z", "recorded_by": "michael",
    }


def test_vendor_import_requires_authority_and_submission_provenance():
    vendor = {**BASE, "method": "vendor_submission", "source_url": "", "vendor_submission_id": "deal-a1"}
    with pytest.raises(ValueError, match="authority attestation"):
        _row(vendor)
    row = _row({**vendor, "authority_attested": True})
    assert row["source"]["retrieval_path"] == "vendor submission"
    assert row["provenance"]["vendor_submission_id"] == "deal-a1"
    assert row["provenance"]["original_url"] is None


@pytest.mark.parametrize("change,message", [
    ({"category": "trailers"}, "everyday local-deal"),
    ({"expires_at": "2026-10-13T17:59:59Z"}, "expired offers"),
    ({"observed_at": "2026-10-13T18:01:00Z"}, "cannot be after"),
    ({"source_url": "file:///tmp/deal"}, "public http"),
    ({"regular_price": "1.00"}, "cannot be lower"),
])
def test_import_rejects_unsupported_stale_or_unprovable_records(change, message):
    with pytest.raises(ValueError, match=message):
        _row({**BASE, **change})


def test_store_is_account_isolated_and_expired_rows_leave_feed(tmp_path):
    store = lds.Store(tmp_path / "local-deals.jsonl")
    one = accounts.google_account("one", "one@example.com")
    two = accounts.google_account("two", "two@example.com")
    with accounts.use(one):
        store.append(_row(account=one))
        assert len(store.active(NOW)) == 1
        one_path = store.path
    with accounts.use(two):
        assert store.rows() == []
        two_path = store.path
    assert one_path != two_path and one_path.stat().st_mode & 0o077 == 0
    with accounts.use(one):
        assert store.active(datetime(2026, 10, 15, tzinfo=timezone.utc)) == []
        assert lds.probe(datetime(2026, 10, 15, tzinfo=timezone.utc), store)["status"] == "offline"


def test_imported_offer_uses_common_market_card_and_filters(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_LOCAL_DEALS_FILE", str(tmp_path / "local-deals.jsonl"))
    lds.Store().append(_row())
    data = lds.load(NOW, market_search._origin("72032"))
    card = data["cards"][0]
    assert data["status"] == "imported" and card["source_key"] == "local_deals"
    assert card["price"] == 1.99 and card["unit"] == "per pound"
    assert card["provenance"]["original_url"] == BASE["source_url"]
    q = market_search.parse_query({"cat": ["food_grocery"], "base": ["72032"], "radius": ["30"], "broad": ["1"]})
    checked, unchecked, hidden = market_search.partition(data["cards"], q)
    assert len(checked) == 1 and unchecked == [] and not any(hidden.values())
    detail = market_detail.local_deal_page(card, NOW)
    assert "Deal price</th><td>$1.99 per pound" in detail
    assert "state IMPORTED, not a live vendor connection" in detail
    assert "Current bid" not in detail and "Bid increment" not in detail


def test_authoritative_registry_and_status_ui_are_honest(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_LOCAL_DEALS_FILE", str(tmp_path / "local-deals.jsonl"))
    info = next(i for i in market_sources.REGISTRY if i.key == "local_deals")
    assert market_sources.source_state(info, market_sources.probe(info, NOW)) == "NOT CONNECTED"
    lds.Store().append(_row())
    probe = market_sources.probe(info, NOW)
    assert market_sources.source_state(info, probe) == "IMPORTED"
    html = market_source_panel.render(NOW)
    assert "data-src='local_deals' data-state='IMPORTED'" in html
    assert "1 active reviewed import(s)" in html
    assert "imports are not a live connection" in html


def test_all_source_loader_includes_reviewed_import_but_not_as_live(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_LOCAL_DEALS_FILE", str(tmp_path / "local-deals.jsonl"))
    monkeypatch.setenv("MBOS_GSA_CACHE", str(tmp_path / "missing-gsa.json"))
    monkeypatch.setenv("MBOS_FACEBOOK_CACHE", str(tmp_path / "missing-facebook.json"))
    lds.Store().append(_row())
    data = market_sources.load_source("all", None, NOW, market_search._origin("72032"), query={})
    assert data["status"] == "imported"
    assert [c["source_key"] for c in data["cards"]] == ["local_deals"]
    local = next(c for c in data["coverage"] if c["name"] == lds.SOURCE_NAME)
    assert local["status"] == "imported" and local["in_scope"] == 1
