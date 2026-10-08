"""Deterministic economics + scoring engine (ADR-03-001, round two).

Pipeline (gates first, score second):

    validate → lane ledger + EV tree → skill-fit → confidence → wasted-trip EV
    → ev_decision → scarcity → sub-scores → composite
    → HARD GATES (any fail ⇒ PASS) → composite floor → YES conditions ⇒ YES | MAYBE
    → alert → reasons

``compute`` is a pure function of (engine input, config). ``score`` adds the
derived searches (cheapest decisive evidence, walk-away price / minimum quote),
``inputs_hash``, ``scorecard_id`` and the provenance / receipt drafts. No LLM is
involved anywhere; no clock is read; no I/O happens except loading config.
"""

from __future__ import annotations

import copy
import math
from decimal import Decimal
from typing import Any

from . import __version__ as ENGINE_VERSION
from .canonical import CanonicalError, canonical_json, content_hash, derived_ulid
from .config import ConfigError, ScoringConfig
from .inputs import InputError, build_engine_input, validate_engine_input
from .lanes import LaneEconomics, flip_economics, scarcity_flip, service_economics
from .numeric import D, HUNDRED, ONE, ZERO, clamp, fine, money, score2, to_json_number

INPUTS_HASH_SPEC = "mbos.economics.inputs/v1"
TOOL_NAME = "mbos_economics.engine"

VERDICT_RANK = {"PASS": 0, "MAYBE": 1, "YES": 2}


# --------------------------------------------------------------------------- helpers

def _usd(x: Decimal) -> str:
    return f"${x:,.2f}" if x >= 0 else f"-${-x:,.2f}"


def _evidence_block(econ: dict) -> dict:
    return (econ.get("estimates_meta") or {}).get("evidence") or {}


def _skill_fit(required: list[str], explicit_license_flag: bool, cfg: ScoringConfig) -> dict:
    prof = cfg.group("skills.proficiency")
    gated = set(cfg.get("skills.license_gated_skills"))
    held = set(cfg.get("skills.licenses_held"))
    needs_license = sorted(s for s in set(required) if s in gated and s not in held)
    uniq = sorted(set(required))
    if not uniq:
        fit, coverage, mean = ONE, ONE, ONE
        covered, uncovered = [], []
    else:
        covered = [s for s in uniq if s in prof]
        uncovered = [s for s in uniq if s not in prof]
        coverage = fine(D(len(covered)) / D(len(uniq)))
        mean = fine(sum((prof[s] for s in covered), ZERO) / D(len(covered))) if covered else ZERO
        fit = fine(coverage * mean)
    return {
        "skill_fit": fit, "coverage": coverage, "mean_proficiency": mean,
        "uncovered_skills": uncovered, "license_gated_needed": needs_license,
        "requires_license_he_lacks": bool(needs_license) or explicit_license_flag,
    }


def _evidence_items(lane: str, category: str, econ: dict, skill_fit: Decimal, cfg: ScoringConfig) -> dict[str, bool]:
    ev = _evidence_block(econ)
    high = skill_fit >= cfg.num("confidence.skill_fit_high_threshold")
    if lane == "flip":
        comps = (econ.get("estimates_meta") or {}).get("comps")
        n = max(len(comps) if isinstance(comps, list) else 0, int(D(ev.get("sold_comps_count", 0))))
        resale = econ["resale"]
        lo, hi = resale.get("comp_price_low"), resale.get("comp_price_high")
        titled = category in set(cfg.get("decision_thresholds.titled_categories"))
        return {
            "three_sold_comps": D(n) >= cfg.num("decision_thresholds.min_sold_comps_for_yes_flip"),
            "condition_verified": bool(ev.get("condition_verified")),
            "fault_identified": bool(econ["rehab"].get("repair_scope_known")) or bool(ev.get("fault_identified")),
            "title_verified": bool(ev.get("title_verified")) or not titled,
            "demand_evidence": bool(ev.get("demand_evidence")),
            "seller_screened": bool(ev.get("seller_screened")),
            "skill_fit_high": high,
            "price_distribution": bool(ev.get("price_distribution"))
                or (lo is not None and hi is not None and D(lo) < D(hi)),
            "remote_verification": bool(ev.get("remote_verification")),
            "_sold_comps_count": n,
            "_titled": titled,
        }
    return {
        "scope_verified": bool(ev.get("scope_verified")),
        "customer_screened": bool(ev.get("customer_screened")),
        "price_agreed_in_writing": bool(ev.get("price_agreed_in_writing")),
        "skill_fit_high": high,
        "materials_priced": bool(ev.get("materials_priced")),
        "access_and_schedule_confirmed": bool(ev.get("access_and_schedule_confirmed")),
        "repeat_or_referral": bool(ev.get("repeat_or_referral")),
        "remote_verification": bool(ev.get("remote_verification")),
    }



# --------------------------------------------------------------------------- R13: PASS on priors

# R13 as amended (agent-01 aa88e7a, from 03 P-03-04). Decisive inputs are ARITHMETIC inputs only:
# the asking price is evidence for the expected buy price, not an input to any formula.
_E = "economics."
_FLIP_REVENUE = [_E + "resale.target_sell_price"]
_FLIP_COST = [_E + f for f in ("acquisition.expected_buy_price", "acquisition.buy_fees", "rehab.parts_cost",
                               "rehab.materials_cost", "rehab.labor_hours", "rehab.admin_hours")]
_FLIP_OTHER_ECON = [_E + f for f in ("rehab.repair_success_prob", "resale.sale_prob",
                                     "downside.salvage_if_unsold", "downside.salvage_if_repair_fails")]
_SERVICE_ECON = [_E + f for f in ("job.quoted_revenue", "job.labor_hours", "job.admin_hours", "job.materials_cost",
                                  "job.win_prob", "job.completion_prob")]
_DISTANCE = ["normalized.location.road_miles_one_way", "economics.logistics.trips"]
_NON_ECON = {
    "flip": {
        "max_loss_ok": [_E + f for f in ("acquisition.expected_buy_price", "acquisition.buy_fees", "rehab.parts_cost",
                                         "downside.salvage_if_repair_fails")],
        "cash_ok": [_E + f for f in ("acquisition.expected_buy_price", "acquisition.buy_fees", "rehab.parts_cost",
                                     "rehab.materials_cost")],
        "skills": [_E + "rehab.required_skills", _E + "rehab.requires_license_he_lacks"],
    },
    "service": {
        "max_loss_ok": [_E + f for f in ("job.quoted_revenue", "job.materials_cost", "job.deposit_rate")],
        "cash_ok": [_E + f for f in ("job.quoted_revenue", "job.materials_cost", "job.deposit_rate")],
        "skills": [_E + "job.required_skills", _E + "job.requires_license_he_lacks"],
    },
}
_ECON_GATES = {"ev_positive", "pph_floor_ok", "class_profit_ok", "distance_ratio_ok", "composite_floor"}


def _gate_basis(gate: str, lane: str, backed: set[str]) -> dict:
    if gate in _ECON_GATES:
        extra = _DISTANCE if gate == "distance_ratio_ok" else []
        if lane == "flip":
            decisive = _FLIP_REVENUE + _FLIP_COST + _FLIP_OTHER_ECON + extra
            rev = [f for f in _FLIP_REVENUE if f in backed]
            cost = [f for f in _FLIP_COST if f in backed]
            return {"rule": "flip economic: revenue side AND >= 1 cost-side input evidence-backed",
                    "decisive_inputs": decisive, "evidence_backed_inputs": [f for f in decisive if f in backed],
                    "revenue_backed": bool(rev), "cost_backed": bool(cost), "evidence_backed": bool(rev and cost)}
        decisive = _SERVICE_ECON + extra
    else:
        key = "skills" if gate in ("skill_ok", "license_ok") else gate
        decisive = _NON_ECON[lane][key]
    hit = [f for f in decisive if f in backed]
    return {"rule": ">= 1 decisive input evidence-backed", "decisive_inputs": decisive,
            "evidence_backed_inputs": hit, "evidence_backed": bool(hit)}


def _pass_on_priors(econ: dict, lane: str, failed: list[str], composite_floor: bool) -> dict:
    """R13 (amended): a PASS archives only if at least one failed gate (or the composite floor) is
    evidence-backed under its rule. Evidence-backed = an assumption record with basis FACT, or an aggregate
    the estimator marked ``evidence_backed`` from FACT evidence. Unattested inputs never count."""
    backed = {a.get("field") for a in (econ.get("estimates_meta") or {}).get("assumptions") or []
              if isinstance(a, dict) and (a.get("basis") == "FACT" or a.get("evidence_backed") is True)}
    gates = {g: _gate_basis(g, lane, backed) for g in (failed or (["composite_floor"] if composite_floor else []))}
    return {
        "gates": gates,
        "decisive_inputs": sorted({f for g in gates.values() for f in g["decisive_inputs"]}),
        "evidence_backed_inputs": sorted({f for g in gates.values() for f in g["evidence_backed_inputs"]}),
        "pass_on_priors": not any(g["evidence_backed"] for g in gates.values()),
    }


# --------------------------------------------------------------------------- deal class & ranking (C-19)

def _deal_class(lane: str, cash: Decimal, days: Decimal, cfg: ScoringConfig) -> str:
    """Class from DATA thresholds (config.deal_classes, mirrored from the operator profile)."""
    if lane == "service":
        return "SERVICE_JOB"
    if cash >= cfg.num("deal_classes.capital_intensive_min_cash") or days >= cfg.num(
            "deal_classes.capital_intensive_min_days"):
        return "CAPITAL_INTENSIVE_FLIP"
    if cash <= cfg.num("deal_classes.micro_flip_max_cash") and days <= cfg.num("deal_classes.micro_flip_max_days"):
        return "MICRO_FLIP"
    if days <= cfg.num("deal_classes.quick_turn_max_days"):
        return "QUICK_TURN"
    return "STANDARD_FLIP"


def _ranking(lane, econ, le, confidence, cash, days, cfg, deal_class):
    """Risk-adjusted profit x confidence x capital velocity, every component visible.

    Returns (ranking, extra-derived-fields). Unknown context contributes factor 1 and is reported null."""
    ctx = econ.get("context") or {}
    personal = D(ctx["personal_use_value"]) if ctx.get("personal_use_value") is not None else None
    try:
        cc = cfg.get("operator_context.current_cash")    # the ONE source: Michael's profile, via config
    except ConfigError:                                   # configs before 2026.10.3 (historical replay)
        cc = None
    current_cash = D(cc) if cc is not None else None
    season = D(ctx["seasonality_factor"]) if ctx.get("seasonality_factor") is not None else None
    risk_penalty = money(cfg.num("ranking.risk_aversion") * le.p_loss * le.max_loss)
    ra_profit = money(le.ev_net_profit + (personal or ZERO) - risk_penalty)
    base = max(cash, cfg.num("ranking.velocity_cash_floor"))
    velocity = fine(min(le.ev_net_profit / base / max(days, cfg.num("ranking.velocity_min_days")),
                        cfg.num("ranking.velocity_cap_per_day")))
    cash_share = fine(cash / current_cash) if current_cash is not None else None
    pressure = fine(clamp(ONE - cfg.num("ranking.cash_pressure_weight") * min(ONE, cash_share), ZERO, ONE)) \
        if cash_share is not None else ONE
    season_f = season if season is not None else ONE
    if ra_profit > 0 and velocity > 0:
        score = score2(ra_profit * confidence * velocity * season_f * pressure)
        formula = "risk_adjusted_profit x confidence x capital_velocity x seasonality_factor x cash_pressure_factor"
    else:
        score = score2(ra_profit * confidence)
        formula = "risk_adjusted_profit x confidence (non-positive profit or velocity is not rescued by speed)"
    ranking = {
        "rank_score": score, "formula": formula, "risk_adjusted_profit": ra_profit,
        "ev_net_profit": le.ev_net_profit, "personal_use_value": personal, "risk_penalty": risk_penalty,
        "confidence": confidence, "capital_velocity": velocity, "seasonality_factor": season,
        "seasonality_factor_applied": season_f, "cash_share_of_current_cash": cash_share,
        "cash_pressure_factor": pressure,
        "timing_flag": "WRONG_BUY_TODAY" if (
            deal_class == "CAPITAL_INTENSIVE_FLIP" and season is not None
            and season <= cfg.num("ranking.wrong_buy_season_factor_max")) else None,
    }
    if lane == "flip":
        sale_p = D(econ["resale"]["sale_prob"])
        dom = econ["resale"].get("expected_dom_days")
        cat = fine(ONE - D(econ["rehab"]["repair_success_prob"]))
        salvage = money(D(econ["downside"]["salvage_if_repair_fails"]))
        liquidity = {"sale_prob": sale_p, "expected_dom_days": D(dom) if dom is not None else None}
    else:
        cat, salvage = fine(le.p_loss), None
        liquidity = {"win_prob": D(econ["job"]["win_prob"]), "expected_dom_days": None}
    capital = {
        "capital_velocity": velocity, "catastrophic_downside_probability": cat, "parts_out_floor": salvage,
        "liquidity": liquidity, "personal_use_value": personal,
        "current_cash_context": {"value": current_cash, "known": current_cash is not None},
        "seasonality_factor": season,
    }
    return ranking, capital


# --------------------------------------------------------------------------- compute

def compute(inp: dict, cfg: ScoringConfig) -> dict:
    """Pure scoring of one engine input under one config. Returns Decimal-valued core."""
    validate_engine_input(inp)
    lane, category, econ = inp["type"], inp["category"], inp["economics"]
    meta_version = (econ.get("estimates_meta") or {}).get("scoring_config_version")

    le: LaneEconomics = flip_economics(econ, cfg) if lane == "flip" else service_economics(econ, cfg)
    if inp.get("road_miles_one_way") is not None:
        miles = D(inp["road_miles_one_way"])
    else:
        miles = (le.trips[0]["round_trip_miles"] / 2) if le.trips else ZERO

    w_min = cfg.num("time_value.w_min_per_hour")
    w_target = cfg.num(f"time_value.w_target_{lane}_per_hour")
    block = econ["rehab"] if lane == "flip" else econ["job"]

    # skill-fit
    sk = _skill_fit(block.get("required_skills", []), bool(block.get("requires_license_he_lacks")), cfg)

    # confidence (evidence checklist; long-distance penalty)
    items = _evidence_items(lane, category, econ, sk["skill_fit"], cfg)
    weights = cfg.group(f"confidence.{lane}_evidence_weights")
    raw_conf = sum((weights[k] for k in weights if items.get(k)), ZERO)
    beyond_radius = miles > cfg.num("distance_rules.normal_radius_miles_one_way")
    penalty = cfg.num("confidence.beyond_normal_radius_penalty") if beyond_radius else ZERO
    confidence = fine(clamp(raw_conf - penalty))
    haircut = fine(cfg.num("confidence.haircut_base") + cfg.num("confidence.haircut_slope") * confidence)

    # wasted-trip EV on the first (committing) trip
    ev_block = _evidence_block(econ)
    evidence_quality = D(ev_block["evidence_quality"]) if ev_block.get("evidence_quality") is not None else confidence
    p_waste = fine(clamp(
        cfg.num("distance_rules.p_waste_base") + cfg.num("distance_rules.p_waste_per_mile") * miles
        - cfg.num("distance_rules.p_waste_evidence_slope") * evidence_quality,
        ZERO, cfg.num("distance_rules.p_waste_max")))
    first = le.trips[0] if le.trips else None
    wasted = money(p_waste * (first["cash"] + first["hours"] * w_min)) if first else ZERO

    pre = le.ev_net_profit - wasted
    ev_decision = money(pre * haircut) if pre > 0 else pre

    # distance-ratio gate (§13-1), long distance only
    travel_burden = money(le.trips_cash + le.travel_hours * w_min + wasted)
    travel_limit = money(cfg.num("distance_rules.travel_cost_fraction_of_ev_max") * max(le.ev_net_profit, ZERO))
    ratio_applies = miles > cfg.num("distance_rules.distance_ratio_gate_beyond_miles")

    # scarcity / lead quality
    if lane == "flip":
        sc = scarcity_flip(econ, cfg)
        scarcity = sc["scarcity"]
    else:
        lq = econ["job"].get("lead_quality")
        scarcity = fine(D(lq)) if lq is not None else ZERO
        sc = {"lead_quality": scarcity}

    # deal class + capital-velocity facts (C-19, ADR-0012): no universal profit floor
    cash_at_risk, days_to_cash = le.cash_tied_up, le.ttc_days
    deal_class = _deal_class(lane, cash_at_risk, days_to_cash, cfg)
    gk = "class_gates." + ("service" if deal_class == "SERVICE_JOB" else deal_class.lower())
    min_net, min_ev, min_mult = (cfg.num(f"{gk}.min_net_profit"), cfg.num(f"{gk}.min_ev_profit"),
                                 cfg.num(f"{gk}.min_cash_multiple"))
    cash_base = max(cash_at_risk, ONE)
    # a cash multiple is meaningless for a service (little or no capital at risk): null, not a number
    cash_multiple = fine((cash_at_risk + le.ev_net_profit) / cash_base) if lane == "flip" else None
    ev_cash_multiple = fine((cash_at_risk + ev_decision) / cash_base) if lane == "flip" else None

    # risk score (§9.1)
    rw = cfg.group("risk_score_weights")
    risk_raw = clamp(rw["max_loss"] * (le.max_loss / cfg.num("capital_and_risk.max_loss_cap"))
                     + rw["p_loss"] * le.p_loss + rw["cov"] * min(le.cov, ONE))
    caps = "normalization_caps"

    def pct(x: Decimal) -> Decimal:
        return score2(clamp(x, ZERO, HUNDRED))

    sub = {
        "ev_score": pct(ev_decision / cfg.num(f"{caps}.ev_cap_{lane}") * HUNDRED),
        "pph_score": pct(le.ev_pph / cfg.num(f"{caps}.pph_cap") * HUNDRED),
        "roi_score": pct(le.ev_roi / cfg.num(f"{caps}.roi_cap") * HUNDRED),
        "ttc_score": pct(HUNDRED - le.ttc_days / cfg.num(f"{caps}.ttc_cap_days") * HUNDRED),
        "risk_score": pct(HUNDRED - HUNDRED * risk_raw),
        "conf_score": pct(confidence * HUNDRED),
        "skill_score": pct(sk["skill_fit"] * HUNDRED),
        "scarcity_score": pct(scarcity * HUNDRED),
    }
    cw = cfg.group(f"composite_weights.{lane}")
    key = {"ev": "ev_score", "pph": "pph_score", "roi": "roi_score", "ttc": "ttc_score",
           "risk": "risk_score", "conf": "conf_score", "skill": "skill_score", "scarcity": "scarcity_score"}
    composite = score2(sum((cw[k] * sub[v] for k, v in key.items()), ZERO))

    # ---------------- STEP 1: hard gates (any fail ⇒ PASS)
    gates = {
        "ev_positive": ev_decision > 0,
        "max_loss_ok": le.max_loss <= cfg.num("capital_and_risk.max_loss_cap"),
        "cash_ok": le.cash_tied_up <= cfg.num("capital_and_risk.risk_capital_per_deal_cap"),
        "skill_ok": sk["skill_fit"] >= cfg.num("decision_thresholds.skill_fit_hard_floor"),
        "license_ok": not sk["requires_license_he_lacks"],
        "pph_floor_ok": le.pph >= w_min,
        "class_profit_ok": le.net_profit >= min_net,
        "distance_ratio_ok": (not ratio_applies) or (le.ev_net_profit > 0 and travel_burden <= travel_limit),
    }
    gate_text = {
        "ev_positive": f"EV after haircut {_usd(ev_decision)} is not positive",
        "max_loss_ok": f"max loss {_usd(le.max_loss)} exceeds cap {_usd(cfg.num('capital_and_risk.max_loss_cap'))}",
        "cash_ok": f"cash tied up {_usd(le.cash_tied_up)} exceeds per-deal cap {_usd(cfg.num('capital_and_risk.risk_capital_per_deal_cap'))}",
        "skill_ok": f"skill fit {sk['skill_fit']} below floor {cfg.num('decision_thresholds.skill_fit_hard_floor')}"
                    + (f" (uncovered: {', '.join(sk['uncovered_skills'])})" if sk["uncovered_skills"] else ""),
        "license_ok": "requires a license Michael lacks"
                      + (f" ({', '.join(sk['license_gated_needed'])})" if sk["license_gated_needed"] else ""),
        "pph_floor_ok": f"deterministic profit/hour {_usd(le.pph)} below floor {_usd(w_min)}",
        "class_profit_ok": f"deterministic net profit {_usd(le.net_profit)} below the {deal_class} requirement {_usd(min_net)}",
        "distance_ratio_ok": f"long-distance travel burden {_usd(travel_burden)} exceeds "
                             f"{cfg.num('distance_rules.travel_cost_fraction_of_ev_max')} x EV = {_usd(travel_limit)}",
    }
    failed = [g for g, ok in gates.items() if not ok]

    # ---------------- STEP 2: YES conditions (only meaningful for gate survivors)
    yes = {
        "composite_ok": composite >= cfg.num("decision_thresholds.composite_yes"),
        "confidence_ok": confidence >= cfg.num("decision_thresholds.confidence_min_for_yes"),
        "ev_pph_target_ok": le.ev_pph >= w_target,
        "class_ev_ok": ev_decision >= min_ev and (ev_cash_multiple is None or ev_cash_multiple >= min_mult),
        "remote_verification_ok": (miles <= cfg.num("distance_rules.remote_verification_required_beyond_miles"))
                                  or items["remote_verification"],
    }
    if lane == "flip":
        yes["sold_comps_ok"] = items["three_sold_comps"]
        yes["fault_identified_ok"] = items["fault_identified"] or not cfg.get(
            "decision_thresholds.require_repair_scope_known_for_yes_flip")
        yes["title_ok"] = items["title_verified"]
    yes_text = {
        "composite_ok": f"composite {composite} < {cfg.num('decision_thresholds.composite_yes')}",
        "confidence_ok": f"confidence {confidence} < {cfg.num('decision_thresholds.confidence_min_for_yes')} (gather evidence)",
        "ev_pph_target_ok": f"EV profit/hour {_usd(le.ev_pph)} < {lane} target {_usd(w_target)}",
        "class_ev_ok": f"{deal_class}: EV after haircut {_usd(ev_decision)} / cash multiple {ev_cash_multiple} "
                       f"below class requirement ({_usd(min_ev)}, {min_mult}x)",
        "remote_verification_ok": f"{miles} mi one-way needs remote verification before a committing trip",
        "sold_comps_ok": f"{items.get('_sold_comps_count', 0)} sold comps < {cfg.num('decision_thresholds.min_sold_comps_for_yes_flip')} required",
        "fault_identified_ok": "repair fault not identified (guessed scope caps at MAYBE)",
        "title_ok": "title/ownership not verified for a titled asset",
    }

    reasons: list[str] = []
    if failed:
        decision = "PASS"
        reasons += [f"GATE FAIL {g}: {gate_text[g]}" for g in failed]
    elif composite < cfg.num("decision_thresholds.composite_pass_below"):
        decision = "PASS"
        reasons.append(f"composite {composite} < pass floor {cfg.num('decision_thresholds.composite_pass_below')}")
    elif all(yes.values()):
        decision = "YES"
        reasons.append(f"all hard gates pass; composite {composite}; confidence {confidence}; "
                       f"EV profit/hour {_usd(le.ev_pph)} >= {_usd(w_target)}; EV {_usd(ev_decision)}")
    else:
        decision = "MAYBE"
        reasons += [f"YES blocked: {yes_text[k]}" for k, ok in yes.items() if not ok]
    pass_basis = None
    if decision == "PASS":
        pass_basis = _pass_on_priors(econ, lane, failed, composite_floor=not failed)
        if pass_basis["pass_on_priors"]:
            why = []
            for g, v in pass_basis["gates"].items():
                if "revenue_backed" in v:
                    why.append(f"{g}: revenue {'backed' if v['revenue_backed'] else 'NOT backed'}, "
                               f"cost {'backed' if v['cost_backed'] else 'NOT backed'}")
                else:
                    why.append(f"{g}: no decisive input backed")
            reasons.append("R13: PASS is not evidence-backed (" + "; ".join(why) + "): route to RESEARCHING, do not archive")
        else:
            ok = [g for g, v in pass_basis["gates"].items() if v["evidence_backed"]]
            reasons.append("R13: PASS is evidence-backed (" + ", ".join(ok) + ") via "
                           + ", ".join(pass_basis["evidence_backed_inputs"]))
    reasons.append(f"deterministic: net {_usd(le.net_profit)}, {_usd(le.pph)}/h over {le.total_hours} h, "
                   f"cash tied up {_usd(le.cash_tied_up)}, ROI {le.roi}")
    reasons.append(f"expected: net {_usd(le.ev_net_profit)}, {_usd(le.ev_pph)}/h, max loss {_usd(le.max_loss)}, "
                   f"P(loss) {le.p_loss}, time-to-cash {le.ttc_days} d")
    if sk["uncovered_skills"] and gates["skill_ok"]:
        reasons.append(f"skills not in profile: {', '.join(sk['uncovered_skills'])}")
    if meta_version is not None and meta_version != cfg.version:
        reasons.append(f"note: estimates prepared under config {meta_version}, scored under {cfg.version}")

    # ---------------- alert (strong AND perishable)
    at = "alert_thresholds"
    if lane == "flip":
        acq = econ["acquisition"]
        age, ends = acq.get("listing_age_hours"), acq.get("auction_ends_in_hours")
        perishable = ((age is not None and D(age) < cfg.num(f"{at}.listing_age_hours_max"))
                      or (ends is not None and D(ends) < cfg.num(f"{at}.auction_ends_in_hours_max"))
                      or sc["supply_tightness"] >= cfg.num(f"{at}.supply_tightness_min"))
        alert_checks = {
            "is_yes": decision == "YES",
            "scarcity_ok": scarcity >= cfg.num(f"{at}.scarcity_min"),
            "perishable": perishable,
            "ev_multiple_ok": ev_cash_multiple >= cfg.num(f"{at}.ev_cash_multiple_min"),
            "deal_discount_ok": sc["deal_discount"] >= cfg.num(f"{at}.deal_discount_min"),
        }
    else:
        age = econ["job"].get("lead_age_hours")
        alert_checks = {
            "is_yes": decision == "YES",
            "lead_quality_ok": scarcity >= cfg.num(f"{at}.service_lead_quality_min"),
            "perishable": age is not None and D(age) < cfg.num(f"{at}.service_lead_age_hours_max"),
            "ev_multiple_ok": le.ev_pph >= cfg.num(f"{at}.service_ev_pph_multiple_of_target") * w_target,
        }
    alert = all(alert_checks.values())
    if alert:
        reasons.append("ALERT: strong and perishable")

    ranking, capital = _ranking(lane, econ, le, confidence, cash_at_risk, days_to_cash, cfg, deal_class)
    if ranking["timing_flag"]:
        reasons.append(f"WRONG BUY TODAY: capital-intensive flip out of season (seasonality factor "
                       f"{ranking['seasonality_factor']}); {_usd(cash_at_risk)} would be locked for {days_to_cash} d. "
                       f"Wait for the season or pass")
    reasons.append(f"class {deal_class} (provisional thresholds): cash at risk {_usd(cash_at_risk)}, "
                   f"{days_to_cash} d to cash, cash multiple {cash_multiple}x; "
                   f"rank score {ranking['rank_score']} = {ranking['formula']}")

    derived = {
        "deal_class": deal_class,
        "deal_class_basis": "RECOMMENDATION",
        "class_requirements": {"min_net_profit": min_net, "min_ev_profit": min_ev, "min_cash_multiple": min_mult},
        "cash_at_risk": cash_at_risk,
        "days_to_cash": days_to_cash,
        "cash_multiple": cash_multiple,
        "ev_cash_multiple": ev_cash_multiple,
        **capital,
        "vehicle_cost_per_mile": le.v_per_mile,
        "road_miles_one_way": miles,
        "trips_cash": le.trips_cash,
        "travel_hours": le.travel_hours,
        "labor_hours": le.labor_hours,
        "admin_hours": le.admin_hours,
        "total_hours": le.total_hours,
        "cost_out": le.cost_out,
        "r_net": le.r_net,
        "net_profit_deterministic": le.net_profit,
        "profit_per_hour_deterministic": le.pph,
        "cash_tied_up": le.cash_tied_up,
        "roi_deterministic": le.roi,
        "expected_revenue": le.expected_revenue,
        "ev_net_profit": le.ev_net_profit,
        "ev_hours": le.ev_hours,
        "ev_profit_per_hour": le.ev_pph,
        "ev_roi": le.ev_roi,
        "p_waste": p_waste,
        "evidence_quality": evidence_quality,
        "wasted_trip_ev": wasted,
        "confidence_raw": fine(raw_conf),
        "confidence_distance_penalty": penalty,
        "confidence": confidence,
        "confidence_haircut": haircut,
        "ev_decision": ev_decision,
        "max_loss": le.max_loss,
        "p_loss": le.p_loss,
        "coefficient_of_variation": le.cov,
        "risk_raw": fine(risk_raw),
        "time_to_cash_days": le.ttc_days,
        "travel_burden": travel_burden,
        "travel_burden_limit": travel_limit,
        "distance_ratio_gate_applies": ratio_applies,
        "skill_fit": sk["skill_fit"],
        "skill_coverage": sk["coverage"],
        "skill_mean_proficiency": sk["mean_proficiency"],
        "scarcity": scarcity,
        **{k: v for k, v in sc.items() if k != "scarcity"},
        **le.extra,
        "branches": [{"name": b.name, "prob": b.prob, "value": b.value, "revenue": b.revenue} for b in le.branches],
        "trips": le.trips,
    }
    return {
        "lane": lane,
        "derived": derived,
        "sub_scores": sub,
        "weights_used": dict(cw),
        "composite": composite,
        "gates": gates,
        "yes_conditions": yes,
        "decision": decision,
        "pass_on_priors": bool(pass_basis and pass_basis["pass_on_priors"]),
        "pass_basis": pass_basis,
        "ranking": ranking,
        "alert": alert,
        "alert_checks": alert_checks,
        "evidence": {k: v for k, v in items.items() if not k.startswith("_")},
        "uncovered_skills": sk["uncovered_skills"],
        "reasons": reasons,
    }


# --------------------------------------------------------------------------- searches

def _with(inp: dict, mutate) -> dict:
    out = copy.deepcopy(inp)
    mutate(out["economics"])
    return out


def _set_evidence(item: str, lane: str, cfg: ScoringConfig):
    def m(econ: dict) -> None:
        meta = econ.setdefault("estimates_meta", {})
        ev = meta.setdefault("evidence", {})
        if item == "fault_identified":
            econ["rehab"]["repair_scope_known"] = True
        elif item == "three_sold_comps":
            ev["sold_comps_count"] = int(cfg.num("decision_thresholds.min_sold_comps_for_yes_flip"))
        elif item == "price_distribution":
            ev["price_distribution"] = True
        else:
            ev[item] = True
    return m


def cheapest_decisive_evidence(inp: dict, core: dict, cfg: ScoringConfig) -> dict | None:
    """EVPI-lite: which missing evidence (cheapest first) lifts the verdict one step.

    Only evidence flags change; estimates (prices, probabilities) do not. Tries each
    missing item alone in cost order, then accumulates items in order.
    """
    if core["decision"] == "YES":
        return None
    lane = core["lane"]
    target = "MAYBE" if core["decision"] == "PASS" else "YES"
    order = list(cfg.get(f"evidence_search.{lane}_order"))
    missing = [k for k in order if not core["evidence"].get(k, False)]
    for k in missing:
        trial = compute(_with(inp, _set_evidence(k, lane, cfg)), cfg)
        if VERDICT_RANK[trial["decision"]] >= VERDICT_RANK[target]:
            return {"target": target, "items": [k], "reaches": trial["decision"]}
    acc = inp
    for i, k in enumerate(missing):
        acc = _with(acc, _set_evidence(k, lane, cfg))
        trial = compute(acc, cfg)
        if VERDICT_RANK[trial["decision"]] >= VERDICT_RANK[target]:
            return {"target": target, "items": missing[: i + 1], "reaches": trial["decision"]}
    return {"target": target, "items": [], "reaches": None}


def _bisect_int(lo: int, hi: int, ok, want_max: bool) -> int | None:
    """Largest (want_max) or smallest integer in [lo, hi] satisfying a monotone predicate."""
    if want_max:
        if not ok(lo):
            return None
        while lo < hi:
            mid = (lo + hi + 1) // 2
            lo, hi = (mid, hi) if ok(mid) else (lo, mid - 1)
        return lo
    if not ok(hi):
        return None
    while lo < hi:
        mid = (lo + hi) // 2
        lo, hi = (lo, mid) if ok(mid) else (mid + 1, hi)
    return lo


def walk_away_price(inp: dict, cfg: ScoringConfig) -> int | None:
    """FLIP: highest whole-dollar expected_buy_price that still scores YES (offer ceiling)."""
    cap = int(math.floor(D(inp["economics"]["resale"]["target_sell_price"])))

    def ok(a: int) -> bool:
        trial = _with(inp, lambda e: e["acquisition"].__setitem__("expected_buy_price", a))
        return compute(trial, cfg)["decision"] == "YES"

    return _bisect_int(0, cap, ok, want_max=True)


def min_quote_for_yes(inp: dict, cfg: ScoringConfig) -> int | None:
    """SERVICE: lowest whole-dollar quoted_revenue that scores YES (quote floor)."""
    cur = D(inp["economics"]["job"]["quoted_revenue"])
    hi = int(max(D(1000), cur * 5).to_integral_value())

    def ok(q: int) -> bool:
        trial = _with(inp, lambda e: e["job"].__setitem__("quoted_revenue", q))
        return compute(trial, cfg)["decision"] == "YES"

    return _bisect_int(0, hi, ok, want_max=False)


# --------------------------------------------------------------------------- hashing / ids / output

def inputs_hash(inp: dict, cfg_version: str) -> str:
    return content_hash({"spec": INPUTS_HASH_SPEC, "scoring_config_version": cfg_version, "input": inp})


def _jsonify(x: Any) -> Any:
    if isinstance(x, Decimal):
        return to_json_number(x)
    if isinstance(x, dict):
        return {k: _jsonify(v) for k, v in x.items()}
    if isinstance(x, list):
        return [_jsonify(v) for v in x]
    return x


def score(inp: dict, cfg: ScoringConfig, scored_at: str) -> dict:
    """Score one engine input. Deterministic in (inp, cfg, scored_at)."""
    core = compute(inp, cfg)
    try:
        ih = inputs_hash(inp, cfg.version)
    except CanonicalError as e:   # ADR-0010 I-JSON profile: e.g. a U+0000 or a non-BMP key in a skill name
        raise InputError([f"input is not MBOS-CJSON-1 hashable: {e}"]) from e
    seed = f"{ih}|{ENGINE_VERSION}|{scored_at}"
    scorecard_id = derived_ulid("scr", scored_at, "scr|" + seed)

    evidence = cheapest_decisive_evidence(inp, core, cfg)
    if core["lane"] == "flip":
        price_hint = {"walk_away_price": walk_away_price(inp, cfg)}
    else:
        price_hint = {"min_quote_for_yes": min_quote_for_yes(inp, cfg)}

    cde = None
    reasons = list(core["reasons"])
    if evidence and evidence["items"]:
        cde = f"{' + '.join(evidence['items'])} -> {evidence['reaches']}"
        reasons.append(f"cheapest decisive evidence: {cde}")
    elif evidence:
        reasons.append("evidence is not the blocker: no missing evidence item changes the verdict")
    if core["lane"] == "flip" and price_hint["walk_away_price"] is not None:
        reasons.append(f"walk-away price (max buy for YES): ${price_hint['walk_away_price']:,}")
    if core["lane"] == "service" and price_hint["min_quote_for_yes"] is not None:
        reasons.append(f"minimum quote for YES: ${price_hint['min_quote_for_yes']:,}")

    scorecard = _jsonify({
        "scoring_config_version": cfg.version,
        "computed_at": scored_at,
        "engine_version": ENGINE_VERSION,
        "config_hash": cfg.hash,
        "lane": core["lane"],
        "derived": core["derived"],
        "sub_scores": core["sub_scores"],
        "weights_used": core["weights_used"],
        "composite": core["composite"],
        "decision": core["decision"],
        "pass_on_priors": core["pass_on_priors"],
        **({"pass_basis": core["pass_basis"]} if core["pass_basis"] else {}),
        "ranking": core["ranking"],
        "alert": core["alert"],
        "alert_checks": core["alert_checks"],
        "gates": core["gates"],
        "yes_conditions": core["yes_conditions"],
        "evidence": core["evidence"],
        "evidence_search": evidence,
        **price_hint,
        "reasons": reasons,
        **({"cheapest_decisive_evidence": cde} if cde else {}),
    })
    return {
        "scorecard_id": scorecard_id,
        "inputs_hash": ih,
        "scorecard": scorecard,
        "scorecard_hash": content_hash(scorecard),
    }


def score_item(item: dict, cfg: ScoringConfig, scored_at: str) -> dict:
    """Score an Item v1. Returns the Item's ``scores`` and ``recommendation`` blocks plus
    the provenance record and receipt drafts the State lane (04) commits in one transaction.
    The Item itself is not mutated."""
    inp = build_engine_input(item)
    bundle = score(inp, cfg, scored_at)
    sc = bundle["scorecard"]
    seed = f"{bundle['inputs_hash']}|{ENGINE_VERSION}|{scored_at}"
    prov_id = derived_ulid("prov", scored_at, "prov|" + seed)
    rec_id = derived_ulid("rec", scored_at, "rec|" + seed)

    upstream = sorted({s["provenance_id"] for s in item.get("sources", []) if "provenance_id" in s}
                      | set(inp["research_ids"]))
    provenance = {
        "provenance_id": prov_id,
        "created_at": scored_at,
        "actor_type": "system",
        "agent_name": "agent-03-economics",
        "basis": "INFERENCE",
        "tool_name": TOOL_NAME,
        "tool_version": ENGINE_VERSION,
        "config_version": cfg.version,
        "inputs_used": [
            {"ref": "engine_input", "hash": bundle["inputs_hash"]},
            {"ref": f"scoring-config@{cfg.version}", "hash": cfg.hash},
        ],
        **({"derived_from": upstream} if upstream else {}),
        "confidence": sc["derived"]["confidence"],
    }
    recommendation = {
        "recommendation_id": rec_id,
        "verdict": sc["decision"],
        "rationale": sc["reasons"],
        "confidence": sc["derived"]["confidence"],
        "alert": sc["alert"],
        "provenance_id": prov_id,
        **({"cheapest_decisive_evidence": sc["cheapest_decisive_evidence"]}
           if "cheapest_decisive_evidence" in sc else {}),
    }
    scores = {"scorecard_id": bundle["scorecard_id"], "inputs_hash": bundle["inputs_hash"], "scorecard": sc}
    receipt_drafts = [
        {"type": "SCORE_RECORDED", "item_id": item.get("item_id"), "entity_type": "scorecard",
         "entity_id": bundle["scorecard_id"], "tool_name": TOOL_NAME, "inputs_hash": bundle["inputs_hash"],
         "payload_hash": bundle["scorecard_hash"], "idempotency_key": f"score:{bundle['scorecard_id']}",
         "provenance_ids": [prov_id]},
        {"type": "RECOMMENDATION_RECORDED", "item_id": item.get("item_id"), "entity_type": "recommendation",
         "entity_id": rec_id, "tool_name": TOOL_NAME, "inputs_hash": bundle["inputs_hash"],
         "payload_hash": content_hash(recommendation), "idempotency_key": f"recommend:{rec_id}",
         "provenance_ids": [prov_id]},
    ]
    return {"scores": scores, "recommendation": recommendation, "provenance": provenance,
            "receipt_drafts": receipt_drafts}


def canonical_scorecard(sc: dict) -> str:
    return canonical_json(sc)
