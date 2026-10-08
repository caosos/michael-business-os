"""F-17: the ADR-0012 capital fields on the card (Michael's training examples). Pure rendering of mbos.card output."""

from __future__ import annotations

import copy
import json
import os
import re
from pathlib import Path

import pytest

from mbos import card as mc
from operator_ui import card_view

ROOT = Path(__file__).resolve().parent.parent
BASE = json.loads((ROOT / "docs/research/contracts/examples/item-flip-trailer.example.json").read_text())
PROFILE = mc.load_profile(os.environ.get("MBOS_OPERATOR_PROFILE"))


def scenario(*, cash, net, days, p_ok=0.9, scope=True, salvage=0, dom=3, sale_prob=0.95, comp_low=None, comp_high=None, profile=None):
    item = copy.deepcopy(BASE)
    d = item["scores"]["scorecard"].setdefault("derived", {})
    d.update(cash_tied_up=cash, ev_net_profit=net, time_to_cash_days=days, skill_fit=0.9, cost_out=cash, net_profit_deterministic=net)
    e = item["economics"]
    e["rehab"].update(repair_success_prob=p_ok, repair_scope_known=scope)
    e["downside"]["salvage_if_repair_fails"] = salvage
    e["resale"].update(sale_prob=sale_prob, expected_dom_days=dom)
    if comp_low is not None:
        e["resale"].update(comp_price_low=comp_low, comp_price_high=comp_high)
    return mc.build_card(item, [], [], profile=profile or PROFILE)


def page(card):
    return card_view.render_item_card(card, mc.validate_card(card), "")


def capital(card):
    return card_view.render_capital(card)


def test_micro_flip_tv_shows_class_multiple_velocity_and_downside_together():
    c = scenario(cash=30, net=45, days=0.1, p_ok=0.8, salvage=15, comp_low=60, comp_high=100)       # the $30 TV
    assert mc.validate_card(c) == []
    h = capital(c)
    assert "Micro flip" in h and "2.5x" in h and "Capital velocity" in h
    assert "Downside: repair fails outright" in h and "20% " not in h and "0.2" in h          # downside beside the headline numbers
    assert h.index("Micro flip") < h.index("Downside") < h.index("Parts-out floor")
    assert "$15" in h                                                                          # parts-out floor
    assert "Capital: why a small fast flip can outrank a big slow one" in page(c)
    assert page(c).index("Estimated numbers") < page(c).index("Capital: why") < page(c).index("Value-add plan")
    assert "$30–$70" in page(c)                                                                # gross profit range (low/high)


def test_late_season_mower_is_capital_intensive_with_trapped_cash():
    c = scenario(cash=900, net=700, days=150, p_ok=0.9, dom=120, sale_prob=0.6)
    h = capital(c)
    assert "Capital-intensive flip" in h and "Micro flip" not in h
    assert any("capital-intensive" in w for w in c["why"]) and any("capital-intensive" in w for w in re.findall(r"<li>(.*?)</li>", page(c)))


def test_non_running_recon_is_high_repair_uncertainty_and_not_the_tvs_class():
    tv = scenario(cash=30, net=45, days=0.1)
    recon = scenario(cash=300, net=500, days=14, p_ok=0.75, scope=False, salvage=120)
    assert "Standard flip" in capital(recon) and "Micro flip" in capital(tv)
    assert re.search(r"Repair uncertainty</td><td>high", capital(recon))


def test_unknown_is_visible_especially_the_cash_situation():
    c = scenario(cash=30, net=45, days=0.1)
    h = capital(c)
    assert "Cash situation: UNKNOWN." in h and "You have not told the system how much cash you have free right now" in h
    assert "economics.current_cash_context" in c["unknowns"]
    assert "<b class='unk'>UNKNOWN</b>" in h                                                    # personal-use value has no source either
    prof = copy.deepcopy(PROFILE)
    prof["current_cash_context"] = {"value": "tight: about $400 available this week"}
    h2 = capital(scenario(cash=30, net=45, days=0.1, profile=prof))
    assert "Cash situation:</b> tight: about $400 available this week" in h2 and "Cash situation: UNKNOWN" not in h2


def test_missing_numbers_render_unknown_not_invented():
    item = copy.deepcopy(BASE)
    item.pop("scores")
    c = mc.build_card(item, [], [], profile=PROFILE)
    h = capital(c)
    assert mc.validate_card(c) == []
    for label in ("Class", "Cash multiple", "Capital velocity (per day)"):          # derived from the missing scorecard numbers
        cell = h.split(label)[1].split("</div></div>")[0]
        assert "UNKNOWN" in cell, label
    assert "x <span" not in h.split("Cash multiple")[1].split("</div></div>")[0]                # no made-up multiple


def test_a_card_without_the_optional_fields_still_renders():
    c = scenario(cash=30, net=45, days=0.1)
    for k in ("opportunity_class", "cash_multiple", "capital_velocity", "parts_out_floor", "catastrophic_downside_probability",
              "repair_uncertainty", "liquidity", "skill_fit", "personal_use_value", "current_cash_context"):
        c["economics"].pop(k, None)
    h = capital(c)                                                                              # an older card: all UNKNOWN, no crash
    assert h.count("UNKNOWN") >= 8 and "the card does not carry this field" in h


def test_hostile_text_in_capital_fields_is_escaped():
    c = scenario(cash=30, net=45, days=0.1)
    c["economics"]["liquidity"] = {"value": "<script>alert(1)</script>", "basis": "INFERENCE"}
    c["economics"]["current_cash_context"] = {"value": "<img src=x onerror=alert(2)>", "basis": "FACT"}
    h = capital(c)
    assert "<script>" not in h and "<img " not in h and "&lt;script&gt;" in h


def test_ui_never_sorts_or_filters_by_absolute_profit():
    """ADR-0012: there is no universal profit floor. The UI may order by lane C's ranking, time, or deadline, but never by
    profit/EV amount, and never filters rows by a profit threshold."""
    offenders = []
    for p in (ROOT / "operator_ui").glob("*.py"):
        for n, line in enumerate(p.read_text().splitlines(), 1):
            low = line.lower()
            if ("sorted(" in low or ".sort(" in low or "order by" in low or "reverse=" in low) and re.search(
                    r"profit|ev_net|\bev\b|net_profit|revenue|gross|value_per_hour|\bpph\b", low):
                offenders.append(f"{p.name}:{n}: {line.strip()}")
            if re.search(r"(profit|ev_net|net_profit)\w*\s*(>=|<=|>|<)\s*\d", low) or re.search(r"min_profit|profit_floor", low):
                offenders.append(f"{p.name}:{n}: {line.strip()}")
    assert offenders == [], offenders


def test_capital_section_is_on_the_live_page(rt, discover, ui):
    from tests.test_operator_ui import ready, req

    item_id, _ = ready(rt, discover)
    body = req(ui, "GET", f"/item/{item_id}")[2]
    assert "Capital: why a small fast flip can outrank a big slow one" in body and "Cash situation: UNKNOWN." in body
    assert "There is no universal profit floor (ADR-0012)" in body
