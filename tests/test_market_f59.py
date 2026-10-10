"""F-59: saved 'any of' focus terms survive the REAL rendered Save, reopen and restart (they were dropped, so a saved search reopened as 'focus: none' and broadened)."""
from __future__ import annotations

import re
from urllib.parse import urlencode

import pytest

from tests.test_market_f47 import cache, get, post, ui  # noqa: F401
from tests.test_market_f56 import _fresh_app_on, _save_form
from tests.test_operator_ui import req


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def _view(h: str) -> tuple:
    """(applied-filter chips, visible known-ID set: cards outside the unchecked section)."""
    chips = re.sub(r"<[^>]+>", " ", re.search(r"id='applied-filters'.*?</p>", h, re.S).group(0))
    main = h.split("id='unchecked-section'")[0]
    return re.sub(r"\s+", " ", chips).strip(), frozenset(re.findall(r"data-lot='([^']*)'", main))


@pytest.mark.parametrize("any_terms", ["tools, welder", "trailer, equipment"])
def test_any_terms_survive_save_reopen_restart(ui, tmp_path, any_terms):
    search = dict(go=1, keywords="", max_price="20000", radius="150", **{"any": any_terms})
    before = _view(get(ui, **search))
    form = _save_form(get(ui, **search))
    assert form["fields"]["any"] == any_terms
    fields = {k: v for k, v in form["fields"].items() if k not in ("csrf", "nonce", "pin", "title")}
    st, loc, _ = post(ui, "/market/save", **{**fields, "title": "f59"})
    assert st == 303 and "created" in loc
    cid = ui.campaign_records()[0]["doc"]["campaign_id"]
    assert _view(get(ui, run=cid)) == before
    app2, httpd2 = _fresh_app_on(ui, tmp_path)
    try:
        assert _view(req(app2, "GET", "/market?" + urlencode({"run": cid}))[2]) == before
    finally:
        httpd2.shutdown()
        httpd2.server_close()


def test_before_has_focus_chip_when_terms_given(ui):
    assert "welder" in _view(get(ui, go=1, max_price="20000", **{"any": "tools, welder"}))[0].lower()
