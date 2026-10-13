"""Truthful source setup and owner-controlled imports."""

from datetime import datetime, timezone

from operator_ui import account_view, market_finds, market_sources, source_onboarding

NOW = datetime(2026, 10, 13, 6, 30, tzinfo=timezone.utc)


def _by_key():
    return {info.key: info for info in market_sources.REGISTRY}


def test_registry_has_requested_sources_and_setup_metadata():
    rows = _by_key()
    for key in ("govdeals", "publicsurplus", "hibid_email", "wooley", "craigslist", "offerup",
                "nahlen", "auctionzip", "half_off_wholesale", "northbay", "bargain_brothers"):
        assert key in rows and rows[key].user_setup
    assert rows["govdeals"].parser == "alert parser ready"
    assert rows["publicsurplus"].parser == "alert parser ready"
    assert rows["craigslist"].parser == "alert parser ready"
    assert rows["hibid_email"].parser == "not implemented"
    assert rows["northbay"].setup_url is None


def test_onboarding_never_promotes_unproven_source(monkeypatch, tmp_path):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setenv("MBOS_ACCOUNT_DELIVERY_FILE", str(tmp_path / "delivery.json"))
    monkeypatch.setenv("MBOS_INTAKE_MAIL_DOMAIN", "mail.dealsniffers.com")
    monkeypatch.setenv("MBOS_INTAKE_ALIAS_SECRET_ENV", "TEST_ALIAS_SECRET")
    monkeypatch.setenv("TEST_ALIAS_SECRET", "x" * 40)
    rows = {r["info"].key: r for r in source_onboarding.entries("local-owner", NOW)}
    assert rows["govdeals"]["state"] == "NOT CONNECTED"
    assert rows["publicsurplus"]["state"] == "NOT CONNECTED"
    assert rows["hibid_email"]["state"] == "NOT CONNECTED"
    assert rows["offerup"]["state"] == "MANUAL"
    assert rows["northbay"]["state"] == "MANUAL"
    rendered = source_onboarding.render("local-owner", NOW)
    assert "alerts-" in rendered and "remains <b>NOT CONNECTED</b>" in rendered
    assert "ALERT PARSER READY" in rendered and "NOT IMPLEMENTED" in rendered
    assert "A setup link does not mean the source is connected" in rendered


def test_settings_exposes_setup_without_source_passwords(monkeypatch, tmp_path):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.setenv("MBOS_ACCOUNT_DELIVERY_FILE", str(tmp_path / "delivery.json"))
    html = account_view.render("csrf", {"configured": False})
    assert "id='source-onboarding'" in html
    assert "DealSniffer never asks for a source password" in html
    assert "GovDeals" in html and "Public Surplus" in html and "Nahlen Auctions" in html
    assert "Half Off Wholesale" in html and "NorthBay Tool Liquidation Pallets" in html
    assert "data-source='hibid_email' data-state='NOT CONNECTED'" in html


def test_manual_source_import_keeps_original_url_and_provenance(monkeypatch, tmp_path):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    original = "https://www.auctionzip.com/Listings/123.html?utm_source=owner#photos"
    msg = market_finds.act("add", {"link": original, "title": "Farm equipment auction", "price": "250",
                                    "location": "Conway, AR", "condition": "used", "source": "auctionzip", "notes": "owner observed"})
    assert "owner-entered" in msg
    record = next(iter(market_finds.load().values()))
    assert record["link"] == original
    assert record["provenance"] == {"method": "owner_import", "source": "auctionzip", "original_url": original,
                                      "recorded_by": market_finds.WHO, "recorded_at": record["created_at"]}
    card = market_finds.card(record, None)
    assert card["url"] == original and card["provenance"]["original_url"] == original


def test_find_counts_are_per_source(monkeypatch, tmp_path):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    common = {"price": "", "location": "Conway, AR", "condition": "used", "notes": ""}
    market_finds.act("add", {**common, "source": "offerup", "title": "Mower", "link": "https://offerup.com/item/detail/1"})
    market_finds.act("add", {**common, "source": "auctionzip", "title": "Trailer event", "link": "https://www.auctionzip.com/1"})
    rows = _by_key()
    assert market_sources.probe(rows["offerup"], NOW)["n"] == 1
    assert market_sources.probe(rows["auctionzip"], NOW)["n"] == 1
    assert market_sources.probe(rows["northbay"], NOW)["n"] == 0


def test_selected_manual_source_filters_owner_imports(monkeypatch, tmp_path):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    common = {"price": "", "location": "Conway, AR", "condition": "used", "notes": ""}
    market_finds.act("add", {**common, "source": "offerup", "title": "Mower", "link": "https://offerup.com/item/detail/1"})
    market_finds.act("add", {**common, "source": "auctionzip", "title": "Trailer event", "link": "https://www.auctionzip.com/1"})
    from operator_ui import market_search
    prefs = {"enabled": False, "hidden": {}}
    q = market_search.parse_query({"source": ["auctionzip"], "base": ["Conway, AR"], "radius": ["50"], "broad": ["1"]})
    checked, unchecked, *_ = market_finds.cards(q, prefs)
    assert {c["source_key"] for c in checked + unchecked} == {"auctionzip"}
