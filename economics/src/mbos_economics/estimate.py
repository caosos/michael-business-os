"""RESEARCH/estimate producer (C-01): fill ``Item.economics`` for the scoring engine.

``estimate_item(item, bundle, as_of)`` is a pure, deterministic function of:

* the Item's **structured** fields only (type, category, normalized.price,
  condition, location, ends_at, flags, sources[].source / first_seen_at). It never
  reads title or description text, so injected instructions in a listing cannot
  move a number;
* an optional **research bundle** of evidence, every piece of which carries a
  ``provenance_id`` (no evidence without provenance)::

      {
        "comps":        [{"kind": "sold"|"asking", "price": 950, "sold_date": "2026-09-20",
                          "source": "ebay", "url": "...", "dom_days": 9, "provenance_id": "prov_..."}],
        "as_is_comps":  [ ...same shape; prices of similar items in as-is condition... ],
        "active_comparable_listings": 7,          # + "active_comparable_listings_provenance_id"
        "evidence":     {"condition_verified": true, ...},   # + "evidence_provenance_id"
        "overrides":    {"rehab.parts_cost": {"value": 140, "basis": "FACT",
                                              "provenance_id": "prov_...", "note": "..."}}
      }

* versioned category priors (``config/estimation-priors.json``).

Rules: a flip resale price is NEVER guessed from priors (no comps => status
``insufficient`` with a blocking gap). Evidence flags are never set by the estimator
itself. Every estimated field gets an ``estimates_meta.assumptions[]`` entry with a
basis tag. The caller supplies ``as_of``; the clock is never read.
"""

from __future__ import annotations

import copy
import json
import math
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import __version__ as ESTIMATOR_VERSION
from .canonical import CanonicalError, content_hash, derived_ulid, parse_ts
from .comps import aggregate_sold_comps
from .config import CONFIG_DIR, ScoringConfig, load_config
from .inputs import FLIP_CATEGORIES, SERVICE_CATEGORIES
from .numeric import D, ONE, ZERO, fine, money, to_json_number

ESTIMATE_SPEC = "mbos.economics.estimate/v1"
TOOL_NAME = "mbos_economics.estimate"
PRIORS_FORMAT = 1

_FLIP_BLOCKS = {"acquisition", "rehab", "holding", "resale", "downside"}
_SERVICE_BLOCKS = {"job"}
_CONDITIONS = {"new", "used", "parts", "unknown"}
_LONG_BASIS = {"FACT": "FACT", "INFER": "INFERENCE", "REC": "RECOMMENDATION", "UNK": "UNKNOWN"}


class BundleError(ValueError):
    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# --------------------------------------------------------------------------- priors

def load_priors(config_dir: Path = CONFIG_DIR) -> ScoringConfig:
    """Priors reuse the config accessor (get/num/group); they have their own version."""
    raw = json.loads((config_dir / "estimation-priors.json").read_text(encoding="utf-8"),
                     parse_float=Decimal, parse_int=Decimal)
    if raw.get("priors_format") != PRIORS_FORMAT:
        raise ValueError(f"estimation priors must be priors_format {PRIORS_FORMAT}")
    return ScoringConfig(version=raw["priors_version"], raw=raw, hash=content_hash(raw))


# --------------------------------------------------------------------------- helpers

class _Ledger:
    """Collects economics values together with their assumption records."""

    def __init__(self) -> None:
        self.assumptions: list[dict] = []
        self.gaps: list[dict] = []

    def note(self, field: str, value: Any, basis: str, note: str) -> Any:
        """Record an assumption; returns the value (Decimals become JSON numbers)."""
        if isinstance(value, Decimal):
            value = to_json_number(value)
        self.assumptions.append({"field": field, "value": copy.deepcopy(value), "basis": basis, "note": note})
        return value

    def gap(self, code: str, detail: str, blocking: bool) -> None:
        self.gaps.append({"code": code, "blocking": blocking, "detail": detail})


def _hours_between(a: str, b: str) -> Decimal:
    return fine(D((parse_ts(b) - parse_ts(a)).total_seconds()) / D(3600))


def _median(xs: list[Decimal]) -> Decimal:
    xs = sorted(xs)
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


def _haversine(lat1, lng1, lat2, lng2) -> Decimal:
    r = [math.radians(float(x)) for x in (lat1, lng1, lat2, lng2)]
    h = math.sin((r[2] - r[0]) / 2) ** 2 + math.cos(r[0]) * math.cos(r[2]) * math.sin((r[3] - r[1]) / 2) ** 2
    return D(round(3958.8 * 2 * math.asin(math.sqrt(h)), 4))


def _validate_bundle(bundle: dict) -> None:
    p: list[str] = []
    for key in ("comps", "as_is_comps"):
        for i, c in enumerate(bundle.get(key, [])):
            w = f"bundle.{key}[{i}]"
            if not str(c.get("provenance_id", "")).startswith("prov_"):
                p.append(f"{w}.provenance_id is required")
            if c.get("kind") not in ("sold", "asking"):
                p.append(f"{w}.kind must be 'sold' or 'asking'")
            price = c.get("price")
            if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
                p.append(f"{w}.price must be a positive number")
            if c.get("kind") == "sold" and not c.get("sold_date"):
                p.append(f"{w}.sold_date is required for a sold comp")
            if c.get("fetched_at") is not None:
                try:
                    parse_ts(c["fetched_at"])
                except (TypeError, ValueError):
                    p.append(f"{w}.fetched_at must be an RFC 3339 timestamp with a timezone")
    if "active_comparable_listings" in bundle and not str(
            bundle.get("active_comparable_listings_provenance_id", "")).startswith("prov_"):
        p.append("bundle.active_comparable_listings_provenance_id is required")
    if bundle.get("evidence"):
        if not str(bundle.get("evidence_provenance_id", "")).startswith("prov_"):
            p.append("bundle.evidence_provenance_id is required")
        if "skill_fit_high" in bundle["evidence"]:
            p.append("bundle.evidence.skill_fit_high is derived by the engine, never supplied")
    for path, o in (bundle.get("overrides") or {}).items():
        block = path.split(".")[0]
        if block not in _FLIP_BLOCKS | _SERVICE_BLOCKS or path.count(".") != 1:
            p.append(f"override {path!r}: only <block>.<field> in {sorted(_FLIP_BLOCKS | _SERVICE_BLOCKS)}")
        if not isinstance(o, dict) or "value" not in o:
            p.append(f"override {path!r} needs a value")
        elif o.get("basis") not in ("FACT", "INFER", "REC", "UNK"):
            p.append(f"override {path!r} needs basis FACT|INFER|REC|UNK")
        elif not str(o.get("provenance_id", "")).startswith("prov_"):
            p.append(f"override {path!r} needs a provenance_id")
    if p:
        raise BundleError(p)


def _road_miles(item: dict, pri: ScoringConfig, led: _Ledger) -> Decimal | None:
    loc = (item.get("normalized") or {}).get("location") or {}
    f = "normalized.location.road_miles_one_way"
    if loc.get("road_miles_one_way") is not None:
        return D(loc["road_miles_one_way"])
    rf = pri.num("distance.road_factor")
    if loc.get("lat") is not None and loc.get("lng") is not None:
        straight = _haversine(pri.num("home_base.lat"), pri.num("home_base.lng"), loc["lat"], loc["lng"])
        return led.note(f, fine(straight * rf), "INFER", f"haversine {straight} mi from home base x road factor {rf}")
    city = str(loc.get("city") or "").strip().lower()
    state = str(loc.get("state") or "").strip().lower()
    towns = pri.group("distance.town_road_miles_one_way")
    if city and f"{city}|{state}" in towns:
        return led.note(f, towns[f"{city}|{state}"], "INFER", f"town table: {city}, {state} (approximate; verify)")
    zip_ = str(loc.get("zip") or "")
    if (city == pri.get("home_base.city") and state == pri.get("home_base.state")) or zip_ in pri.get("home_base.zips"):
        return led.note(f, pri.num("distance.same_city_miles_one_way"), "REC", "same city/zip as home base")
    tier = loc.get("geo_tier")
    if tier is not None and str(int(tier)) in pri.group("distance.geo_tier_straight_line_miles"):
        straight = pri.group("distance.geo_tier_straight_line_miles")[str(int(tier))]
        led.gap("distance_approximate", f"road miles from Agent 02 geo_tier {tier} band midpoint; confirm", False)
        return led.note(f, fine(straight * rf), "INFER", f"geo_tier {tier} midpoint {straight} mi x road factor {rf}")
    led.gap("location_unknown", "no road miles, coordinates, known town or geo_tier", True)
    return None


def _comp_fact(c: dict, field: str) -> dict:
    """One FACT research entry per comp, carrying the comp's OWN provenance (C-04)."""
    verb = "sold" if c["kind"] == "sold" else "asking"
    r = {"finding": f"{verb} comp ${c['price']} on {c.get('sold_date', '?')} ({c.get('source', 'research')})",
         "field": field, "basis": "FACT", "provenance_id": c["provenance_id"]}
    if c.get("url"):
        r["source_uri"] = c["url"]
    if c.get("fetched_at"):
        r["fetched_at"] = c["fetched_at"]
    return r


def _apply_overrides(econ: dict, bundle: dict, led: _Ledger) -> None:
    for path, o in sorted((bundle.get("overrides") or {}).items()):
        block, field = path.split(".")
        if block not in econ:
            continue
        econ[block][field] = o["value"]
        led.assumptions = [a for a in led.assumptions if a["field"] != f"economics.{path}"]
        led.note(f"economics.{path}", o["value"], o["basis"],
                 f"override from research ({o['provenance_id']})" + (f": {o['note']}" if o.get("note") else ""))


def _num(x: Decimal) -> int | float:
    return to_json_number(x)


# --------------------------------------------------------------------------- flip

def _estimate_flip(item: dict, bundle: dict, pri: ScoringConfig, miles: Decimal, as_of: str,
                   led: _Ledger, scoring_cfg: ScoringConfig) -> tuple[dict | None, list[dict]]:
    cat = item["category"]
    n = item.get("normalized") or {}
    p = pri.group(f"flip.{cat}")
    cond = n.get("condition") if n.get("condition") in _CONDITIONS else "unknown"
    E = "economics"

    # ---- acquisition
    price = n.get("price") or {}
    ptype = price.get("type")
    acq: dict = {}
    if ptype == "free":
        acq["expected_buy_price"] = led.note(f"{E}.acquisition.expected_buy_price", 0, "FACT", "listed free")
        acq["ask_price"] = 0
    elif price.get("amount") is None:
        led.gap("price_unknown", "listing has no price amount", True)
        return None, []
    else:
        ask = D(price["amount"])
        acq["ask_price"] = led.note(f"{E}.acquisition.ask_price", _num(ask), "FACT", f"normalized.price ({ptype})")
        if ptype in ("auction_current", "starting_bid"):
            f = pri.num("flip_general.auction_expected_over_current_bid")
            buy = money(ask * f)
            led.note(f"{E}.acquisition.expected_buy_price", _num(buy), "REC",
                     f"auction: {ptype} {ask} x {f}; the engine's walk_away_price is the real bid ceiling")
        else:
            buy = money(ask * p["negotiation_factor"])
            led.note(f"{E}.acquisition.expected_buy_price", _num(buy), "REC",
                     f"ask {ask} x negotiation factor {p['negotiation_factor']} (prior)")
        acq["expected_buy_price"] = _num(buy)
    buy = D(acq["expected_buy_price"])
    premium = D(price.get("buyer_premium_pct", 0)) / 100
    fees = money(p["buy_fees_flat"] + (p["buy_fees_pct"] + premium) * buy)
    acq["buy_fees"] = led.note(f"{E}.acquisition.buy_fees", _num(fees), "REC",
                               f"flat {p['buy_fees_flat']} + ({p['buy_fees_pct']} prior + buyer premium {premium}) x buy")
    acq["acquire_lead_days"] = _num(pri.num("flip_general.acquire_lead_days"))
    first_seen = min(s["first_seen_at"] for s in item["sources"])
    age = _hours_between(first_seen, as_of)
    if age >= 0:
        acq["listing_age_hours"] = led.note(f"{E}.acquisition.listing_age_hours", _num(age), "INFER",
                                            "hours since first seen by discovery (a lower bound on true listing age)")
    if n.get("ends_at"):
        left = _hours_between(as_of, n["ends_at"])
        if left >= 0:
            acq["auction_ends_in_hours"] = led.note(f"{E}.acquisition.auction_ends_in_hours", _num(left), "FACT",
                                                    "normalized.ends_at - as_of")
        else:
            led.gap("auction_ended", f"ends_at {n['ends_at']} is before as_of", True)
    research: list[dict] = []
    as_is = bundle.get("as_is_comps") or []
    if as_is:
        ratio = p["ask_to_sold_ratio"]
        vals = [D(c["price"]) * (ONE if c["kind"] == "sold" else ratio) for c in as_is]
        med = money(_median(vals))
        acq["market_buy_median"] = led.note(f"{E}.acquisition.market_buy_median", _num(med), "INFER",
                                            f"median of {len(vals)} as-is comps (asking x {ratio})")
        research += [_comp_fact(c, "acquisition.market_buy_median") for c in as_is]

    # ---- resale (never guessed)
    comps = bundle.get("comps") or []
    sold = [c for c in comps if c["kind"] == "sold"]
    asking = [c for c in comps if c["kind"] == "asking"]
    resale: dict = {}
    if sold:
        agg = aggregate_sold_comps([{"sold_price": c["price"]} for c in sold], scoring_cfg)
        target = agg["comp_price_expected"]
        resale["target_sell_price"] = led.note(f"{E}.resale.target_sell_price", _num(target), "INFER",
                                               f"trimmed median of {len(sold)} sold comps (n used {agg['n_used']})")
        resale["comp_price_expected"] = _num(target)
        if agg["n_used"] >= 2:
            resale["comp_price_low"], resale["comp_price_high"] = _num(agg["comp_price_low"]), _num(agg["comp_price_high"])
        research.append({"finding": f"{len(sold)} sold comps; trimmed median ${target}", "field": "resale.target_sell_price",
                         "basis": "INFERENCE"})
        research += [_comp_fact(c, "resale.target_sell_price") for c in sold]
        if len(sold) < int(scoring_cfg.num("decision_thresholds.min_sold_comps_for_yes_flip")):
            led.gap("thin_comps", f"{len(sold)} sold comps; YES needs "
                    f"{scoring_cfg.num('decision_thresholds.min_sold_comps_for_yes_flip')}", False)
    elif asking:
        ratio = p["ask_to_sold_ratio"]
        target = money(_median([D(c["price"]) for c in asking]) * ratio)
        resale["target_sell_price"] = led.note(f"{E}.resale.target_sell_price", _num(target), "INFER",
                                               f"median of {len(asking)} ASKING comps x ask-to-sold {ratio} (no sold comps)")
        led.gap("no_sold_comps", "resale estimated from asking prices only; YES needs sold comps", False)
        research.append({"finding": f"{len(asking)} asking comps x {ratio}; est. ${target}",
                         "field": "resale.target_sell_price", "basis": "INFERENCE"})
    else:
        led.gap("no_comps", "no comparable prices: resale cannot be estimated (research §14: never guessed)", True)
        return None, []
    target = D(resale["target_sell_price"])
    doms = [D(c["dom_days"]) for c in comps if c.get("dom_days") is not None]
    if doms:
        resale["expected_dom_days"] = led.note(f"{E}.resale.expected_dom_days", _num(fine(_median(doms))), "INFER",
                                               f"median DOM of {len(doms)} comps")
    else:
        resale["expected_dom_days"] = led.note(f"{E}.resale.expected_dom_days", _num(p["expected_dom_days"]), "REC", "prior")
    resale["sale_prob"] = led.note(f"{E}.resale.sale_prob", _num(p["sale_prob"]), "REC", "prior")
    if "active_comparable_listings" in bundle:
        resale["active_comparable_listings"] = led.note(
            f"{E}.resale.active_comparable_listings", int(bundle["active_comparable_listings"]), "FACT",
            f"research ({bundle['active_comparable_listings_provenance_id']})")

    # ---- rehab
    labor = p["labor_hours"][cond]
    rehab = {
        "parts_cost": led.note(f"{E}.rehab.parts_cost", _num(p["parts_cost"][cond]), "REC", f"prior ({cat}, {cond})"),
        "materials_cost": led.note(f"{E}.rehab.materials_cost", _num(p["materials_cost"]), "REC", f"prior ({cat})"),
        "labor_hours": led.note(f"{E}.rehab.labor_hours", _num(labor), "REC", f"prior ({cat}, {cond})"),
        "admin_hours": led.note(f"{E}.rehab.admin_hours", _num(p["admin_hours"]), "REC", f"prior ({cat})"),
        "required_skills": list(p["required_skills"]),
        "repair_success_prob": led.note(f"{E}.rehab.repair_success_prob", _num(p["repair_success_prob"][cond]),
                                        "REC", f"prior ({cat}, {cond})"),
        "repair_scope_known": False,
    }
    led.note(f"{E}.rehab.required_skills", rehab["required_skills"], "REC", f"prior ({cat})")
    led.gap("repair_scope_unknown", "repair scope is a category prior, not a diagnosis", False)

    # ---- holding, logistics, downside
    per_day = pri.num("flip_general.productive_repair_hours_per_day")
    hold = D(math.ceil(labor / per_day)) + D(resale["expected_dom_days"])
    holding = {
        "storage_cost_per_day": _num(p["storage_cost_per_day"]),
        "expected_hold_days": led.note(f"{E}.holding.expected_hold_days", _num(hold), "INFER",
                                       f"ceil(labor {labor} / {per_day} h/day) + DOM"),
        "sell_fees_rate": _num(p["sell_fees_rate"]),
        "sell_fees_flat": _num(p["sell_fees_flat"]),
    }
    led.note(f"{E}.holding.storage_cost_per_day", holding["storage_cost_per_day"], "REC", f"prior ({cat})")
    r_net = target * (ONE - p["sell_fees_rate"]) - p["sell_fees_flat"]
    downside = {
        "salvage_if_unsold": led.note(f"{E}.downside.salvage_if_unsold",
                                      _num(money(min(r_net, target * p["salvage_unsold_frac"]))), "REC",
                                      f"target x {p['salvage_unsold_frac']} (prior)"),
        "salvage_if_repair_fails": led.note(f"{E}.downside.salvage_if_repair_fails",
                                            _num(money(min(r_net, buy * p["salvage_fail_frac"]))), "REC",
                                            f"expected buy x {p['salvage_fail_frac']} (prior)"),
    }
    rt = money(miles * 2)
    trips = [{"purpose": "inspect_pickup", "round_trip_miles": _num(rt)},
             {"purpose": "buyer_meet", "round_trip_miles": _num(pri.num("distance.buyer_meet_round_trip_miles"))}]
    led.note(f"{E}.logistics.trips", trips, "INFER", "one combined inspect+pickup trip (2 x road miles) + buyer meet prior")
    return {"acquisition": acq, "rehab": rehab, "logistics": {"trips": trips}, "holding": holding,
            "resale": resale, "downside": downside}, research


# --------------------------------------------------------------------------- service

def _estimate_service(item: dict, bundle: dict, pri: ScoringConfig, miles: Decimal, as_of: str,
                      led: _Ledger, scfg: ScoringConfig) -> tuple[dict, list[dict]]:
    cat = item["category"]
    n = item.get("normalized") or {}
    p = pri.group(f"service.{cat}")
    sg = "service_general"
    E = "economics.job"
    source = item["sources"][0]["source"]
    win = pri.group(f"{sg}.win_prob_by_source")
    lq = pri.group(f"{sg}.lead_quality_by_source")
    labor, mat, admin, disposal = p["labor_hours"], p["materials_cost"], p["admin_hours"], p["disposal_cost"]

    # ---- trips first: the quote prices the WHOLE job (travel + quoting + admin), not just labor
    job_days = max(1, math.ceil(labor / 8))
    rt = money(miles * 2)
    scope_known = bool((bundle.get("evidence") or {}).get("scope_verified"))
    trips: list[dict] = []
    est_hours = ZERO
    if not scope_known:
        est_hours = pri.num(f"{sg}.estimate_hours")
        trips.append({"purpose": "estimate_visit", "round_trip_miles": _num(rt)})
        led.gap("scope_unverified", "job size is a category prior; photos or a site visit verify it", False)
    trips += [{"purpose": "work_day", "round_trip_miles": _num(rt)} for _ in range(job_days)]
    if mat > 0:
        trips.append({"purpose": "material_run", "round_trip_miles": _num(pri.num("distance.material_run_round_trip_miles"))})
    led.note("economics.logistics.trips", trips, "INFER",
             f"{'estimate visit + ' if not scope_known else ''}{job_days} work day(s) at 2 x road miles"
             f"{' + material run' if mat > 0 else ''}")

    # per-mile cost and speed come from the scoring config (C13: single source)
    v = fine(scfg.num("vehicle.fuel_price_per_gal") / scfg.num("vehicle.vehicle_mpg") + scfg.num("vehicle.wear_per_mile"))
    speed = scfg.num("vehicle.avg_speed_mph")
    trip_cash = sum((money(D(t["round_trip_miles"]) * v) for t in trips), ZERO)
    travel_h = sum((fine(D(t["round_trip_miles"]) / speed) for t in trips), ZERO)
    hours = labor + admin + est_hours + travel_h

    rate, markup = pri.num(f"{sg}.quote_rate_per_hour"), pri.num(f"{sg}.material_markup_rate")
    step = pri.num(f"{sg}.quote_round_to")
    raw = mat * (ONE + markup) + trip_cash + disposal + hours * rate
    quote = max(pri.num(f"{sg}.min_charge"), D(math.ceil(raw / step)) * step)

    job: dict = {
        "quoted_revenue": led.note(
            f"{E}.quoted_revenue", _num(quote), "UNK",
            f"max(min charge, ceil{step}(materials {mat} + trip cash {trip_cash} + disposal {disposal} "
            f"+ {fine(hours)} h all-in x ${rate}/h)); pricing-policy placeholder"),
        "materials_cost": led.note(f"{E}.materials_cost", _num(mat), "REC", f"prior ({cat})"),
        "material_markup_rate": _num(markup),
        "labor_hours": led.note(f"{E}.labor_hours", _num(labor), "REC", f"prior ({cat})"),
        "admin_hours": led.note(f"{E}.admin_hours", _num(admin), "REC", f"prior ({cat})"),
        "required_skills": led.note(f"{E}.required_skills", list(p["required_skills"]), "REC", f"prior ({cat})"),
        "win_prob": led.note(f"{E}.win_prob", _num(win.get(source, win["default"])), "REC", f"prior by source '{source}'"),
        "completion_prob": led.note(f"{E}.completion_prob", _num(p["completion_prob"]), "REC", f"prior ({cat})"),
        "deposit_rate": led.note(f"{E}.deposit_rate", _num(p["deposit_rate"]), "REC", f"prior ({cat})"),
        "disposal_cost": _num(disposal),
        "payment_terms_days": _num(p["payment_terms_days"]),
        "schedule_lag_days": _num(pri.num(f"{sg}.schedule_lag_days")),
        "job_days": job_days,
        "lead_quality": led.note(f"{E}.lead_quality", _num(lq.get(source, lq["default"])), "REC", f"prior by source '{source}'"),
    }
    if not scope_known:
        job["estimate_hours"] = led.note(f"{E}.estimate_hours", _num(est_hours), "REC",
                                         "scope not verified: an on-site estimate visit is budgeted")
    price = n.get("price") or {}
    if price.get("type") == "customer_budget" and price.get("amount") is not None:
        led.note("normalized.price.customer_budget", price["amount"], "FACT", "customer-stated budget (not used as the quote)")
        if D(price["amount"]) < quote:
            led.gap("budget_below_quote", f"customer budget ${price['amount']} < estimated quote ${quote}", False)
    first_seen = min(s["first_seen_at"] for s in item["sources"])
    age = _hours_between(first_seen, as_of)
    if age >= 0:
        job["lead_age_hours"] = led.note(f"{E}.lead_age_hours", _num(age), "INFER", "hours since the lead was first seen")
    return {"job": job, "logistics": {"trips": trips}}, []


# --------------------------------------------------------------------------- entry point

def _estimate_hash(item: dict, bundle: dict, pri: ScoringConfig, scfg: ScoringConfig, as_of: str) -> str:
    return content_hash({
        "spec": ESTIMATE_SPEC, "estimator_version": ESTIMATOR_VERSION, "priors_version": pri.version,
        "priors_hash": pri.hash, "scoring_config_version": scfg.version, "as_of": as_of,
        "item": {"type": item.get("type"), "category": item.get("category"), "normalized": item.get("normalized"),
                 "sources": [{k: s.get(k) for k in ("source", "first_seen_at", "provenance_id")}
                             for s in item.get("sources", [])]},
        "bundle": bundle,
    })


def estimate_item(item: dict, bundle: dict | None, as_of: str, *, priors: ScoringConfig | None = None,
                  scoring_cfg: ScoringConfig | None = None) -> dict:
    """Return {status, item_patch, gaps, estimate_hash, provenance, receipt_draft}. Pure."""
    bundle = copy.deepcopy(bundle or {})
    _validate_bundle(bundle)
    pri = priors or load_priors()
    scfg = scoring_cfg or load_config()
    led = _Ledger()
    lane, cat = item.get("type"), item.get("category")
    flags = set(((item.get("normalized") or {}).get("flags")) or [])

    try:
        est_hash = _estimate_hash(item, bundle, pri, scfg, as_of)
    except CanonicalError as e:
        raise BundleError([f"item or bundle is not MBOS-CJSON-1 hashable: {e}"]) from e
    prov_id = derived_ulid("prov", as_of, "est|" + est_hash)

    for f in sorted(flags & {"injection_suspected", "needs_review"}):
        led.gap(f, "flagged by discovery: a human must review before any action (estimator ignores listing text)", False)

    econ = None
    research: list[dict] = []
    miles = None
    if lane == "flip" and cat in FLIP_CATEGORIES and cat != "other_asset":
        miles = _road_miles(item, pri, led)
        miles = D(miles) if miles is not None else None
        if miles is not None:
            econ, research = _estimate_flip(item, bundle, pri, miles, as_of, led, scfg)
    elif lane == "service" and cat in SERVICE_CATEGORIES and cat != "other_service":
        miles = _road_miles(item, pri, led)
        miles = D(miles) if miles is not None else None
        if miles is not None:
            econ, research = _estimate_service(item, bundle, pri, miles, as_of, led, scfg)
    else:
        led.gap("category_unestimable", f"{lane}/{cat}: no priors (other_* needs human categorization)", True)

    blocking = any(g["blocking"] for g in led.gaps)
    status = "insufficient" if (blocking or econ is None) else "estimated"
    patch: dict = {}
    if status == "estimated":
        _apply_overrides(econ, bundle, led)
        ev = bundle.get("evidence") or {}
        if lane == "flip" and (econ["rehab"].get("repair_scope_known") or ev.get("fault_identified")):
            led.gaps = [g for g in led.gaps if g["code"] != "repair_scope_unknown"]
        sold = [c for c in bundle.get("comps") or [] if c["kind"] == "sold"]
        meta = {
            "scoring_config_version": scfg.version,
            "assumptions": led.assumptions,
            "estimate": {"estimate_hash": est_hash, "estimator_version": ESTIMATOR_VERSION,
                         "priors_version": pri.version, "priors_hash": pri.hash, "as_of": as_of,
                         "provenance_id": prov_id},
        }
        if lane == "flip" and sold:
            meta["comps"] = [{k: v for k, v in {"url": c.get("url"), "sold_price": c["price"], "sold_date": c["sold_date"],
                                                "dom_days": c.get("dom_days"), "source": c.get("source", "research"),
                                                "condition_note": c.get("condition_note")}.items() if v is not None}
                             for c in sold]
        evidence = dict(bundle.get("evidence") or {})
        if evidence:
            meta["evidence"] = evidence
        econ["estimates_meta"] = meta
        patch = {
            "economics": econ,
            "normalized.location.road_miles_one_way": _num(miles),
            "research": [{"provenance_id": prov_id, **r} for r in research],   # comp facts keep their own
        }

    upstream = sorted({s["provenance_id"] for s in item.get("sources", []) if "provenance_id" in s}
                      | {c["provenance_id"] for k in ("comps", "as_is_comps") for c in bundle.get(k, [])}
                      | {o["provenance_id"] for o in (bundle.get("overrides") or {}).values()}
                      | ({bundle["evidence_provenance_id"]} if bundle.get("evidence") else set())
                      | ({bundle["active_comparable_listings_provenance_id"]}
                         if "active_comparable_listings" in bundle else set()))
    provenance = {
        "provenance_id": prov_id, "created_at": as_of, "actor_type": "system",
        "agent_name": "agent-03-economics", "basis": "INFERENCE",
        "tool_name": TOOL_NAME, "tool_version": ESTIMATOR_VERSION, "config_version": pri.version,
        "inputs_used": [{"ref": "estimate_input", "hash": est_hash},
                        {"ref": f"estimation-priors@{pri.version}", "hash": pri.hash}],
        **({"derived_from": upstream} if upstream else {}),
    }
    receipt_draft = {
        "type": "ITEM_UPDATED", "v1_fallback": "ITEM_STATE_CHANGED with before_state == after_state (ADR-0009 item 2 pending)",
        "item_id": item.get("item_id"), "entity_type": "item", "entity_id": item.get("item_id"),
        "tool_name": TOOL_NAME, "inputs_hash": est_hash, "payload_hash": content_hash(patch) if patch else None,
        "idempotency_key": f"estimate:{item.get('item_id')}:{est_hash}", "provenance_ids": [prov_id],
        "intent": f"RESEARCH estimate: {status}",
    }
    return {"status": status, "item_patch": patch, "gaps": led.gaps, "estimate_hash": est_hash,
            "provenance": provenance, "receipt_draft": receipt_draft}


def apply_estimate(item: dict, result: dict) -> dict:
    """Return a NEW Item with the estimate applied (input is not mutated). No-op when insufficient."""
    out = copy.deepcopy(item)
    patch = result["item_patch"]
    if not patch:
        return out
    out["economics"] = copy.deepcopy(patch["economics"])
    out.setdefault("normalized", {}).setdefault("location", {})["road_miles_one_way"] = \
        patch["normalized.location.road_miles_one_way"]
    if patch["research"]:
        out["research"] = list(out.get("research", [])) + copy.deepcopy(patch["research"])
    pid = result["provenance"]["provenance_id"]
    out["provenance_ids"] = sorted(set(out.get("provenance_ids", [])) | {pid})
    return out

