"""A-60: exact-listing hide (X) by stable ID, independent of the suggestions toggle, in checked and unchecked sections, durable across restart,
per-item Undo, no learning from X, saved preserved, strict filters never relaxed, honest exhausted state."""
from __future__ import annotations

import json
import re

import pytest

from operator_ui import market_prefs as mp
from operator_ui import market_search as ms
from tests.test_market_f47 import cache, get, post, ui  # noqa: F401
from tests.test_market_f52 import lots


@pytest.fixture(autouse=True)
def prefs_file(tmp_path, monkeypatch):
    monkeypatch.setenv("MBOS_MARKET_PREFS_FILE", str(tmp_path / "prefs.json"))


Q = dict(go=1, broad=1, radius=150, max_price=2000, base="Conway AR")


def ids(h: str, section="main") -> list[str]:
    if section == "main":
        h = h.split("id='unchecked-section'")[0]
    else:
        h = h.split("id='unchecked-section'")[1] if "id='unchecked-section'" in h else ""
    return re.findall(r"data-lot='([^']+)'", h)


def test_x_control_is_accessible_distinct_and_keyboard_operable(ui):
    h = get(ui, **Q)
    assert re.search(r"<button name='act' value='hide' class='mk-x' type='submit' aria-label='Hide this listing'", h)
    assert h.count("value='hide'") == len(ids(h)) + len(ids(h, "unchecked"))
    assert "value='dismiss' title='Hides this listing and counts its title words as less like this'>Not interested" in h


def test_hide_persists_with_toggle_on_and_off_and_after_restart(ui):
    first = ids(get(ui, **Q))[0]
    post(ui, "/market/pref", act="hide", lot=first, title="t")
    for act in ("enable", "disable", "enable"):
        post(ui, "/market/pref", act=act)
        assert first not in ids(get(ui, **Q)) and first in get(ui, **Q)          # in the hidden list only
    assert first in mp.load()["hidden"]
    assert first not in ids(get(ui, **Q))     # a fresh load() = what a restarted server reads
    assert json.loads(mp.path().read_text())["hidden"].get(first) is not None


def test_hide_applies_to_unchecked_section_and_undo_restores_one(ui):
    un = ids(get(ui, **Q), "unchecked")
    assert un, "fixture must have unchecked lots"
    main = ids(get(ui, **Q))
    a, b = un[0], main[0]
    post(ui, "/market/pref", act="save", lot=main[1], title="saved one")
    post(ui, "/market/pref", act="hide", lot=a, title="u")
    post(ui, "/market/pref", act="hide", lot=b, title="m")
    h = get(ui, **Q)
    assert a not in ids(h, "unchecked") and b not in ids(h)
    post(ui, "/market/pref", act="restore", lot=b)
    h = get(ui, **Q)
    assert b in ids(h) and a not in ids(h, "unchecked") and mp.load()["saved"] == [main[1]]
    assert f"data-hidden='{a}'" in h and f"data-hidden='{b}'" not in h


def test_x_leaves_all_learning_weights_and_saved_unchanged(ui):
    first = ids(get(ui, **Q))[0]
    mp.act("more", "x", "Utility trailer heavy")
    mp.act("less", "y", "Office chair")
    mp.act("save", first, "Saved trailer")
    before = {k: mp.load()[k] for k in ("more", "less", "saved")}
    mp.act("hide", first, "Utility trailer chair heavy")
    after = mp.load()
    assert {k: after[k] for k in ("more", "less", "saved")} == before and first in after["hidden"]
    mp.act("restore", first)
    assert {k: mp.load()[k] for k in ("more", "less", "saved")} == before


def test_not_interested_is_separate_hides_and_learns_honestly(ui):
    msg = mp.act("dismiss", "z1", "Utility trailer")
    d = mp.load()
    assert "z1" in d["hidden"] and "trailer" in d["less"] and "less like this" in msg
    mp.act("restore", "z1")
    assert "trailer" in mp.load()["less"]                       # restore does not undo learning, and says so in the message above


def test_hide_never_relaxes_filters_or_refills(ui):
    base = ids(get(ui, **{**Q, "max_price": 300}))
    assert base
    post(ui, "/market/pref", act="hide", lot=base[0], title="t")
    after = ids(get(ui, **{**Q, "max_price": 300}))
    assert after == base[1:]                                    # remaining real eligible, same order, nothing added
    assert set(after) <= set(base) and len(set(after)) == len(after)


def test_exhausted_state_is_honest(ui):
    one = ids(get(ui, **{**Q, "max_price": 300}))
    for i in one:
        post(ui, "/market/pref", act="hide", lot=i, title="t")
    h = get(ui, **{**Q, "max_price": 300})
    assert "0 results left" in h and f"All {len(one)} cached listing" in h and "no new fetch was made" in h and "no guaranteed replacement" in h
    assert ids(h) == []


def test_saved_record_survives_hide(ui):
    first = ids(get(ui, **Q))[0]
    mp.act("save", first, "t")
    mp.act("hide", first, "t")
    assert first in mp.load()["saved"]


def test_old_prefs_file_dismissed_ids_migrate_to_hidden(tmp_path):
    mp.path().write_text(json.dumps({"enabled": False, "dismissed": ["9"], "saved": []}))
    assert "9" in mp.load()["hidden"]
