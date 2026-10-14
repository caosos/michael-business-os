"""Owner-facing Marketplace source labels keep availability separate from matches."""
from datetime import datetime, timezone

from operator_ui import market_browse as browse
from operator_ui import market_search as search
from operator_ui import market_source_panel as panel
from operator_ui import market_sources as sources


NOW = datetime(2026, 10, 13, 18, 0, tzinfo=timezone.utc)


def source_rows():
    info = {i.key: i for i in sources.REGISTRY}
    return [
        {"info": info["facebook"], "probe": {"status": "connected"}, "state": "LIVE CONNECTED"},
        {"info": info["gsa"], "probe": {"status": "connected"}, "state": "LIVE CONNECTED"},
        {"info": info["local_deals"], "probe": {"status": "imported"}, "state": "IMPORTED"},
        {"info": info["offerup"], "probe": {"status": "manual"}, "state": "MANUAL"},
        {"info": info["ebay"], "probe": {"status": "offline"}, "state": "NOT CONNECTED"},
    ]


def test_filter_labels_separate_availability_from_current_matches(monkeypatch):
    monkeypatch.setattr(browse.msp, "rows", lambda now=None: source_rows())
    q = search.parse_query({"source": ["all"]})
    h = browse.source_section(q, {"all_sources": 7, "source": {
        "facebook": 0, "gsa": 4, "local_deals": 2, "offerup": 1, "ebay": 0}}, NOW)
    assert "All sources</b> <span class='mk-n'>(7 matching)" in h
    assert "Facebook Marketplace <span class='mk-n'>(0 matching)</span> <span class='small '>historical cache · retrieval off · no matches in this search" in h
    assert "GSA Auctions <span class='mk-n'>(4 matching)</span> <span class='small '>cache ready" in h
    assert "Authorized local deals <span class='mk-n'>(2 matching)</span> <span class='small '>imported" in h
    assert "OfferUp <span class='mk-n'>(1 matching)</span>" in h and ">manual</span>" in h
    assert "eBay <span class='mk-n'>(0 matching)</span>" in h and ">not connected</span>" in h
    assert h.count("type='checkbox'") == 6 and "disabled" not in h


def test_every_status_keeps_its_precise_owner_label():
    rows = source_rows()
    assert panel.display_status(rows[0], 0) == "historical cache · retrieval off · no matches in this search"
    assert panel.display_status(rows[1], 0) == "cache ready · no matches in this search"
    assert panel.display_status(rows[2], 2) == "imported"
    assert panel.display_status(rows[3], 0) == "manual · no matches in this search"
    assert panel.display_status(rows[4], 0) == "not connected"


def test_zero_nearby_gsa_offers_a_truthful_wider_search(monkeypatch):
    monkeypatch.setattr(browse.msp, "rows", lambda now=None: source_rows())
    q = search.parse_query({"base": ["72032"], "radius": ["41"], "source": ["all"], "cat": ["all"]})
    h = browse.source_section(q, {"all_sources": 7, "source": {"facebook": 7, "gsa": 0}}, NOW)
    assert "id='gsa-widen'" in h and "Show GSA Auctions within 150 miles" in h
    assert "source=gsa" in h and "radius=150" in h
