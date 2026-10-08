"""C-15: Deal Sniffer enrichment blocks (ADR-0011) for the opportunity card.

``build_enrichment(item, as_of, ...)`` is pure and deterministic. It reads a SCORED Item and returns the four
lane-C blocks that Agent 01's ``spine.record_enrichment(conn, item_id, block, data, provenance_id,
agent="agent-03-economics")`` attaches:

* ``economics``   opening_offer, max_acquisition, resale_conservative/likely/optimistic, transport_cost, days_to_cash
* ``logistics``   transport_mode, trip_miles_round_trip, trip_hours, fuel_cost, difficulty
* ``seasonality`` demand_now, hold_likely, peak_months, note   (from the SOURCED table; absent category => omitted)
* ``why``         deterministic plain-English reasons built from gates and facts

Honesty rules (ADR-0011): every datum is ``{"value", "basis", "provenance_id"}`` (+ unit/low/high/note);
anything the evidence cannot support is OMITTED, so the card shows UNKNOWN and lists it. No comps => no resale
range. Unclassifiable transport => no mode. Difficulty is an economic input already inside the score, never a
rejection. The returned ``provenance`` record must be persisted BEFORE the blocks are attached.
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import __version__ as ENRICH_VERSION
from .canonical import content_hash, derived_ulid, parse_ts
import copy
import re

from .comps import aggregate_sold_comps
from .config import CONFIG_DIR, ScoringConfig
from .engine import _bisect_int, compute, effective_caps
from .inputs import build_engine_input
from .logistics import acquisition_round_trip_miles, classify_transport, difficulty, trailer_status
from .numeric import D, fine, money
from .vocab import query_key

TOOL_NAME = "mbos_economics.enrich"
SEASONALITY_FORMAT = 1
_MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"]
_EVIDENCE_WORDS = {
    "seller_screened": "a call with the seller", "condition_verified": "photos or an inspection of the condition",
    "fault_identified": "a diagnosed fault", "title_verified": "a verified title", "demand_evidence": "evidence of demand",
    "three_sold_comps": "three sold comparables", "price_distribution": "a spread of comparable prices",
    "remote_verification": "remote verification of the item", "scope_verified": "photos or a visit to size the job",
    "customer_screened": "a call with the customer", "materials_priced": "priced materials",
    "access_and_schedule_confirmed": "confirmed access and schedule", "price_agreed_in_writing": "the price in writing",
}


def load_seasonality(path: Path | None = None) -> dict:
    p = Path(path) if path else CONFIG_DIR / "seasonality.json"
    doc = json.loads(p.read_text(encoding="utf-8"))
    if doc.get("seasonality_format") != SEASONALITY_FORMAT:
        raise ValueError(f"seasonality table must be seasonality_format {SEASONALITY_FORMAT}")
    doc["_hash"] = content_hash({k: v for k, v in doc.items() if k != "_hash"})
    return doc


# --------------------------------------------------------------------------- datum helpers

def _n(x) -> int | float:
    d = D(x)
    return int(d) if d == d.to_integral_value() else float(str(d.quantize(Decimal("0.01"))))


def _datum(value: Any, basis: str, pid: str, *, unit: str | None = None, low=None, high=None, note: str | None = None) -> dict:
    d: dict[str, Any] = {"value": _n(value) if isinstance(value, (int, float, Decimal)) and not isinstance(value, bool) else value,
                         "basis": basis, "provenance_id": pid}
    for k, v in (("unit", unit), ("note", note)):
        if v is not None:
            d[k] = v
    for k, v in (("low", low), ("high", high)):
        if v is not None:
            d[k] = _n(v)
    return d


def _usd(x) -> str:
    return f"${D(x):,.0f}"


def _month_name(m: int) -> str:
    return _MONTHS[m - 1]


# --------------------------------------------------------------------------- economics

def _sold_comps(item: dict) -> list[dict]:
    meta = (item.get("economics") or {}).get("estimates_meta") or {}
    comps = [c for c in meta.get("comps") or [] if c.get("sold_price") is not None]
    fact = [r for r in item.get("research") or [] if r.get("basis") == "FACT" and r.get("field") == "resale.target_sell_price"]
    return comps if fact else []                # FACT-tagged comp evidence is required


def _economic_ceiling(item: dict, cfg: ScoringConfig) -> int | None:
    """Highest whole-dollar buy price at which every HARD gate passes and the expected $/h and profit clear the
    targets, ignoring the evidence conditions still outstanding (confidence, comps count, fault, title). This is
    the price ceiling that matters while evidence is being gathered; the engine's walk-away price needs a full YES."""
    inp = build_engine_input(item)
    cap = int(D(inp["economics"]["resale"]["target_sell_price"]))

    def ok(price: int) -> bool:
        trial = copy.deepcopy(inp)
        trial["economics"]["acquisition"]["expected_buy_price"] = price
        r = compute(trial, cfg)
        return all(r["gates"].values()) and r["yes_conditions"]["ev_pph_target_ok"] and r["yes_conditions"]["class_ev_ok"]

    return _bisect_int(0, cap, ok, want_max=True)


def _join(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _economics_block(item: dict, as_of: str, pid: str, cfg: ScoringConfig, pri: ScoringConfig) -> tuple[dict, list[str]]:
    sc = (item.get("scores") or {}).get("scorecard")
    if not sc or sc.get("lane") != "flip":
        return {}, ["economics: not a scored flip"]
    d, out, omitted = sc["derived"], {}, []
    walk = sc.get("walk_away_price")
    target = cfg.num("time_value.w_target_flip_per_hour")
    ceiling_note = None
    if walk is None and item.get("economics", {}).get("resale", {}).get("target_sell_price") is not None:
        walk = _economic_ceiling(item, cfg)
        if walk is not None:
            ceiling_note = (f"highest buy price that clears your ${target:g}/h flip target and every hard limit, "
                            "provided the evidence still outstanding checks out (not a YES yet)")
    if walk is not None:
        out["max_acquisition"] = _datum(walk, "INFERENCE", pid, unit="USD",
                                        note=ceiling_note or f"highest buy price that still meets your ${target:g}/h flip target (scored YES)")
        price = (item.get("normalized") or {}).get("price") or {}
        if price.get("type") == "fixed" and price.get("amount") is not None:
            ask = D(price["amount"])
            step = int(pri.num("offer.round_down_to"))
            raw = min(ask * pri.num("offer.opening_fraction_of_ask"), D(walk))
            opening = int(raw // step) * step
            if opening > 0:
                out["opening_offer"] = _datum(opening, "RECOMMENDATION", pid, unit="USD",
                                              note=f"{int(pri.num('offer.opening_fraction_of_ask') * 100)}% of the ask, never above the price ceiling")
            else:
                omitted.append("opening_offer: rounds to $0")
        else:
            omitted.append("opening_offer: needs a fixed asking price")
    else:
        omitted.append("max_acquisition/opening_offer: no buy price makes this deal reach YES")

    comps = _sold_comps(item)
    if comps:
        prices = sorted(D(c["sold_price"]) for c in comps)
        n = len(prices)
        if n >= int(pri.num("enrichment.min_sold_comps_for_range")):
            agg = aggregate_sold_comps([{"sold_price": c["sold_price"]} for c in comps], cfg)
            lo, mid, hi = agg["comp_price_low"], agg["comp_price_expected"], agg["comp_price_high"]
            trimmed = n - agg["n_used"]
            how = (f"{n} FACT sold comps" + (f" (the highest and lowest dropped as outliers; middle {agg['n_used']} used)" if trimmed else "")
                   + ": 25th percentile / median / 75th percentile")
        elif n == 2:
            lo, hi = prices[0], prices[1]
            mid = money((lo + hi) / 2)
            how = "2 FACT sold comps (lower / mean / higher)"
        else:
            lo = hi = None
            mid = prices[0]
            how = "1 FACT sold comp (no range from a single sale)"
        out["resale_likely"] = _datum(mid, "INFERENCE", pid, unit="USD", low=lo, high=hi, note=how)
        if lo is not None and hi is not None:
            out["resale_conservative"] = _datum(lo, "INFERENCE", pid, unit="USD", note=how)
            out["resale_optimistic"] = _datum(hi, "INFERENCE", pid, unit="USD", note=how)
        else:
            omitted.append("resale_conservative/optimistic: fewer than 2 sold comps")
    else:
        omitted.append("resale_*: no FACT sold comps (asking-price estimates are not shown as resale ranges)")

    tr_extra = D(d.get("transport_extra_cash", 0))
    out["transport_cost"] = _datum(D(d["trips_cash"]) + tr_extra, "INFERENCE", pid, unit="USD",
                                   note="fuel and wear for the trips" + (f", plus ${tr_extra:g} for towing a trailer" if tr_extra else ""))
    ttc = D(d["time_to_cash_days"])
    doms = sorted(D(c["dom_days"]) for c in (item["economics"].get("estimates_meta") or {}).get("comps") or []
                  if c.get("dom_days") is not None)
    low = high = None
    if len(doms) >= 2:
        med = (doms[len(doms) // 2] if len(doms) % 2 else (doms[len(doms) // 2 - 1] + doms[len(doms) // 2]) / 2)
        low, high = max(D(1), ttc - med + doms[0]), ttc - med + doms[-1]
    out["days_to_cash"] = _datum(ttc, "INFERENCE", pid, unit="days", low=low, high=high,
                                 note="lead + repair + expected days on market" + (" (range from the comps' days on market)" if low is not None else ""))
    return out, omitted


# --------------------------------------------------------------------------- logistics

def _logistics_block(item: dict, pid: str, cfg: ScoringConfig, pri: ScoringConfig, profile: dict | None) -> tuple[dict, list[str]]:
    sc = (item.get("scores") or {}).get("scorecard")
    econ = item.get("economics") or {}
    if not sc or sc.get("lane") != "flip" or not (econ.get("logistics") or {}).get("trips"):
        return {}, ["logistics: not a scored flip with a trip plan"]
    d, out, omitted = sc["derived"], {}, []
    n = item.get("normalized") or {}
    transport = econ["logistics"].get("transport")
    if transport:
        mode, how = transport["mode"], "classified when the economics were estimated"
    else:
        mode, _ = classify_transport(item["category"], n.get("title"), pri)
        how = "classified from the category and type"
    miles = acquisition_round_trip_miles(econ["logistics"]["trips"])
    one_way = D(d["road_miles_one_way"]) if d.get("road_miles_one_way") is not None else None
    if mode is not None:
        towed = item["category"] in pri.get("transport.towed_categories")
        extra_cash = D(d.get("transport_extra_cash", 0))
        extra_hours = D(d.get("transport_extra_hours", 0))
        note = how + ("; towed behind the truck (tow rating and hitch are not on file)" if towed and mode == "fits_truck" else "")
        if mode == "requires_trailer":
            status = trailer_status(profile, pri)
            note += (f"; {status} trailer: the score already includes ${extra_cash:g} and {extra_hours:g} h for it. "
                     "Cost, not a rejection")
        out["transport_mode"] = _datum(mode, "INFERENCE", pid, note=note)
    else:
        omitted.append("transport_mode: not definite for this category/type")
    out["trip_miles_round_trip"] = _datum(miles, "INFERENCE", pid, unit="miles",
                                          note="pickup trip only (inspect and collect); the buyer meeting is a separate local trip")
    speed = D(econ["logistics"].get("avg_speed_mph", cfg.num("vehicle.avg_speed_mph")))
    hours = fine(miles / speed) + D(d.get("transport_extra_hours", 0))
    out["trip_hours"] = _datum(hours, "INFERENCE", pid, unit="hours",
                               note="driving time" + (" plus fetching, hooking up and loading the trailer" if d.get("transport_extra_hours") else ""))
    fuel = D(econ["logistics"].get("fuel_price_per_gal", cfg.num("vehicle.fuel_price_per_gal")))
    mpg = D(econ["logistics"].get("vehicle_mpg", cfg.num("vehicle.vehicle_mpg")))
    out["fuel_cost"] = _datum(money(miles * fuel / mpg), "INFERENCE", pid, unit="USD",
                              note="fuel at the truck's normal mileage; the towing premium is inside transport_cost")
    diff = difficulty(mode, one_way, pri)
    if diff:
        out["difficulty"] = _datum(diff[0], "INFERENCE", pid, note=f"{diff[1]}. An economic input (already in the score), never a rejection")
    else:
        omitted.append("difficulty: needs the transport mode and the distance")
    return out, omitted


# --------------------------------------------------------------------------- seasonality

def _match_entry(item: dict, table: dict, pri: ScoringConfig) -> dict | None:
    cat = item.get("category")
    key = query_key(cat, (item.get("normalized") or {}).get("title"), pri)
    tokens = set(key.values())
    cands = [e for e in table["entries"] if e["category"] == cat]
    typed = [e for e in cands if e["type_tokens"] and tokens & set(e["type_tokens"])]
    if typed:
        return typed[0]
    return next((e for e in cands if not e["type_tokens"]), None)


def _seasonality_block(item: dict, as_of: str, pid: str, table: dict, pri: ScoringConfig) -> tuple[dict, list[str]]:
    e = _match_entry(item, table, pri)
    if e is None:
        return {}, [f"seasonality: no sourced entry for category {item.get('category')!r}"]
    month = parse_ts(as_of).month
    peak, low = e["peak_months"], e["low_months"]
    demand = "strong" if month in peak else ("weak" if month in low else "normal")
    basis = e["basis"]
    out: dict[str, Any] = {"demand_now": _datum(demand, basis, pid, note=f"{_month_name(month)}: " + (
        "in the peak months" if demand == "strong" else "in the slow months" if demand == "weak" else "neither peak nor slow"))}
    if demand == "strong":
        hold = "short: in season, expect it to sell within weeks"
    elif demand == "weak":
        nxt = next((m for m in sorted(peak) if m > month), (sorted(peak)[0] if peak else None))
        hold = (f"long: likely to hold until {_month_name(nxt)} when demand picks up" if nxt else "long: demand is weak now")
    else:
        hold = "typical for the category"
    out["hold_likely"] = _datum(hold, basis, pid)
    if peak:
        out["peak_months"] = list(peak)
    srcs = "; ".join(s["title"] for s in e["sources"]) or ("owner statement: " + e.get("owner_stated", "none"))
    out["note"] = _datum(e["note"] + " [source: " + srcs + "]", basis, pid)
    return out, []


# --------------------------------------------------------------------------- why

def _why_lines(item: dict, as_of: str, econ_b: dict, log_b: dict, season_b: dict, cfg: ScoringConfig,
               listing_activity: dict | None) -> list[str]:
    sc = (item.get("scores") or {}).get("scorecard")
    if not sc:
        return []
    d, lane = sc["derived"], sc["lane"]
    target = cfg.num(f"time_value.w_target_{lane}_per_hour")
    caps_eff = effective_caps(item.get("economics") or {}, cfg)
    cap = caps_eff["cash_cap"]
    out: list[str] = []
    ev_pph, cash, verdict = D(d["ev_profit_per_hour"]), D(d["cash_tied_up"]), sc["decision"]
    if verdict == "YES":
        out.append(f"Meets your bar: about ${ev_pph:,.0f}/h expected against your ${target:g}/h {lane} target, "
                   f"with {_usd(cash)} of cash at risk (limit {_usd(cap)}).")
    elif verdict == "MAYBE":
        blocks = [k for k, ok in (sc.get("yes_conditions") or {}).items() if not ok]
        if "ev_pph_target_ok" in blocks:
            tail = ""
            if sc.get("walk_away_price") is not None:
                tail = f" Buying at or below {_usd(sc['walk_away_price'])} would clear it."
            elif sc.get("min_quote_for_yes") is not None:
                tail = f" Quoting {_usd(sc['min_quote_for_yes'])} or more would clear it."
            out.append(f"Not a YES yet: about ${ev_pph:,.0f}/h expected, under your ${target:g}/h {lane} target.{tail}")
        cde = sc.get("evidence_search") or {}
        if cde.get("items"):
            words = _join([_EVIDENCE_WORDS.get(i, i.replace("_", " ")) for i in cde["items"]])
            out.append(f"More evidence would settle it: {words}.")
    else:
        failed = [k for k, ok in (sc.get("gates") or {}).items() if not ok]
        text = {"cash_ok": f"cash tied up of {_usd(cash)} is over your {_usd(cap)} per-deal limit",
                "max_loss_ok": f"the worst case loses {_usd(d['max_loss'])}, over your {_usd(caps_eff['max_loss_cap'])} limit",
                "pph_floor_ok": f"it pays about ${D(d['profit_per_hour_deterministic']):,.0f}/h even when everything goes right, under your ${cfg.num('time_value.w_min_per_hour'):g}/h floor",
                "class_profit_ok": f"the profit if it goes to plan ({_usd(d['net_profit_deterministic'])}) is under what a {str(d.get('deal_class', 'deal')).lower().replace('_', ' ')} must clear",
                "ev_positive": "the expected value after risk is not positive",
                "skill_ok": "it needs skills outside your profile", "license_ok": "it needs a license you do not hold",
                "distance_ratio_ok": "the travel eats too much of the profit at this distance"}
        if failed:
            out.append("Passed because " + "; ".join(text.get(g, g) for g in failed) + ".")
        if sc.get("pass_on_priors"):
            out.append("That rejection rests on estimates rather than evidence, so it is held for research instead of being discarded.")

    if econ_b.get("max_acquisition") and verdict != "YES" and "clears" in (econ_b["max_acquisition"].get("note") or ""):
        out.append(f"Economically it works up to {_usd(econ_b['max_acquisition']['value'])}, once the missing evidence checks out.")
    if econ_b.get("resale_likely"):
        r = econ_b["resale_likely"]
        n_comps = int(re.match(r"(\d+)", r["note"]).group(1))
        line = f"{n_comps} sold comparable{'s' if n_comps != 1 else ''} put likely resale near {_usd(r['value'])}"
        if "low" in r:
            line += f" (range {_usd(r['low'])} to {_usd(r['high'])})"
        out.append(line + ".")
    elif lane == "flip":
        out.append("No sold comparables yet, so resale is not estimated from guesses.")
    ask = ((item.get("normalized") or {}).get("price") or {}).get("amount")
    if ask is not None and econ_b.get("max_acquisition"):
        w = D(econ_b["max_acquisition"]["value"])
        gap = D(ask) - w
        out.append(f"Asking {_usd(ask)} is {_usd(abs(gap))} {'above' if gap > 0 else 'below'} the most you should pay ({_usd(w)}).")
    mode = (log_b.get("transport_mode") or {}).get("value")
    if mode == "requires_trailer":
        out.append(f"Needs a trailer: about ${D(d.get('transport_extra_cash', 0)):g} and {D(d.get('transport_extra_hours', 0)):g} h are already in the "
                   "score. That is a cost and a confirmation step with the lender, not a reason to skip it.")
    elif mode == "fits_truck" and item.get("category") in ("trailer",):
        out.append("Towed behind the truck; its tow rating and hitch are not on file.")
    elif mode == "fits_truck":
        out.append("Fits the truck; no trailer needed.")
    elif lane == "flip" and mode is None:
        out.append("Whether it fits the truck or needs a trailer is UNKNOWN (not definite for this listing); "
                   "no transport penalty is assumed.")
    if listing_activity:
        out.extend(_listing_lines(listing_activity, as_of))
    dn = (season_b.get("demand_now") or {}).get("value")
    if dn == "strong":
        out.append(f"{_month_name(parse_ts(as_of).month)} is a strong-demand month for this category.")
    elif dn == "weak":
        out.append(f"{_month_name(parse_ts(as_of).month)} is a weak-demand month for this category; expect a longer hold.")
    return out


def _listing_lines(la: dict, as_of: str) -> list[str]:
    age = (la.get("age_days") or {}).get("value")
    upd = (la.get("updated_at") or {}).get("value")
    if not isinstance(age, (int, float)):
        return []
    since_update = None
    if isinstance(upd, str) and upd != "UNKNOWN":
        try:
            since_update = (parse_ts(as_of) - parse_ts(upd)).days
        except ValueError:
            since_update = None
    if age >= 30 and since_update is not None and since_update <= 14:
        return [f"Old listing ({age:g} days), but the seller updated it {since_update} days ago, reducing stale-listing risk."]
    if age >= 30:
        return [f"Old listing ({age:g} days) with no recent update: stale-listing risk is real."]
    if age <= 7:
        return [f"Fresh listing ({age:g} days old)."]
    return []


# --------------------------------------------------------------------------- entry point

def build_enrichment(item: dict, as_of: str, *, cfg: ScoringConfig, priors: ScoringConfig, seasonality: dict | None = None,
                     profile: dict | None = None, listing_activity: dict | None = None) -> dict:
    """Return ``{"blocks": {...}, "provenance": {...}, "omitted": {block: [reasons]}, "enrichment_hash": ...}``. Pure."""
    table = seasonality or load_seasonality()
    sc = (item.get("scores") or {})
    key = content_hash({"spec": "mbos.economics.enrich/v1", "engine": ENRICH_VERSION, "as_of": as_of,
                        "item_id": item.get("item_id"), "scorecard_id": sc.get("scorecard_id"),
                        "inputs_hash": sc.get("inputs_hash"), "priors": priors.hash, "config": cfg.hash,
                        "seasonality": table["_hash"], "profile": profile, "listing_activity": listing_activity})
    pid = derived_ulid("prov", as_of, "enrich|" + key)
    econ_b, o1 = _economics_block(item, as_of, pid, cfg, priors)
    log_b, o2 = _logistics_block(item, pid, cfg, priors, profile)
    sea_b, o3 = _seasonality_block(item, as_of, pid, table, priors) if item.get("type") == "flip" else ({}, ["seasonality: flips only"])
    why = _why_lines(item, as_of, econ_b, log_b, sea_b, cfg, listing_activity)
    blocks = {k: v for k, v in (("economics", econ_b), ("logistics", log_b), ("seasonality", sea_b)) if v}
    if why:
        blocks["why"] = why
    upstream = sorted({s["provenance_id"] for s in item.get("sources", []) if s.get("provenance_id")}
                      | {r["provenance_id"] for r in item.get("research", []) if r.get("provenance_id")}
                      | ({(item.get("recommendation") or {}).get("provenance_id")} - {None}))
    provenance = {
        "provenance_id": pid, "created_at": as_of, "actor_type": "system", "agent_name": "agent-03-economics",
        "basis": "INFERENCE", "tool_name": TOOL_NAME, "tool_version": ENRICH_VERSION,
        "config_version": priors.version,
        "inputs_used": [{"ref": "scorecard.inputs_hash", "hash": sc.get("inputs_hash") or "sha256:" + "0" * 64},
                        {"ref": f"estimation-priors@{priors.version}", "hash": priors.hash},
                        {"ref": f"seasonality@{table['seasonality_version']}", "hash": table["_hash"]}],
        **({"derived_from": upstream} if upstream else {}),
    }
    return {"blocks": blocks, "provenance": provenance,
            "omitted": {k: v for k, v in (("economics", o1), ("logistics", o2), ("seasonality", o3)) if v},
            "enrichment_hash": key}
