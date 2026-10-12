"""F-143: numeric price fields only (sliders gone), a radius slider coupled to the numeric radius field, a generic scope summary, no hidden Conway origin."""
from __future__ import annotations

import re

import pytest

from operator_ui import landing_fix, market_search as ms
from tests.test_market_f47 import cache, get, req, ui  # noqa: F401


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    return tmp_path / "prefs.json"


def new_user(path):
    """F-159: this owner starts at home (AR, 72032); a user with no home set in prefs `ui.home` starts with nothing preselected."""
    path.write_text(__import__("json").dumps({"ui": {"home": {"state": "", "zip": ""}}}))


def test_price_sliders_are_gone_and_numeric_fields_stay(ui):
    h = get(ui, go=1, base="Conway AR", radius="150")
    assert "min_r" not in h and "max_r" not in h and "prev_min" not in h and "prev_max" not in h
    assert re.search(r"type='number' id='min_price' name='min_price'", h) and re.search(r"type='number' id='max_price' name='max_price'", h)
    assert not hasattr(ms, "_price_pick") and not hasattr(ms, "_slider_price") and not hasattr(ms, "DEFAULT_BASE")


def test_obsolete_slider_urls_never_change_typed_prices(ui):
    q = ms.parse_query({"base": ["Conway AR"], "min_price": ["10"], "max_price": ["60"], "min_r": ["900"], "max_r": ["20"], "prev_min": ["1"], "prev_max": ["20000"]})
    assert (q["min_price"], q["max_price"], q["errors"]) == (10.0, 60.0, [])
    q = ms.parse_query({"base": ["Conway AR"], "min_r": ["900"], "max_r": ["bad"]})
    assert (q["min_price"], q["max_price"], q["errors"]) == (None, None, [])


def test_old_saved_search_keeps_numeric_values_and_has_no_fallback_origin():
    doc = {"criteria": {"keywords": ["trailer"], "origin": "Conway AR", "radius_miles": 80, "max_price": 300, "min_price": 20, "nice_to_have": []}}
    out = ms.criteria_to_query(doc)
    assert out["base"] == "Conway AR" and out["radius"] == "80"
    del doc["criteria"]["origin"]
    assert ms.criteria_to_query(doc)["base"] == ""                        # no hidden Conway


def test_new_user_must_give_an_origin_and_blank_origin_is_not_located():
    assert ms._origin("") is None and ms._origin("   ") is None
    q = ms.parse_query({"radius": ["50"]})
    assert any("Enter your ZIP or city" in m for m in q["errors"])
    assert ms.parse_query({"loc_mode": ["state"], "state": ["AR"]})["errors"] == []     # By State needs no origin
    assert ms.parse_query({"base": ["72032"], "radius": ["50"]})["errors"] == []         # another supported origin: ZIP
    assert ms._origin("72032") and ms._origin("Conway AR")


def test_fresh_visit_for_a_new_user_shows_empty_origin_and_no_conway(ui, prefs_file):
    new_user(prefs_file)
    h = get(ui)
    assert "name='base' size='12' value=''" in h and "Radius: none" in h
    assert "Conway" not in h


def test_radius_control_markup_and_scope_text(ui):
    h = get(ui, go=1, base="72032", radius="37.5", broad=1)               # F-159: the slider became a 10/25/50/100/250/Any dropdown; an off-preset value is kept, never clamped
    sel = re.search(r"<select form='mkform' id='radius' name='radius'>.*?</select>", h, re.S).group(0)
    assert re.findall(r"<option value='([^']*)'", sel) == ["10", "25", "50", "100", "250", "", "37.5"] and "value='37.5' selected" in sel
    assert "id='radius_r'" not in h and "within 37.5 miles" in h and "of 72032" not in h.split("<h2>")[1].split("</h2>")[0]


def test_script_is_same_origin_and_only_market_gets_script_src(ui):
    s, _, body = req(ui, "GET", "/static/market_radius.js")
    assert s == 200 and "radius_r" in body
    import http.client

    def csp(path):
        c = http.client.HTTPConnection("127.0.0.1", ui.port, timeout=15)
        c.request("GET", path, headers={"Host": f"127.0.0.1:{ui.port}"})
        return c.getresponse().getheader("Content-Security-Policy") or ""
    assert "script-src 'self'" in csp("/market") and "script-src" not in csp("/wanted") and "unsafe-inline'; img" in csp("/market")
    assert "<script" not in get(ui, go=1, base="72032").replace("<script src='/static/market_radius.js' defer></script>", "")


def test_state_mode_radius_not_applied_unless_also_radius():
    q = ms.parse_query({"loc_mode": ["state"], "state": ["AR"], "radius": ["10"]})
    assert "NOT applied" in __import__("operator_ui.market_view", fromlist=["x"]).scope_text(q)
    q = ms.parse_query({"loc_mode": ["state"], "state": ["AR"], "radius": ["10"], "also_radius": ["1"], "base": ["72032"]})
    assert __import__("operator_ui.market_view", fromlist=["x"]).scope_text(q) == "By State: AR AND within 10 miles"


def test_real_chrome_radius_dropdown_submits_the_displayed_miles(ui):
    pw = pytest.importorskip("playwright.sync_api")
    base = f"http://127.0.0.1:{ui.port}"
    with pw.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome", headless=True)
        except Exception:
            pytest.skip("no chrome")
        for vp in ({"width": 1648, "height": 1000}, {"width": 390, "height": 844}):
            pg = b.new_page(viewport=vp)
            pg.goto(base + "/market?go=1&broad=1&base=Conway+AR&radius=150")
            side = lambda: pg.click("#filters-btn-m") if vp["width"] < 700 else None  # noqa: E731  phone: the filters are a drawer
            side()
            assert pg.is_visible("#radius") and pg.input_value("#radius") == "150"
            for target in ("10", "250", ""):
                if pg.is_hidden("#radius"):
                    side()
                pg.select_option("#radius", target)
                with pg.expect_navigation():
                    pg.click("#mkfilters button.mk-apply")
                assert (f"radius={target}" in pg.url) if target else "radius=" not in pg.url.replace("radius=&", "")
                assert pg.input_value("#radius") == target
            pg.close()
        b.close()
