"""F-136: Location panel with explicit By State / By Distance modes, searchable multi-select state list, removable chips; strict conjunction;
unknown state never local; saved states+mode survive save / reopen / restart."""
from __future__ import annotations

import re
from urllib.parse import urlencode

import pytest

from operator_ui import market_search as ms
from operator_ui import market_view as mv
from tests.test_market_f47 import PIN, cache, post, req, ui  # noqa: F401
from tests.test_market_f56 import _fresh_app_on, _save_form


def get(ui, **qs):
    return req(ui, "GET", "/market?" + urlencode(qs, doseq=True))[2]          # doseq: a repeated `state` like the browser's checkboxes


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


def L(id, state, dist, bid=50.0, title="trailer"):
    return {"id": id, "title": f"{title} {id}", "text": f"{title} {id}", "bid": bid, "distance": dist, "state": state, "closes": "2026-11-01", "category": "trailer", "city": None}


def Q(**kw):
    base = {"go": ["1"], "broad": ["1"], "radius": ["150"]}
    base.update({k: v if isinstance(v, list) else [v] for k, v in kw.items()})
    return ms.parse_query(base)


LOTS = [L("a", "AR", 20), L("b", "AR", 200), L("c", "TX", 300), L("d", "OK", 120), L("e", None, None), L("f", "TX", None), L("g", "AR", 30, bid=900.0)]
ids = lambda rs: sorted(c["id"] for c in rs)  # noqa: E731


def test_default_is_by_distance_and_unchanged():
    q = Q()
    assert q["loc_mode"] == "distance" and q["states"] == [] and not q["errors"]
    res, unk, _ = ms.partition(LOTS, q)
    assert ids(res) == ["a", "d", "g"] and ids(unk) == ["e", "f"]          # radius 150; unlocated lots are not counted as local


def test_state_mode_multi_state_and_radius_not_silently_applied():
    q = Q(loc_mode="state", state=["AR", "TX"])
    res, unk, hid = ms.partition(LOTS, q)
    assert ids(res) == ["a", "b", "c", "f", "g"] and ids(unk) == ["e"] and hid["state"] == 1     # b (200 mi) and f (no distance) pass: radius is OFF in this mode
    assert "the radius is NOT applied" in mv.scope_text(q)


def test_state_mode_with_also_radius_is_a_labelled_intersection():
    q = Q(loc_mode="state", state=["AR", "TX"], also_radius="1")
    res, unk, _ = ms.partition(LOTS, q)
    assert ids(res) == ["a", "g"] and ids(unk) == ["e", "f"]
    assert "By State: AR, TX AND within 150 mi of Conway AR" == mv.scope_text(q)


def test_strict_conjunction_with_price():
    res, unk, _ = ms.partition(LOTS, Q(loc_mode="state", state="AR", max_price="100"))
    assert ids(res) == ["a", "b"] and "g" not in ids(unk)       # g is AR but $900 > $100


def test_unknown_state_is_never_local_and_only_in_unchecked():
    q = Q(loc_mode="state", state="AR")
    res, unk, _ = ms.partition(LOTS, q)
    assert "e" not in ids(res) and ids(unk) == ["e"] and "state not known" in unk[0]["unchecked"][0]
    assert ms.US_STATES.get("ZZ") is None and ms._states({"state": ["zz"]}) == ([], ["ZZ"])


def test_invalid_state_code_is_a_visible_error():
    q = Q(loc_mode="state", state=["AR", "ZZ"])
    assert any("'ZZ' is not a US state code" in m for m in q["errors"])


def test_empty_selection_in_state_mode_refuses():
    q = Q(loc_mode="state")
    assert q["errors"] and "no state is ticked" in q["errors"][0]
    assert not Q(loc_mode="distance").get("errors")


def test_distance_mode_ignores_ticked_states_and_says_so():
    q = Q(state=["TX"])
    res, _, _ = ms.partition(LOTS, q)
    assert ids(res) == ["a", "d", "g"] and "states are NOT applied" in mv.scope_text(q)


def test_page_renders_panel_modes_checkboxes_chips_and_scope(ui):
    h = get(ui, go=1, broad=1, loc_mode="state", state=["AR", "TX"])
    assert "id='location-panel'" in h and "name='loc_mode' value='distance'" in h and "name='loc_mode' value='state' checked" in h
    assert re.search(r"name='state' value='AR' checked", h) and re.search(r"name='state' value='TX' checked", h) and "name='state' value='OK'>" in h
    chips = re.search(r"<div id='state-chips'.*?</div>", h, re.S).group(0)
    assert chips.count("class='chip'") == 2 and "Remove AR" in chips
    assert "Location: By State: AR, TX; the radius is NOT applied" in h


def test_chip_removal_link_drops_only_that_state(ui):
    h = get(ui, go=1, broad=1, loc_mode="state", state=["AR", "TX"], max_price="500")
    href = re.search(r"<a href='([^']*)' aria-label='Remove AR'", h).group(1).replace("&amp;", "&")
    assert "state=TX" in href and "state=AR" not in href and "max_price=500" in href and "loc_mode=state" in href
    h2 = req(ui, "GET", href)[2]
    assert "Location: By State: TX" in h2 and "Remove AR" not in h2 and "Remove TX" in h2


def test_search_narrows_list_but_keeps_selected(ui):
    h = get(ui, go=1, broad=1, loc_mode="state", state="AR", state_find="tex")
    lst = re.search(r"<div class='st-list'.*?</div>", h, re.S).group(0)
    assert "TX Texas" in lst and "AR Arkansas" in lst and "OK Oklahoma" not in lst          # AR stays (selected) so it is not lost
    assert "No state matches" in re.search(r"<div class='st-list'.*?</div>", get(ui, go=1, state_find="qqq"), re.S).group(0)
    assert "OK Oklahoma" in re.search(r"<div class='st-list'.*?</div>", get(ui, go=1, state_find="ok"), re.S).group(0)


def test_real_results_by_state_on_cache(ui):
    from operator_ui.market_search import load_gsa
    from tests.test_market_f47 import NOW
    cards = load_gsa(None, NOW)["cards"]
    known = {c["state"] for c in cards if c["state"]}
    assert known and all(s in ms.US_STATES for s in known)
    pick = sorted(known)[0]
    res, unk, _ = ms.partition(cards, Q(loc_mode="state", state=pick))
    assert res and all(c["state"] == pick for c in res) and all(c["state"] is None for c in unk)
    assert f"{len(res)} result" in get(ui, go=1, broad=1, loc_mode="state", state=pick)


def test_saved_roundtrip_reopen_and_restart(ui, tmp_path):
    h = get(ui, go=1, broad=1, loc_mode="state", state=["AR", "TX"], also_radius="1", max_price="500", min_price="10", radius="150", condition="used")
    f = _save_form(h)["fields"]
    assert f["loc_mode"] == "state" and f["state"] == "AR,TX" and f["also_radius"] == "1"
    st, loc, _ = post(ui, "/market/save", **{k: v for k, v in f.items() if k not in ("csrf", "nonce", "pin", "title")}, title="f136")
    assert st == 303 and "created" in loc
    c = ui.campaign_records()[0]["doc"]
    assert {"locmode:state", "states:AR>TX", "alsorad:1"} <= set(c["criteria"]["nice_to_have"])
    assert "locmode" not in " ".join(c["criteria"]["preferred"] if "preferred" in c["criteria"] else [])
    cid = c["campaign_id"]

    def check(h):
        assert "Location: By State: AR, TX AND within 150 mi" in h and "Min price: $10" in h and "Max price: $500" in h and "Condition: used" in h and "filter-errors" not in h
        assert "name='state' value='AR' checked" in h and "name='also_radius' value='1' checked" in h and "locmode" not in h
    check(get(ui, run=cid))
    app2, httpd2 = _fresh_app_on(ui, tmp_path)
    try:
        check(req(app2, "GET", "/market?" + urlencode({"run": cid}))[2])
    finally:
        httpd2.shutdown()
        httpd2.server_close()


def test_state_choice_persists_across_navigation_and_restart_via_prefs(ui):
    get(ui, go=1, broad=1, loc_mode="state", state=["OK"])
    h = get(ui)                                                     # a visit with no filters restores the last search
    assert "Location: By State: OK" in h


def test_nothing_in_defaults_changed_local_default(ui):
    h = get(ui)
    assert "value='Conway AR'" in h and "value='150.0'" in h and "Radius: 150 mi (known distances only); Location mode: By Distance" in h
