"""C-19 golden cases from Michael's three training examples (ARIA-20261007-1840, ADR-0012).

Numbers are illustrative inputs shaped by the examples, not real listings. They exist to prove
that the engine ranks by capital velocity and class, not by a universal absolute-profit floor.
"""

from __future__ import annotations

import copy

from worked_cases import _meta, _ulid, item


def tv_65_inch() -> dict:
    """~$30 TV that becomes $75-100 in about an hour; binary panel risk; parts-out floor."""
    return item(101, "flip", "other_asset", "65 inch LED TV, no picture (backlight?)", 4, {
        "acquisition": {"ask_price": 40, "expected_buy_price": 30, "buy_fees": 0, "listing_age_hours": 1},
        "rehab": {"parts_cost": 0, "materials_cost": 0, "labor_hours": 0.25, "admin_hours": 0.25,
                  "required_skills": ["electrical_diagnosis"], "repair_success_prob": 0.8,
                  "repair_scope_known": True},
        "logistics": {"trips": [{"purpose": "inspect_pickup", "round_trip_miles": 8}]},
        "holding": {"expected_hold_days": 0.04, "sell_fees_rate": 0, "sell_fees_flat": 0},
        "resale": {"target_sell_price": 90, "comp_price_low": 75, "comp_price_expected": 90,
                   "comp_price_high": 100, "sale_prob": 0.9, "expected_dom_days": 1,
                   "active_comparable_listings": 5},
        "downside": {"salvage_if_repair_fails": 15, "salvage_if_unsold": 40},
        "context": {"seasonality_factor": 1},
        "estimates_meta": _meta({"sold_comps_count": 4, "condition_verified": True, "title_verified": True,
                                 "demand_evidence": True, "seller_screened": True}),
    })


def mower_late_season() -> dict:
    """Older riding mower, late season, funds tight: big spread but cash trapped for months."""
    return item(102, "flip", "mower", "Older riding mower, needs carburetor", 12, {
        "acquisition": {"ask_price": 800, "expected_buy_price": 650, "buy_fees": 0, "listing_age_hours": 30},
        "rehab": {"parts_cost": 120, "materials_cost": 20, "labor_hours": 4, "admin_hours": 1,
                  "required_skills": ["small_engine_repair"], "repair_success_prob": 0.9,
                  "repair_scope_known": True},
        "logistics": {"trips": [{"purpose": "inspect_pickup", "round_trip_miles": 24},
                                {"purpose": "buyer_meet", "round_trip_miles": 16}]},
        "holding": {"storage_cost_per_day": 0.5, "expected_hold_days": 120, "sell_fees_rate": 0,
                    "sell_fees_flat": 0},
        "resale": {"target_sell_price": 1400, "comp_price_low": 1250, "comp_price_expected": 1400,
                   "comp_price_high": 1500, "sale_prob": 0.8, "expected_dom_days": 90,
                   "active_comparable_listings": 9},
        "downside": {"salvage_if_repair_fails": 250, "salvage_if_unsold": 900},
        "context": {"seasonality_factor": 0.2},
        "estimates_meta": _meta({"sold_comps_count": 4, "condition_verified": True, "title_verified": True,
                                 "demand_evidence": True, "seller_screened": True}),
    })


def recon_250_non_running() -> dict:
    """Non-running Honda Recon 250 at ~$300: a different class; hunting-season liquidity."""
    return item(103, "flip", "other_asset", "Honda Recon 250 ATV, non-running", 20, {
        "acquisition": {"ask_price": 350, "expected_buy_price": 300, "buy_fees": 0, "listing_age_hours": 5},
        "rehab": {"parts_cost": 150, "materials_cost": 20, "labor_hours": 8, "admin_hours": 1,
                  "required_skills": ["small_engine_repair", "mechanical_diagnosis"],
                  "repair_success_prob": 0.6, "repair_scope_known": False},
        "logistics": {"trips": [{"purpose": "inspect_pickup", "round_trip_miles": 40},
                                {"purpose": "buyer_meet", "round_trip_miles": 20}],
                      "transport": {"mode": "requires_trailer", "extra_cash": 20, "extra_hours": 1}},
        "holding": {"expected_hold_days": 21, "sell_fees_rate": 0, "sell_fees_flat": 0},
        "resale": {"target_sell_price": 1000, "comp_price_low": 850, "comp_price_expected": 1000,
                   "comp_price_high": 1100, "sale_prob": 0.85, "expected_dom_days": 14,
                   "active_comparable_listings": 6},
        "downside": {"salvage_if_repair_fails": 250, "salvage_if_unsold": 600},
        "context": {"seasonality_factor": 0.9},
        "estimates_meta": _meta({"sold_comps_count": 3, "condition_verified": False, "title_verified": True,
                                 "demand_evidence": True, "seller_screened": True}),
    })


CLASS_CASES = {"tv_65_inch": tv_65_inch, "mower_late_season": mower_late_season,
               "recon_250_non_running": recon_250_non_running}


def fresh(name: str) -> dict:
    return copy.deepcopy(CLASS_CASES[name]())
