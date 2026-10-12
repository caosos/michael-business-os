"""F-144: DealSniffer Marketplace title, radius slider 0-500 that expands (never clamps), neutral first-visit prompt."""
from __future__ import annotations

import re

import pytest

from operator_ui import landing_fix
from tests.test_market_f47 import cache, get, req, ui  # noqa: F401


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))
    return tmp_path / "prefs.json"


def _radius(h):
    sel = re.search(r"<select form='mkform' id='radius' name='radius'>.*?</select>", h, re.S).group(0)
    return re.findall(r"<option value='([^']*)'", sel), re.search(r"<option value='([^']*)' selected", sel).group(1)


def test_title_text(ui):
    h = get(ui)
    assert "<h1 class='pagehead'>DealSniffer Marketplace</h1>" in h and "Michael's Marketplace" not in h


def test_radius_presets_f159(ui):                         # F-159 replaced the 0-500 slider with the GSA-style presets
    assert _radius(get(ui, go=1, base="Conway AR", radius="100")) == (["10", "25", "50", "100", "250", ""], "100")


def test_radius_750_kept_unclamped(ui):
    h = get(ui, go=1, base="Conway AR", radius="750")
    assert _radius(h) == (["10", "25", "50", "100", "250", "", "750"], "750") and "750 miles" in h
    assert "Radius: 750 mi" in get(ui) or _radius(get(ui))[1] == "750"     # saved preference comes back unclamped
    assert _radius(get(ui))[1] == "750"


def test_radius_25000_accepted(ui):
    h = get(ui, go=1, base="Conway AR", radius="25000")
    assert _radius(h)[1] == "25000" and "within 25000 miles" in h


def test_fractional_radius_over_500_not_rounded_down(ui):
    assert _radius(get(ui, go=1, base="Conway AR", radius="500.5"))[1] == "500.5"


def test_js_widens_and_never_clamps():
    js = open("operator_ui/static/market_radius.js").read()
    assert "base = 500" in js and "Math.max(base, Math.ceil(x))" in js and "Math.min" not in js
    assert 'r.addEventListener("input"' in js and 'n.addEventListener("input"' in js     # both directions


def test_first_visit_prompt_is_neutral_not_an_error(ui, prefs_file):
    from tests.test_market_f143 import new_user
    new_user(prefs_file)                                       # F-159: a user with no home set; this owner starts at AR / 72032
    h = get(ui)
    assert "Enter a ZIP or city to search by distance" in h and "accepted but not located" not in h
    assert "Enter a ZIP or city to search by distance" in landing_fix.origin_note("", False, None)
    assert "accepted but not located" in landing_fix.origin_note("Nowhereville", False, 50.0)
