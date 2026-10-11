"""F-144: DealSniffer Marketplace title, radius slider 0-500 that expands (never clamps), neutral first-visit prompt."""
from __future__ import annotations

import re

import pytest

from operator_ui import landing_fix
from tests.test_market_f47 import cache, get, req, ui  # noqa: F401


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def _slider(h):
    return re.search(r"id='radius_r' min='0' max='(\d+)' step='1' value='([\d.]+)'", h).groups()


def test_title_text(ui):
    h = get(ui)
    assert "<h1 class='pagehead'>DealSniffer Marketplace</h1>" in h and "Michael's Marketplace" not in h


def test_slider_default_max_is_500(ui):
    h = get(ui, go=1, base="Conway AR", radius="150")
    assert _slider(h) == ("500", "150") and "500 miles</span>" in h


def test_radius_750_expands_slider_and_submits_750(ui):
    h = get(ui, go=1, base="Conway AR", radius="750")
    assert _slider(h) == ("750", "750") and "value='750'" in h and "750 miles" in h
    assert "name='radius' min='0' max='25000'" in h
    assert "Radius: 750 mi" in get(ui)                       # saved preference comes back unclamped
    assert _slider(get(ui)) == ("750", "750")


def test_radius_25000_accepted_by_field(ui):
    h = get(ui, go=1, base="Conway AR", radius="25000")
    assert _slider(h) == ("25000", "25000") and "Radius: 25000 mi" in h and "value='25000'" in h


def test_fractional_radius_over_500_not_rounded_down(ui):
    h = get(ui, go=1, base="Conway AR", radius="500.5")
    assert _slider(h)[0] == "501" and "value='500.5'" in h


def test_js_widens_and_never_clamps():
    js = open("operator_ui/static/market_radius.js").read()
    assert "base = 500" in js and "Math.max(base, Math.ceil(x))" in js and "Math.min" not in js
    assert 'r.addEventListener("input"' in js and 'n.addEventListener("input"' in js     # both directions


def test_first_visit_prompt_is_neutral_not_an_error(ui):
    h = get(ui)
    assert "Enter a ZIP or city to search by distance" in h and "accepted but not located" not in h
    assert "Enter a ZIP or city to search by distance" in landing_fix.origin_note("", False, None)
    assert "accepted but not located" in landing_fix.origin_note("Nowhereville", False, 50.0)
