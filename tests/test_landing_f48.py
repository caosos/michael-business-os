"""F-48: the landing is the Marketplace; no demo/training item or unlabelled bankroll anywhere on it; a GSA card never has a broken
<img>; origin and radius are free input."""

from __future__ import annotations

import re

from operator_ui import landing_fix, live_demo
from operator_ui import market_search as ms
from operator_ui import market_view as mv
from operator_ui import mission_view as mv_
from tests.test_market_f47 import NOW, cache, get, ui  # noqa: F401  (fixtures)
from tests.test_operator_ui import req
from tests.test_f29_ui import PLAN, leg  # noqa: F401


class Store:
    def item(self, iid):
        return {"item_id": iid, "dedup_key": "train-tv"} if iid.startswith("TRAIN") else {"item_id": iid, "sources": [{"url": "https://www.gsaauctions.gov/a"}]}


def _plan(*ids):
    import copy
    doc = copy.deepcopy(PLAN)
    doc["legs"] = [leg(item_id=i, title="55 inch LED TV" if i.startswith("TRAIN") else "Real trailer", verdict="YES", waiting_on=[]) for i in ids]
    doc["ledger"] = {"available_to_deploy": 500}
    return {"kind": "plan", "doc": doc, "errors": []}


def test_landing_redirects_to_marketplace_and_queue_is_one_click_away(ui):
    s, loc, _ = req(ui, "GET", "/")
    assert s in (302, 303) and loc == "/market"
    assert 'href="/queue"' in req(ui, "GET", "/market")[2]
    s, loc, _ = req(ui, "GET", "/?msg=hi")                    # a flash from a form redirect still reaches the queue
    assert loc == "/queue?msg=hi"


def test_best_next_move_ignores_training_items_everywhere():
    live = landing_fix.live_only(_plan("TRAIN-TV-1", "itm_real"), Store())
    assert [l["item_id"] for l in live["doc"]["legs"]] == ["itm_real"]
    only_demo = landing_fix.live_only(_plan("TRAIN-TV-1"), Store())
    h = mv_.today_header(only_demo)
    assert "55 inch" not in h and "TRAIN-" not in h and "Nothing to approve yet" in h


def test_http_pages_have_no_train_no_55_inch_no_unlabelled_500(ui):
    h = req(ui, "GET", "/market")[2]
    assert "TRAIN-" not in h and "55 inch" not in h and "Marketplace" in h
    assert not re.search(r"\$\s?500(\.00)?\b", re.sub(r"<[^>]+>", " ", re.sub(r"<div class='card small' id='working-capital'>.*?</div>", "", h, flags=re.S)))  # F-51: the labelled SETTING is allowed


def test_bankroll_is_labelled_with_source_and_asof_and_recommends_nothing():
    h = landing_fix.bankroll_html({"available_to_deploy": 500, "as_of": "2026-10-09T10:00:00Z"}, lambda v: f"${v:,.2f}")
    assert "Simulated bankroll, not your cash" in h and "source:" in h and "as of 2026-10-09T10:00:00Z" in h
    assert "deploy" not in h.lower().replace("not used to recommend", "") and "Not used to recommend anything" in h
    assert "UNKNOWN" in landing_fix.bankroll_html(None, str)
    full = mv_.today_header(_plan("itm_real"))
    assert "available to deploy" not in full


def test_gsa_card_has_no_broken_img_and_keeps_the_url_in_details(ui):
    h = get(ui, go=1, keywords="trailer")
    assert "<img" not in h and "Photo is behind GSA&#x27;s login: open the original listing" in h.replace("'s", "&#x27;s") or "behind GSA" in h
    assert "ppms.gov" in h and "<details" in h and "gsaauctions.gov/auctions/preview" in h
    t = landing_fix.photo_tile("https://www.ppms.gov/x.jpg", "https://www.gsaauctions.gov/l")
    assert "<img" not in t and "https://www.ppms.gov/x.jpg" in t
    assert "<img" not in live_demo.render_gsa_lot({"id": "1", "imageURL": "https://www.ppms.gov/x.jpg", "itemDescURL": "https://www.gsaauctions.gov/l"})
    assert "<img" in mv._photo("https://www.gsaauctions.gov/img/1.jpg")        # non-GSA hosts are unchanged


def test_arbitrary_origin_and_radius_are_accepted(ui):
    q = ms.parse_query({"base": ["Tulsa, OK"], "radius": ["12000"]})
    assert q["base"] == "Tulsa, OK" and q["radius"] == 12000
    assert ms.parse_query({"base": ["72032"], "radius": ["7"]})["radius"] == 7
    assert ms._origin("35.1, -92.4") == (35.1, -92.4)
    h = get(ui, go=1, keywords="trailer", base="90210", radius="25")
    assert "accepted but not located" in h and "not applied" in h
    assert "Marianna" in h                                                   # unlocated origin never silently hides results
