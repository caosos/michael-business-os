"""Worked cases: Item v1 documents (ADR-0004) for both lanes.

Flip categories: trailer, mower, generator, project_vehicle.
Service categories: drywall_repair, smart_home_install, equipment_repair.

Numbers are illustrative (round-one §17 inputs where a case existed), not real
listings. Each case is a function returning a fresh dict so tests can mutate it.
"""

from __future__ import annotations

import copy

SCORED_AT = "2026-10-07T12:00:00Z"


def _ulid(prefix: str, n: int) -> str:
    return f"{prefix}_01JB{n:022d}"


def item(n: int, lane: str, category: str, title: str, miles: float | None, economics: dict,
         *, source: str = "craigslist", research: list[dict] | None = None) -> dict:
    doc = {
        "item_id": _ulid("itm", n),
        "schema_version": "1.0.0",
        "type": lane,
        "category": category,
        "state": "RESEARCHING",
        "created_at": "2026-10-07T10:00:00Z",
        "sources": [{
            "source": source,
            "url": f"https://example.invalid/{category}/{n}",
            "ingestion_method": "rss" if lane == "flip" else "inbound_form",
            "first_seen_at": "2026-10-07T10:00:00Z",
            "provenance_id": _ulid("prov", n * 10),
        }],
        "dedup_key": f"{category}|example|{n}",
        "normalized": {
            "title": title,
            "condition": "used" if lane == "flip" else "n/a",
            "location": {"city": "Conway", "state": "AR", **({"road_miles_one_way": miles} if miles is not None else {})},
        },
        "economics": economics,
    }
    if research:
        doc["research"] = research
    return doc


def _meta(evidence: dict, comps: list | None = None) -> dict:
    m = {"scoring_config_version": "2026.10.1", "evidence": evidence}
    if comps is not None:
        m["comps"] = comps
    return m


# ------------------------------------------------------------------ FLIPS

def trailer_utility() -> dict:
    """Round-one §17.1 inputs exactly (C14 case). 5x8 utility trailer, 20 mi."""
    return item(1, "flip", "trailer", "5x8 utility trailer, needs deck + tire", 20, {
        "acquisition": {"ask_price": 300, "expected_buy_price": 250, "buy_fees": 10,
                        "market_buy_median": 500, "listing_age_hours": 2},
        "rehab": {"parts_cost": 160, "materials_cost": 30, "labor_hours": 5, "admin_hours": 1.25,
                  "required_skills": ["carpentry", "trailer_wiring", "painting"],
                  "repair_success_prob": 0.95, "repair_scope_known": True},
        "logistics": {"trips": [{"purpose": "inspect_pickup", "round_trip_miles": 40},
                                {"purpose": "buyer_meet", "round_trip_miles": 16}]},
        "holding": {"storage_cost_per_day": 3, "expected_hold_days": 9, "sell_fees_rate": 0, "sell_fees_flat": 0},
        "resale": {"target_sell_price": 1050, "comp_price_low": 950, "comp_price_expected": 1050,
                   "comp_price_high": 1150, "sale_prob": 0.85, "expected_dom_days": 7,
                   "active_comparable_listings": 6},
        "downside": {"salvage_if_repair_fails": 220, "salvage_if_unsold": 700},
        "estimates_meta": _meta({"sold_comps_count": 4, "condition_verified": True, "title_verified": True,
                                 "demand_evidence": True, "seller_screened": True}),
    }, research=[{"finding": "4 refurbished 5x8 utility trailers sold $950-$1,150 in 60 d (illustrative)",
                  "field": "resale.target_sell_price", "basis": "FACT",
                  "source_uri": "https://example.invalid/comps/trailer", "fetched_at": "2026-10-07T10:30:00Z",
                  "provenance_id": _ulid("prov", 11)}])


def trailer_utility_at_walkaway() -> dict:
    d = trailer_utility()
    d["item_id"] = _ulid("itm", 2)
    d["economics"]["acquisition"]["expected_buy_price"] = 225
    return d


def mower_no_start() -> dict:
    """Round-one §17.2 inputs. Riding mower, 'won't start', 35 mi; fault guessed."""
    return item(3, "flip", "mower", "Riding mower, won't start", 35, {
        "acquisition": {"ask_price": 150, "expected_buy_price": 150, "buy_fees": 0, "market_buy_median": 250},
        "rehab": {"parts_cost": 150, "materials_cost": 0, "labor_hours": 4, "admin_hours": 1.25,
                  "required_skills": ["small_engine_repair", "mechanical_diagnosis"],
                  "repair_success_prob": 0.70, "repair_scope_known": False},
        "logistics": {"trips": [{"purpose": "inspect_pickup", "round_trip_miles": 70},
                                {"purpose": "buyer_meet", "round_trip_miles": 14}]},
        "holding": {"storage_cost_per_day": 2, "expected_hold_days": 14},
        "resale": {"target_sell_price": 650, "comp_price_low": 550, "comp_price_high": 750,
                   "sale_prob": 0.80, "expected_dom_days": 14, "active_comparable_listings": 9},
        "downside": {"salvage_if_repair_fails": 90, "salvage_if_unsold": 480},
        "estimates_meta": _meta({"sold_comps_count": 3, "demand_evidence": True}),
    })


def mower_compression_confirmed() -> dict:
    """§17.2 evidence flip: seller confirms it cranks with compression; carb diagnosed."""
    d = mower_no_start()
    d["item_id"] = _ulid("itm", 4)
    r = d["economics"]["rehab"]
    r["repair_success_prob"] = 0.90
    r["repair_scope_known"] = True
    d["economics"]["estimates_meta"]["evidence"].update({"seller_screened": True, "condition_verified": True})
    return d


def generator_far() -> dict:
    """Round-one §17.3 inputs. Standby generator, 'needs work', 160 mi one-way."""
    return item(5, "flip", "generator", "Standby generator, needs work", 160, {
        "acquisition": {"ask_price": 600, "expected_buy_price": 600, "buy_fees": 0, "market_buy_median": 900},
        "rehab": {"parts_cost": 350, "materials_cost": 0, "labor_hours": 6, "admin_hours": 2,
                  "required_skills": ["electrical_diagnosis", "small_engine_repair"],
                  "repair_success_prob": 0.60, "repair_scope_known": False},
        "logistics": {"trips": [{"purpose": "inspect_pickup", "round_trip_miles": 320},
                                {"purpose": "buyer_meet", "round_trip_miles": 20}]},
        "holding": {"storage_cost_per_day": 3, "expected_hold_days": 21},
        "resale": {"target_sell_price": 2200, "comp_price_low": 1900, "comp_price_high": 2500,
                   "sale_prob": 0.85, "expected_dom_days": 21, "active_comparable_listings": 12},
        "downside": {"salvage_if_repair_fails": 400, "salvage_if_unsold": 1600},
        "estimates_meta": _meta({"sold_comps_count": 3}),
    })


def project_vehicle_civic() -> dict:
    """New round-two case. 2002 sedan, dead alternator + worn brakes (both diagnosed), 25 mi."""
    return item(6, "flip", "project_vehicle", "2002 sedan, needs alternator + brakes", 25, {
        "acquisition": {"ask_price": 1100, "expected_buy_price": 950, "buy_fees": 95,
                        "market_buy_median": 1300, "listing_age_hours": 20},
        "rehab": {"parts_cost": 260, "materials_cost": 40, "labor_hours": 6, "admin_hours": 3,
                  "required_skills": ["electrical_diagnosis", "maintenance", "mechanical_diagnosis"],
                  "repair_success_prob": 0.90, "repair_scope_known": True},
        "logistics": {"trips": [{"purpose": "inspect_pickup", "round_trip_miles": 50}]},
        "holding": {"storage_cost_per_day": 1, "expected_hold_days": 21},
        "resale": {"target_sell_price": 2600, "comp_price_low": 2300, "comp_price_high": 2900,
                   "sale_prob": 0.80, "expected_dom_days": 18, "active_comparable_listings": 14},
        "downside": {"salvage_if_repair_fails": 700, "salvage_if_unsold": 1900},
        "estimates_meta": _meta({"condition_verified": True, "title_verified": True, "demand_evidence": True,
                                 "seller_screened": True},
                                comps=[{"sold_price": p, "sold_date": "2026-09-1%d" % i, "source": "example"}
                                       for i, p in enumerate([2300, 2450, 2600, 2700, 2900])]),
    })


def project_vehicle_truck_over_cap() -> dict:
    """New round-two case. Profitable truck that breaks the $1,500 cash-per-deal cap."""
    d = project_vehicle_civic()
    d["item_id"] = _ulid("itm", 7)
    d["normalized"]["title"] = "2008 pickup, needs fuel pump"
    a = d["economics"]["acquisition"]
    a.update({"ask_price": 2600, "expected_buy_price": 2400, "buy_fees": 170, "market_buy_median": 3200})
    d["economics"]["resale"].update({"target_sell_price": 4800, "comp_price_low": 4300, "comp_price_high": 5300})
    d["economics"]["downside"].update({"salvage_if_repair_fails": 1900, "salvage_if_unsold": 3800})
    d["economics"]["rehab"]["parts_cost"] = 320
    # R13 (C-05): the asking price is attested from the listing, so this cash-cap PASS is evidence-backed
    d["economics"]["estimates_meta"]["assumptions"] = [
        {"field": "economics.acquisition.ask_price", "value": 2600, "basis": "FACT", "note": "listing price"}]
    return d


def trailer_enclosed_coordinator() -> dict:
    """Agent 01's contracts/examples/item-flip-trailer.example.json economics, unchanged (C23)."""
    return item(8, "flip", "trailer", "6x12 enclosed trailer, needs lights + floor", 32, {
        "acquisition": {"ask_price": 1200, "expected_buy_price": 1050, "buy_fees": 25},
        "rehab": {"parts_cost": 120, "materials_cost": 180, "labor_hours": 6, "admin_hours": 2,
                  "required_skills": ["trailer_wiring", "carpentry"], "repair_success_prob": 0.95,
                  "repair_scope_known": True},
        "logistics": {"trips": [{"purpose": "inspect_pickup", "round_trip_miles": 64, "can_combine": False},
                                {"purpose": "buyer_meet", "round_trip_miles": 20}],
                      "vehicle_mpg": 18, "fuel_price_per_gal": 3.2, "wear_per_mile": 0.28, "avg_speed_mph": 45},
        "holding": {"storage_cost_per_day": 3, "expected_hold_days": 14, "disposal_cost": 0,
                    "sell_fees_rate": 0, "sell_fees_flat": 0},
        "resale": {"target_sell_price": 2100, "comp_price_low": 1800, "comp_price_expected": 2100,
                   "comp_price_high": 2400, "sale_prob": 0.85, "expected_dom_days": 14},
        "downside": {"salvage_if_repair_fails": 900, "salvage_if_unsold": 1000},
        "estimates_meta": {"scoring_config_version": "2026.10.0",
                           "assumptions": [{"field": "rehab.labor_hours", "value": 6, "basis": "INFER",
                                            "note": "illustrative"}]},
    })


# ------------------------------------------------------------------ SERVICES

def drywall_basement() -> dict:
    """Round-one §17.4 inputs. Awarded hang + finish, 8 mi."""
    return item(20, "service", "drywall_repair", "Hang + finish 12x14 basement room + closet", 8, {
        "logistics": {"trips": [{"purpose": "work_day", "round_trip_miles": 16},
                                {"purpose": "work_day", "round_trip_miles": 16},
                                {"purpose": "work_day", "round_trip_miles": 16},
                                {"purpose": "material_run", "round_trip_miles": 10}]},
        "job": {"quoted_revenue": 1850, "labor_revenue": 1530, "materials_cost": 320, "material_markup_rate": 0,
                "labor_hours": 14, "admin_hours": 1.5, "disposal_cost": 15,
                "required_skills": ["drywall_hang", "drywall_finish"],
                "win_prob": 1.0, "completion_prob": 0.98, "payment_terms_days": 5, "deposit_rate": 0,
                "job_days": 3, "lead_quality": 0.5},
        "estimates_meta": _meta({"scope_verified": True, "customer_screened": True, "price_agreed_in_writing": True,
                                 "materials_priced": True, "access_and_schedule_confirmed": True}),
    }, source="referral")


def drywall_patch_coordinator() -> dict:
    """Agent 01's contracts/examples/item-service-drywall.example.json economics, unchanged (C23)."""
    return item(21, "service", "drywall_repair", "Drywall patch after plumbing repair", 8, {
        "logistics": {"trips": [{"purpose": "estimate_visit", "round_trip_miles": 16},
                                {"purpose": "work_day", "round_trip_miles": 16},
                                {"purpose": "work_day", "round_trip_miles": 16}]},
        "job": {"quoted_revenue": 450, "materials_cost": 40, "labor_hours": 4, "admin_hours": 1,
                "required_skills": ["drywall"], "win_prob": 0.6, "completion_prob": 0.95,
                "deposit_rate": 0.25, "lead_quality": 0.6},
        "estimates_meta": {"scoring_config_version": "2026.10.0"},
    }, source="website_lead")


def smart_home_install() -> dict:
    """Round-one §17.5 inputs. Customer-supplied devices, 14 mi."""
    return item(22, "service", "smart_home_install", "6 switches, doorbell, 3 cameras, hub", 14, {
        "logistics": {"trips": [{"purpose": "work_day", "round_trip_miles": 28},
                                {"purpose": "work_day", "round_trip_miles": 28}]},
        "job": {"quoted_revenue": 900, "labor_revenue": 900, "materials_cost": 40,
                "labor_hours": 6, "admin_hours": 1,
                "required_skills": ["smart_home_install", "low_voltage_wiring", "network_config"],
                "win_prob": 1.0, "completion_prob": 0.97, "payment_terms_days": 0, "job_days": 2,
                "lead_quality": 0.6, "lead_age_hours": 3},
        "estimates_meta": _meta({"scope_verified": True, "customer_screened": True, "price_agreed_in_writing": True,
                                 "materials_priced": True, "access_and_schedule_confirmed": True,
                                 "repeat_or_referral": True}),
    }, source="referral")


def smart_home_needs_new_circuit() -> dict:
    """Same job but the EV charger needs a new 240V circuit: licensed work. Hard PASS."""
    d = smart_home_install()
    d["item_id"] = _ulid("itm", 23)
    d["economics"]["job"]["required_skills"] = ["smart_home_install", "licensed_electrical"]
    return d


def equipment_repair_zero_turn() -> dict:
    """New round-two case. Mobile repair of a landscaper's zero-turn: hydraulic drive pump.
    Competitive (customer comparing with the dealer), card payment, parts deposit."""
    return item(24, "service", "equipment_repair", "Zero-turn hydraulic pump replacement (on site)", 15, {
        "logistics": {"trips": [{"purpose": "estimate_visit", "round_trip_miles": 30},
                                {"purpose": "work_day", "round_trip_miles": 30},
                                {"purpose": "material_run", "round_trip_miles": 12}]},
        "job": {"quoted_revenue": 1070, "labor_revenue": 650, "materials_cost": 420, "material_markup_rate": 0,
                "labor_hours": 4, "admin_hours": 1, "estimate_hours": 0.75,
                "required_skills": ["equipment_repair", "hydraulics"],
                "win_prob": 0.8, "completion_prob": 0.9, "deposit_rate": 0.4,
                "payment_fee_rate": 0.029, "payment_fee_flat": 0.30, "payment_terms_days": 7,
                "lead_quality": 0.7},
        "estimates_meta": _meta({"scope_verified": True, "customer_screened": True, "materials_priced": True,
                                 "access_and_schedule_confirmed": True, "repeat_or_referral": True}),
    }, source="referral")


FLIP_CASES = {
    "trailer_utility": trailer_utility,
    "trailer_utility_at_walkaway": trailer_utility_at_walkaway,
    "mower_no_start": mower_no_start,
    "mower_compression_confirmed": mower_compression_confirmed,
    "generator_far": generator_far,
    "project_vehicle_civic": project_vehicle_civic,
    "project_vehicle_truck_over_cap": project_vehicle_truck_over_cap,
    "trailer_enclosed_coordinator": trailer_enclosed_coordinator,
}
SERVICE_CASES = {
    "drywall_basement": drywall_basement,
    "drywall_patch_coordinator": drywall_patch_coordinator,
    "smart_home_install": smart_home_install,
    "smart_home_needs_new_circuit": smart_home_needs_new_circuit,
    "equipment_repair_zero_turn": equipment_repair_zero_turn,
}
ALL_CASES = {**FLIP_CASES, **SERVICE_CASES}


def fresh(name: str) -> dict:
    return copy.deepcopy(ALL_CASES[name]())
