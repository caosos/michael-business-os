"""F-46: live vs demo. Normal feed has zero TRAIN-*/fixture items; the DEMO switch shows them behind the banner; example.invalid is never a link;
no sold evidence = RESEARCH NEEDED; owner-supplied intake carries provenance; GSA lots show original link and photo. TEST data only; DRY-RUN."""
import re

import pytest

from operator_ui import comps_view, live_demo
from tests.conftest import PIN
from tests.test_operator_ui import ready, req

REAL = {"source_listing_id": "3-1-QSC-I-27-006-005", "source": "GSA", "url": "https://www.gsaauctions.gov/auctions/lot/3-1-QSC-I-27-006-005"}
TRAIN = {"source_listing_id": "TRAIN-TV-1", "source": "facebook_marketplace_manual", "url": "https://example.invalid/fbm/tv-55-inch"}


def test_classification():
    assert live_demo.is_training({"sources": [TRAIN]}) and live_demo.is_demo({"sources": [TRAIN]})
    assert live_demo.is_training({"item_id": "x", "dedup_key": "other_asset|tv|conway|train-tv-1", "sources": [REAL]})
    assert not live_demo.is_demo({"sources": [REAL]})
    assert live_demo.is_demo({"sources": [{"url": "https://example.invalid/x"}]}) and live_demo.is_demo({"sources": []}) and live_demo.is_demo(None)


class FakeStore:
    def __init__(self, items):
        self.items = items

    def item(self, i):
        return self.items[i]


def test_split_queue_keeps_training_out_of_the_live_lists():
    st = FakeStore({"a": {"sources": [REAL]}, "b": {"sources": [TRAIN]}})
    q = {"pending": [{"item_id": "a", "title": "Real", "status": "pending_approval"}, {"item_id": "b", "title": "TV", "status": "pending_approval"}],
         "held": [], "closed": []}
    live, demo = live_demo.split_queue(st, q)
    assert [r["item_id"] for r in live["pending"]] == ["a"] and [r["item_id"] for r in demo["pending"]] == ["b"]
    sec = live_demo.render_demo_section(demo)
    assert "DEMO / TRAINING DATA, NOT REAL LISTINGS, DO NOT BUY" in sec and "Needs" not in sec and "<button" not in sec


def test_no_clickable_example_invalid():
    h = live_demo.link_html("https://example.invalid/cl/trailer")
    assert "No real listing, training example" in h and "<a " not in h
    assert "No verified live link" in live_demo.link_html(None)
    assert "<a " not in live_demo.link_html("javascript:alert(1)")


def test_unknown_fields_are_collapsed():
    rows = [("Make", "Honda")] + [(f"F{i}", "UNKNOWN") for i in range(15)]
    h = live_demo.collapse_unknown(rows, lambda v: v == "UNKNOWN")
    assert h.count("UNKNOWN") == 0 and "15 unknown fields" in h and "<details>" in h and "Honda" in h


def test_owner_listing_intake_has_provenance_and_escapes():
    d = live_demo.parse_owner_listing({"url": "https://www.govdeals.com/en/asset/1/2", "photos": "https://www.govdeals.com/p1.jpg\n\nhttps://www.govdeals.com/p2.jpg",
                                       "text": "<script>alert(1)</script>\nline two"}, "Michael", "2026-10-09T12:00:00Z")
    assert d["provenance"] == "OWNER-SUPPLIED" and d["sold_evidence"] is None and len(d["photos"]) == 2
    h = live_demo.render_owner_listing(d)
    assert "OWNER-SUPPLIED" in h and "RESEARCH NEEDED, DO NOT BUY YET" in h and "View original listing" in h
    assert "<script>" not in h and "&lt;script&gt;" in h and "Michael" in h and "2026-10-09T12:00:00Z" in h
    for bad in ({"url": "javascript:alert(1)"}, {"photos": "data:text/html,x"}, {}):
        with pytest.raises(ValueError):
            live_demo.parse_owner_listing(bad, "Michael", "t")


def test_gsa_lot_card_has_link_photo_and_no_sold_claim():
    lot = {"id": "3-1-QSC-I-27-006-005", "itemName": "Utility trailer <b>x</b>", "highBidAmount": 425, "biddersCount": 3, "aucEndDt": "2026-10-20T15:00:00Z",
           "location": "Marianna, AR", "itemDescURL": "https://www.gsaauctions.gov/auctions/lot/3-1-QSC-I-27-006-005",
           "imageURL": "https://www.gsaauctions.gov/img/1.jpg", "as_of": "2026-10-09T10:00:00Z"}
    h = live_demo.render_gsa_lot(lot)
    assert "View original listing" in h and "<img " in h and "Marianna, AR" in h and "as of 2026-10-09T10:00:00Z" in h
    assert "&lt;b&gt;x&lt;/b&gt;" in h and "not a sold price" in h
    assert "<img " not in live_demo.render_gsa_lot({**lot, "imageURL": "https://img.example.invalid/1.jpg"})


def test_research_needed_replaces_the_sold_price_prompt():
    h = comps_view.render_today([({"item_id": "i1", "normalized": {"title": "Mower"}}, comps_view.DEFAULT_GAP)])
    assert "RESEARCH NEEDED, DO NOT BUY YET" in h and "Needs from you" not in h


def test_http_demo_switch_banner_and_no_link(rt, ui, discover):
    iid, _ = ready(rt, discover)
    normal = req(ui, "GET", "/queue")[2]
    assert iid not in normal and "TRAIN-" not in normal and "DEMO / TRAINING DATA" not in normal and "Show demo data" not in normal
    assert not re.search(r"href=['\"][^'\"]*example\.invalid", normal)
    demo = req(ui, "GET", "/queue?demo=1")[2]
    assert iid in demo and "DEMO / TRAINING DATA, NOT REAL LISTINGS, DO NOT BUY" in demo and "Demo / training examples" in demo
    item = req(ui, "GET", f"/item/{iid}")[2]
    assert "DEMO / TRAINING DATA, NOT REAL LISTINGS, DO NOT BUY" in item and not re.search(r"href=['\"][^'\"]*example\.invalid", item)
    assert "No real listing, training example" in item
    # the resale demo lots sit behind the same switch
    assert "DEMO CountyLine" not in req(ui, "GET", "/resale")[2] and "DEMO CountyLine" in req(ui, "GET", "/resale?demo=1")[2]
    assert "DEMO CountyLine" not in normal


def test_http_owner_listing_intake(ui):
    assert req(ui, "GET", "/owner-listing")[0] == 200 and req(ui, "GET", "/gsa")[0] == 200
    s, _, b = req(ui, "POST", "/owner-listing", {"csrf": ui.csrf, "url": "https://www.govdeals.com/en/asset/9/9", "photos": "", "text": "Bobcat <i>x</i>"})
    assert s == 200 and "OWNER-SUPPLIED" in b and "View original listing" in b and "&lt;i&gt;x&lt;/i&gt;" in b
    s, _, b = req(ui, "POST", "/owner-listing", {"csrf": "bad", "url": "https://www.govdeals.com/en/asset/9/9"})
    assert "flash err" in b
    s, _, b = req(ui, "POST", "/owner-listing", {"csrf": ui.csrf, "url": "javascript:alert(1)"})
    assert "flash err" in b and 'href="javascript' not in b


def test_f48_queue_and_mission_have_no_training_item_or_unlabelled_bankroll(rt, ui, discover):  # F-48
    iid, _ = ready(rt, discover)
    assert req(ui, "GET", "/")[1] == "/market"
    for path in ("/queue", "/mission"):
        h = req(ui, "GET", path)[2]
        assert iid not in h and "TRAIN-" not in h and "55 inch" not in h, path
        assert "available to deploy" not in h, path
