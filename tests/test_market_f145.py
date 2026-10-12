"""F-145 (B-12 sub-step): the source seam over lane 02's EmailAlertAdapter + EmlDirReader, offline, scrubbed .eml fixtures (tests/fixtures/alerts)."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from operator_ui import market_search as ms, market_sources as msrc
from tests.test_market_f47 import cache, get, req, ui  # noqa: F401

MAIL = Path(__file__).parent / "fixtures" / "alerts"
NOW = datetime(2026, 10, 11, 18, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    monkeypatch.delenv(msrc.ENV_FLAG, raising=False)
    monkeypatch.delenv(msrc.ENV_DIR, raising=False)


@pytest.fixture()
def staging(monkeypatch):
    monkeypatch.setenv(msrc.ENV_FLAG, "1")
    monkeypatch.setenv(msrc.ENV_DIR, str(MAIL))


def gsa_card(cache):
    return ms.load_gsa(str(cache), NOW)["cards"][0]


def test_card_shape_parity_with_gsa(cache):
    want = set(gsa_card(cache))
    for s in msrc.ALERT_SOURCES:
        d = ms.load_source(s, NOW, None, directory=str(MAIL))
        assert d["status"] == "fixture" and d["cards"]
        for c in d["cards"]:
            assert want <= set(c), want - set(c)
            assert set(c["labels"]) == set(gsa_card(cache)["labels"])


def test_per_source_provenance_price_location_freshness():
    gd = {c["title"]: c for c in ms.load_source("govdeals", NOW, ms._origin("Conway AR"), directory=str(MAIL))["cards"]}
    trailer = gd["Utility Trailer 5x10, Single Axle"]
    assert trailer["source"] == "GovDeals" and trailer["url"] == "https://www.govdeals.com/asset/1234/5678" and trailer["bid"] == 350.0
    assert trailer["city"] == "Conway, AR" and trailer["state"] == "AR" and trailer["distance"] is not None and trailer["distance"] < 5
    assert trailer["fetched_at"].startswith("2026-10-07") and trailer["fixture"] is True and trailer["closes"] == "2026-10-08"
    mower = gd["Kubota Zero Turn Mower 60in"]
    assert mower["bid"] is None and mower["price"] == 500.0 and mower["price_type"] == "starting_bid"      # a starting price is not a bid, as for GSA
    assert not any("evil" in (c["url"] or "") for c in gd.values()) and len(gd) == 2                        # off-domain link dropped; spoofed mail quarantined
    ps = ms.load_source("publicsurplus", NOW, None, directory=str(MAIL))["cards"]
    assert [c["source"] for c in ps] == ["Public Surplus"] and ps[0]["bid"] == 120.0 and ps[0]["distance"] is None


def test_unresolved_location_is_not_counted_as_local(tmp_path):
    (tmp_path / "x.eml").write_bytes((MAIL / "02-publicsurplus.eml").read_bytes().replace(b"Little Rock, AR 72201", b"Zzyzx, AR"))
    c = ms.load_source("publicsurplus", NOW, ms._origin("Conway AR"), directory=str(tmp_path))["cards"][0]
    assert c["distance"] is None
    res, unchecked, _ = ms.partition([c], ms.parse_query({"base": ["Conway AR"], "radius": ["10"], "broad": ["1"]}))
    assert not res and "location not found (distance unknown)" in unchecked[0]["unchecked"]


def test_radius_applies_with_a_resolved_distance():
    cs = ms.load_source("publicsurplus", NOW, ms._origin("Conway AR"), directory=str(MAIL))["cards"]
    assert ms.partition(cs, ms.parse_query({"base": ["Conway AR"], "radius": ["10"], "broad": ["1"]}))[2]["radius"] == 1      # Little Rock is ~25 mi


def test_filters_apply_to_parser_backed_records():
    d = ms.load_source("all", NOW, ms._origin("Conway AR"), directory=str(MAIL))
    cards = [c for c in d["cards"] if c.get("fixture")]
    run = lambda **k: ms.partition(cards, ms.parse_query({"base": ["Conway AR"], "broad": ["1"], **{a: [b] for a, b in k.items()}}))   # noqa: E731
    assert {c["title"] for c in run()[0] + run()[1]} >= {"Utility Trailer 5x10, Single Axle", "Lincoln AC225 Stick Welder"}
    assert [c["title"] for c in run(max_price="300")[0]] == ["Lincoln AC225 Stick Welder"] and run(max_price="300")[2]["price"] == 1      # 350 > 300 hidden by price
    assert [c["title"] for c in run(min_price="100", max_price="400", radius="10")[0]] == ["Utility Trailer 5x10, Single Axle"]
    assert [c["title"] for c in run(keywords="welder")[0] + run(keywords="welder")[1]] == ["Lincoln AC225 Stick Welder"]
    assert not [c for c in run(exclude="trailer")[0] if "Trailer" in c["title"]]
    assert [c["title"] for c in run(loc_mode="state", state="AR", radius="")[0]] and run(loc_mode="state", state="TX")[0] == []
    assert ms.partition(cards, ms.parse_query({"base": ["Conway AR"], "radius": ["10"], "cat": ["trailers"]}))[0][0]["title"].startswith("Utility Trailer")


def test_all_dedups_across_sources_and_keeps_gsa(cache, tmp_path):
    d = msrc.load_source("all", str(cache), NOW, None, str(MAIL))
    assert d["status"] == "connected" and d["fixture"] is True
    names = {c["source"] for c in d["cards"]}
    assert names == {"GSA Auctions", "GovDeals", "Public Surplus"}
    twin = tmp_path / "dup"
    twin.mkdir()
    (twin / "a.eml").write_bytes((MAIL / "01-govdeals.eml").read_bytes())
    (twin / "b.eml").write_bytes((MAIL / "01-govdeals.eml").read_bytes().replace(b"fixture-gd-1", b"fixture-gd-2"))
    assert len(msrc.load_alerts("govdeals", str(twin), NOW)["cards"]) == 4 and len(msrc.dedupe(msrc.load_alerts("govdeals", str(twin), NOW)["cards"])) == 4  # F-150: same-source cards are never merged
    cards = msrc.load_alerts("govdeals", str(twin), NOW)["cards"]
    assert len(msrc.dedupe(cards + [{**cards[0], "source": "Public Surplus"}])) == 4  # a cross-source twin (same link) is merged
    assert [c["source"] for c in msrc.dedupe(d["cards"])].count("GSA Auctions") == [c["source"] for c in d["cards"]].count("GSA Auctions")


def test_no_staging_flag_means_not_connected_everywhere(ui):
    for s in ("govdeals", "publicsurplus"):
        h = get(ui, go=1, source=s, broad=1)
        assert f"<b>{'GovDeals' if s == 'govdeals' else 'Public Surplus'}: not connected.</b>" in h or "NOT CONNECTED" in h
        assert "FIXTURE" not in h and "Utility Trailer" not in h and "Stick Welder" not in h
    assert "NOT CONNECTED</b> · no mailbox read" in get(ui, go=1, source="govdeals")
    assert msrc.fixture_dir() is None


def test_flag_alone_or_dir_alone_is_still_not_connected(monkeypatch):
    monkeypatch.setenv(msrc.ENV_DIR, str(MAIL))
    assert msrc.fixture_dir() is None and ms.load_source("govdeals", NOW)["status"] == "not_connected"
    monkeypatch.delenv(msrc.ENV_DIR)
    monkeypatch.setenv(msrc.ENV_FLAG, "1")
    assert msrc.fixture_dir() is None and ms.load_source("publicsurplus", NOW)["cards"] == []


def test_fixture_page_is_labelled_and_never_connected(ui, staging):
    h = get(ui, go=1, source="govdeals", broad=1, base="Conway AR", radius="50", view="list")
    assert "FIXTURE / not live" in h and "id='fixture-banner'" in h and "not Michael's real deals" in html.unescape(h)
    li = re.search(r"<li data-src='GovDeals'[^>]*>.*?</li>", h).group(0)
    assert "connected" not in li.lower().replace("not connected", "") and "FIXTURE / not live" in li
    assert "https://www.govdeals.com/asset/1234/5678" in h and "Conway, AR" in h and "$350" in h and "fetched 2026-10-07" in h
    for off in ("Craigslist", "eBay", "Facebook Marketplace"):
        assert re.search(rf"<li data-src='{off}' data-status='not_connected'><b>{off}: NOT CONNECTED</b>", h)
    g = get(ui, go=1, source="govdeals", broad=1, base="Conway AR", radius="50")                   # gallery view carries the label per card
    assert g.count("FIXTURE / not live</span>") >= 1 and "data-lot='govdeals_email:1234/5678'" in g


def test_source_with_no_read_stays_not_connected_even_on_staging(ui, staging):
    for s in ("ebay", "craigslist", "facebook marketplace"):
        h = get(ui, go=1, source=s, broad=1)
        assert f"{s}: not connected.</b>" in h and "Utility Trailer" not in h and "id='fixture-banner'" not in h
    d = ms.load_source("all", NOW, None, directory=str(MAIL))
    assert all(r["status"] == "fixture" for r in d["coverage"] if r["name"] in ("GovDeals", "Public Surplus"))
    assert not any(r["status"] == "connected" for r in d["coverage"] if r["name"] != "GSA Auctions")


def test_fixture_cards_get_the_same_filters_through_the_page(ui, staging):
    q = dict(go=1, source="govdeals", broad=1, base="Conway AR", radius="50", view="list")
    h = get(ui, max_price="300", **q)
    assert "Utility Trailer 5x10" not in h and "0 results" in h and "price" in h
    h2 = get(ui, min_price="100", max_price="400", **q)
    assert "Utility Trailer 5x10" in h2 and "<h2>1 result" in h2


def test_no_network_or_imap_in_the_seam():
    src = (Path(msrc.__file__).read_text() + Path(__file__).parent.parent.joinpath("operator_ui/market_source_view.py").read_text())
    assert not re.search(r"import (imaplib|socket|urllib|requests|http)|ImapReader|\.login\(|MBOS_IMAP", src)
