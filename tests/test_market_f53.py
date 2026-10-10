"""F-53: close the four F-52 acceptance gaps: (1) browse-first layout, (2) filter/category/row-order choices survive a real restart
(proven on a second App instance sharing only the prefs file), (3) validation of the FINAL resolved numbers (sliders + direct query)."""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer

import pytest

from operator_ui import market_prefs as mp
from operator_ui import market_search as ms
from operator_ui.server import App, make_handler
from tests.conftest import PIN
from tests.test_operator_ui import req
from tests.test_market_f47 import NOW, GOV_POLICY, StubStore, cache, get, ui  # noqa: F401
from tests.test_market_f52 import lots


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def _fresh_app(tmp_path, name):
    """A brand-new App + HTTP server: shares NO memory with another instance, only files (what a process restart keeps)."""
    app = App(StubStore(), operator_pin=PIN, campaigns_file=str(tmp_path / f"{name}.json"), policy_path=str(GOV_POLICY) if GOV_POLICY else None)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    app.port = httpd.server_address[1]
    return app, httpd


# ---- (3) final resolved numeric values
def q_of(**kw):
    return ms.parse_query({k: [v] for k, v in kw.items()})


@pytest.mark.parametrize("kw", [
    {"max_price": "abc"}, {"min_price": "-5"}, {"max_price": "-0.01"}, {"radius": "-1"}, {"radius": "far"}, {"radius": "25001"},
    {"min_price": "nan"}, {"max_price": "inf"}, {"max_price": "1e999"},
    {"min_price": "900", "max_price": "100"},                                                    # inverted boxes
    {"max_price": "100", "max_r": "abc", "prev_max": "20000"},                                    # moved slider, nonnumeric
    {"min_r": "-3", "prev_min": "1"},                                                              # moved slider, negative
    {"min_r": "900", "prev_min": "1", "max_r": "100", "prev_max": "20000"},                        # inverted sliders
    {"min_r": "900", "prev_min": "1", "max_price": "100"},                                         # inverted: slider min vs typed max
    {"min_price": "500", "max_r": "100", "prev_max": "20000"},                                     # inverted: typed min vs slider max
])
def test_final_resolved_values_invalid_are_said_and_run_nothing(ui, kw):
    assert q_of(**kw)["errors"], kw
    h = get(ui, go=1, **kw)
    assert "id='filter-errors'" in h and "No search was run" in h and "data-lot=" not in h


@pytest.mark.parametrize("kw,lo,hi", [
    ({"min_price": "", "max_price": ""}, None, None),                                           # blank = no limit
    ({"min_price": "  ", "max_price": " "}, None, None),
    ({"min_price": "100", "max_price": "100"}, 100.0, 100.0),                                   # exact boundary: equal is allowed
    ({"min_price": "0", "max_price": "0"}, 0.0, 0.0),
    ({"min_price": "$1,000", "max_price": "20000"}, 1000.0, 20000.0),
    ({"min_price": "5", "min_r": "300", "prev_min": "300"}, 5.0, None),                          # slider untouched: the typed box decides
    ({"min_price": "5", "min_r": "300", "prev_min": "1"}, 300.0, None),                          # slider moved: it decides
    ({"max_r": "250", "prev_max": "20000"}, None, 250.0),
])
def test_final_resolved_values_valid(kw, lo, hi):
    q = q_of(**kw)
    assert q["errors"] == [] and q["min_price"] == lo and q["max_price"] == hi


def test_radius_boundaries():
    assert q_of(radius="0", max_price="1")["errors"] == [] and q_of(radius="0", max_price="1")["radius"] == 0.0
    assert q_of(radius="25000")["errors"] == []
    assert q_of(radius="")["errors"] == [] and q_of(radius="", max_price="1")["radius"] is None


def test_exact_boundary_bid_is_inside_and_strict_unknowns_stay_out():
    cards = lots()
    known = sorted({c["bid"] for c in cards if c["bid"] is not None})
    assert known, "fixture must have bid values"
    b = known[len(known) // 2]
    res, unchecked, _ = ms.partition(cards, q_of(broad="1", min_price=str(b), max_price=str(b)))
    assert res and all(c["bid"] == b for c in res)                                                  # inclusive both ends
    assert all(c["bid"] is None for c in unchecked) and unchecked                                    # no-bid lots are never "in range"
    assert not {c["id"] for c in res} & {c["id"] for c in unchecked}
    below, _, _ = ms.partition(cards, q_of(broad="1", max_price=str(max(b - 0.01, 0))))
    assert all(c["bid"] < b for c in below)


# ---- (2) persistence across a real restart
def test_owner_choices_survive_a_server_restart_on_an_isolated_instance(ui, tmp_path):
    pick = dict(go=1, cat="equipment", row1="vehicles", row2="tools", row3="", row4="", sort="bid", max_price="5000", radius="200", broad=1)
    first = get(ui, **pick)
    assert "Max price: $5,000" in first
    assert json.loads(mp.path().read_text())["last"]["cat"] == ["equipment"]                       # written to disk, not app memory
    app2, httpd2 = _fresh_app(tmp_path, "restarted")                                                # nothing in memory; same prefs file
    try:
        assert not hasattr(app2, "market_last")
        again = req(app2, "GET", "/market")[2]
    finally:
        httpd2.shutdown()
        httpd2.server_close()
    assert "Max price: $5,000" in again and "Radius: 200 mi" in again and "Mode: BROAD" in again
    assert "<option value='bid' selected>" in again


def test_row_order_survives_restart(ui, tmp_path):
    get(ui, go=1, row1="equipment", row2="trailers", row3="", row4="")
    app2, httpd2 = _fresh_app(tmp_path, "r2")
    try:
        h = req(app2, "GET", "/market")[2]
    finally:
        httpd2.shutdown()
        httpd2.server_close()
    assert h.index("data-row='equipment'") < h.index("data-row='trailers'")


def test_new_search_clears_remembered_choices_and_reset_keeps_them(ui):
    get(ui, go=1, cat="tools", max_price="77")
    assert mp.recall(("cat", "max_price"))
    mp.act("reset", "")
    assert mp.recall(("cat", "max_price")), "resetting suggestions must not erase the owner's filter choices"
    get(ui, new=1)
    assert mp.recall(("cat", "max_price")) == {}


def test_remembered_file_is_untrusted_and_only_known_keys_come_back(tmp_path):
    mp.path().write_text(json.dumps({"last": {"cat": ["tools"], "evil": ["x"], "max_price": "notalist", "base": ["a" * 999]}}))
    got = mp.recall(("cat", "max_price", "base"))
    assert got == {"cat": ["tools"], "base": ["a" * 200]}
    mp.path().write_text("{not json")
    assert mp.recall(("cat",)) == {}


# ---- (1) browse-first layout
def test_cards_come_before_the_secondary_panels_and_panels_are_collapsed(ui):
    h = get(ui, go=1)
    first_card = h.index("data-lot=")
    for marker in ("id='prefs'", "id='working-capital'", "id='gsa-explainer'", "id='distance-caveat'", "id='save-search'"):
        i = h.index(marker)
        assert i > first_card or marker == "id='save-search'", marker
        assert h[max(0, i - 40):i].count("<details") or h[i - 1] == "<", marker
    assert h.index("id='save-search'") < first_card and "id='save-search' open" not in h          # compact: closed disclosure
    assert "id='applied-filters'" in h and "current bid" in h and "all-in cost UNKNOWN" in h        # truth labels stay visible


def test_mobile_css_puts_the_filters_and_search_now_before_the_results():
    from operator_ui import market_view as mv
    assert ".mk-main{order:2}" in mv.CSS and ".mk-side{order:1}" in mv.CSS      # F-60: Search Now lives in the filter card, so it comes first


# ---- F-54: radius compares the UNROUNDED haversine distance; saved-search round trip; invalid requests never overwrite the last good choices
def _rounding_down_lot():
    for base in ("Conway AR", "Little Rock AR", "Searcy AR", "Russellville AR", "Benton AR"):
        for c in ms.load_gsa(None, NOW, ms._origin(base))["cards"]:
            d = c["distance"]
            if d is not None and round(d, 1) < d - 0.004:
                return base, c, round(d, 1)
    pytest.fail("fixture needs a lot whose real distance rounds down")


def test_radius_boundary_real_haversine_just_over_is_out_and_exact_is_in():
    base, lot, shown = _rounding_down_lot()
    assert lot["distance"] > shown and lot["distance"] != round(lot["distance"], 1)            # the card keeps the real distance
    cards = ms.load_gsa(None, NOW, ms._origin(base))["cards"]
    over = ms.partition(cards, q_of(base=base, broad="1", radius=f"{shown:g}"))[0]
    assert lot["id"] not in {c["id"] for c in over}            # e.g. 50.04 mi must not pass a 50 mi limit (old code rounded to 50.0 and let it in)
    exact = ms.partition(cards, q_of(base=base, broad="1", radius=f"{lot['distance']:.10f}"))[0]
    assert lot["id"] in {c["id"] for c in exact}               # exactly the distance is inclusive
    assert lot["id"] not in {c["id"] for c in ms.partition(cards, q_of(base=base, broad="1", radius=f"{lot['distance'] - 0.001:.6f}"))[0]}


def test_saved_search_round_trip_keeps_min_price_categories_rows_broad_condition():
    from operator_ui import market_view as mv
    f = {"csrf": "x", "keywords": "trailer", "base": "Conway AR", "radius": "120", "min_price": "100", "max_price": "500", "cat": "equipment", "row1": "tools",
         "row2": "equipment", "row3": "", "row4": "", "broad": "1", "condition": "used", "exclude": "broken", "preferred": "tandem"}
    saved = mv.save_form(f)
    doc = {"criteria": {"keywords": ["trailer"], "origin": saved["origin"], "radius_miles": float(saved["radius_miles"]), "max_price_usd": float(saved["max_price_usd"]),
                        "must_have": [], "nice_to_have": [w.strip() for w in saved["nice_to_have"].split(",")]}}
    q = ms.parse_query({k: v if isinstance(v, list) else [str(v)] for k, v in ms.criteria_to_query(doc).items()})
    assert (q["min_price"], q["max_price"], q["radius"]) == (100.0, 500.0, 120.0) and q["errors"] == []
    assert q["cats"] == ["equipment"] and q["rows"][:2] == ["tools", "equipment"] and q["broad"] and q["condition"] == "used"
    assert q["exclude"] == ["broken"] and q["preferred"] == ["tandem"]


def test_saved_search_http_round_trip(ui):
    from tests.test_market_f47 import post
    st, loc, _ = post(ui, "/market/save", keywords="trailer", base="Conway AR", radius="120", min_price="100", max_price="500", cat="equipment", title="rt")
    assert st == 303 and "created" in loc
    cid = ui.campaign_records()[0]["doc"]["campaign_id"]
    h = get(ui, run=cid)
    assert "Min price: $100" in h and "Max price: $500" in h and "Radius: 120 mi" in h and "filter-errors" not in h


def test_invalid_request_never_overwrites_last_good_choices(ui, tmp_path):
    get(ui, go=1, radius="120", max_price="500", cat="tools")
    good = mp.recall(("radius", "max_price", "cat"))
    assert good["radius"] == ["120"]
    bad = get(ui, go=1, radius="x")
    assert "id='filter-errors'" in bad                              # the refused request is told so
    assert mp.recall(("radius", "max_price", "cat")) == good        # and the stored choices are untouched
    for page in (get(ui), req(ui, "GET", "/market")[2]):            # plain load: choices restored, no error banner
        assert "Radius: 120 mi" in page and "Max price: $500" in page and "filter-errors" not in page
    app2, httpd2 = _fresh_app(tmp_path, "after-bad")
    try:
        again = req(app2, "GET", "/market")[2]
    finally:
        httpd2.shutdown()
        httpd2.server_close()
    assert "Radius: 120 mi" in again and "Max price: $500" in again and "filter-errors" not in again
