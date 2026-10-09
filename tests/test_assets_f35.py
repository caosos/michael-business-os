"""F-35: the /assets figures form. Michael's rough ranges feed C-30 `compare_paths` as INFER research entries (his estimates, never
verified); with example ranges the card recommends a path and shows the others; clearing a range returns it to UNKNOWN."""

from __future__ import annotations

import pytest

from operator_ui import assets_view
from tests.conftest import PIN
from tests.test_assets_f34 import add
from tests.test_operator_ui import req

EXAMPLE = {
    "sell:resale": (500, 800), "sell:hours": (2, 2), "sell:days": (7, 30),
    "minimal:cash": (150, 250), "minimal:hours": (8, 12), "minimal:resale": (1800, 2400), "minimal:days": (14, 30),
    "themed:cash": (600, 900), "themed:hours": (25, 35), "themed:resale": (3500, 5000), "themed:days": (30, 60),
    "convert:cash": (400, 700), "convert:hours": (20, 30), "convert:resale": (2500, 3200), "convert:days": (30, 60),
    "keep:value": (1000, 1000), "keep:cash": (0, 0), "keep:hours": (0, 0)}


def form(ui, ex=EXAMPLE, **kw):
    f = {"csrf": ui.csrf, "pin": PIN, "f_tailgate_months": "9,10,11,12,1", **kw}
    for k, (lo, hi) in ex.items():
        f[f"f_{k}_lo"], f[f"f_{k}_hi"] = str(lo), str(hi)
    return f


def test_example_ranges_make_the_card_recommend_a_path_and_show_the_others(ui):
    path = add(ui)
    assert "nothing is recommended" in req(ui, "GET", path)[2]
    assert req(ui, "POST", path + "/answer", form(ui))[0] == 303
    body = req(ui, "GET", path)[2]
    assert "System leans" in body and "nothing is recommended" not in body and "INFERENCE, not verified" in body
    for p in ("SELL_AS_IS_OR_PART_OUT", "MINIMAL_REHAB_FLIP", "THEMED_VALUE_ADD_FLIP", "CONVERT", "KEEP"):
        assert p in body
    assert "Verified facts: 0" in body and "your estimates" in body
    item = assets_view.to_item("a", ui.assets[path.split("/")[-1]], "michael")
    figs = [r for r in item["research"] if r["field"] in {"owned:" + k for k in EXAMPLE}]
    assert len(figs) == len(EXAMPLE) and {r["basis"] for r in figs} == {"INFER"} and all(r["entered_by"] == "michael" for r in figs)


def test_clearing_a_range_returns_it_to_unknown(ui):
    path = add(ui)
    req(ui, "POST", path + "/answer", form(ui))
    assert "owned:themed:resale" not in req(ui, "GET", path)[2]
    clear = {"f_themed:resale_lo": "", "f_themed:resale_hi": ""}
    assert req(ui, "POST", path + "/answer", {"csrf": ui.csrf, "pin": PIN, **clear})[0] == 303
    body = req(ui, "GET", path)[2]
    assert "owned:themed:resale" in body and "themed:resale" not in ui.assets[path.split("/")[-1]]["figures"]
    assert "owned:minimal:resale" not in body                                  # others untouched
    req(ui, "POST", path + "/answer", {"csrf": ui.csrf, "pin": PIN, "f_tailgate_months": ""})
    assert "owned:tailgate_months" in req(ui, "GET", path)[2]


@pytest.mark.parametrize("lo,hi", [("abc", "5"), ("-1", "5"), ("9", "3"), ("nan", "nan"), ("inf", "inf"), ("1e9", "1e9")])
def test_bad_numbers_are_refused_and_nothing_is_kept(ui, lo, hi):
    path = add(ui)
    st, _, body = req(ui, "POST", path + "/answer", {"csrf": ui.csrf, "pin": PIN, "f_minimal:cash_lo": lo, "f_minimal:cash_hi": hi})
    assert st == 200 and not ui.assets[path.split("/")[-1]].get("figures")


def test_months_validated_and_pin_csrf_required(ui):
    path = add(ui)
    assert req(ui, "POST", path + "/answer", {"csrf": ui.csrf, "pin": PIN, "f_tailgate_months": "13"})[0] == 200
    assert not ui.assets[path.split("/")[-1]].get("figures")
    assert req(ui, "POST", path + "/answer", {**form(ui), "pin": "0000"})[0] == 200
    assert req(ui, "POST", path + "/answer", {**form(ui), "csrf": "x"})[0] == 200
    assert not ui.assets[path.split("/")[-1]].get("figures")
