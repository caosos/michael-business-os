"""Engine input: build it from an Item v1, and validate it.

The *engine input* is the complete, minimal document the arithmetic depends on::

    {
      "type": "flip" | "service",
      "category": "<Item v1 category>",
      "road_miles_one_way": <number> | null,    # Item.normalized.location.road_miles_one_way
      "economics": { ...03 flip or service economics block... },
      "research_ids": ["prov_...", ...]         # sorted, de-duplicated
    }

``inputs_hash`` is computed over exactly this plus ``scoring_config_version``,
so anything that can change a number is inside the hash and nothing else is.
"""

from __future__ import annotations

import copy
from decimal import Decimal
from typing import Any

from .numeric import D

FLIP_CATEGORIES = {
    "trailer", "mower", "generator", "welder", "compressor", "tool",
    "commercial_equipment", "mechanical_equipment", "project_vehicle", "other_asset",
}
SERVICE_CATEGORIES = {
    "mobile_repair", "equipment_repair", "drywall_repair", "assembly", "handyman",
    "smart_home_install", "technical_service", "mechanical_service", "other_service",
}


class InputError(ValueError):
    """The input cannot be scored. No scorecard is produced for invalid input."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = problems


# C-25 / F-90. Michael's attested confirmation of a requested decisive-evidence key is an Item.research entry
# whose ``field`` is ``attestation:<key>`` (spine ``record_attestation``, human provenance). Only boolean
# evidence a person can actually confirm is attestable: sold-comp counts, price spread and skill fit are
# computed from data and are never accepted from a statement.
ATTEST_PREFIX = "attestation:"
ATTESTABLE = {
    "flip": {"condition_verified", "fault_identified", "title_verified", "demand_evidence", "seller_screened",
             "remote_verification"},
    "service": {"scope_verified", "customer_screened", "price_agreed_in_writing", "materials_priced",
                "access_and_schedule_confirmed", "repeat_or_referral", "remote_verification"},
}


def attested_keys(item: dict) -> list[str]:
    """Sorted evidence keys Michael has attested on this Item (valid for its lane only)."""
    ok = ATTESTABLE.get(item.get("type"), set())
    keys = set()
    for r in item.get("research") or []:
        f = r.get("field")
        if isinstance(f, str) and f.startswith(ATTEST_PREFIX) and r.get("basis") != "UNKNOWN" and r.get("provenance_id"):
            if f[len(ATTEST_PREFIX):] in ok:
                keys.add(f[len(ATTEST_PREFIX):])
    return sorted(keys)


def build_engine_input(item: dict) -> dict:
    """Project an Item v1 onto the engine input. Pure; does not mutate ``item``."""
    loc = (item.get("normalized") or {}).get("location") or {}
    research_ids = sorted({r["provenance_id"] for r in item.get("research", []) if "provenance_id" in r})
    econ = copy.deepcopy(item.get("economics"))
    keys = attested_keys(item)
    if keys and isinstance(econ, dict):
        ev = econ.setdefault("estimates_meta", {}).setdefault("evidence", {})
        for k in keys:
            ev[k] = True            # attested evidence counts as that evidence; nothing else is invented
    return {
        "type": item.get("type"),
        "category": item.get("category"),
        "road_miles_one_way": loc.get("road_miles_one_way"),
        "economics": econ,
        "research_ids": research_ids,
    }


class _V:
    def __init__(self) -> None:
        self.problems: list[str] = []

    def num(self, block: dict, key: str, where: str, *, required: bool = True,
            lo: Decimal | None = Decimal(0), hi: Decimal | None = None, positive: bool = False) -> None:
        if key not in block or block[key] is None:
            if required:
                self.problems.append(f"{where}.{key} is required")
            return
        v = block[key]
        if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
            self.problems.append(f"{where}.{key} must be a number")
            return
        d = D(v)
        if not d.is_finite():
            self.problems.append(f"{where}.{key} must be finite")
        elif positive and d <= 0:
            self.problems.append(f"{where}.{key} must be > 0")
        elif lo is not None and d < lo:
            self.problems.append(f"{where}.{key} must be >= {lo}")
        elif hi is not None and d > hi:
            self.problems.append(f"{where}.{key} must be <= {hi}")

    def prob(self, block: dict, key: str, where: str, *, required: bool = True) -> None:
        self.num(block, key, where, required=required, lo=Decimal(0), hi=Decimal(1))

    def obj(self, parent: dict, key: str, where: str, *, required: bool = True) -> dict:
        v = parent.get(key)
        if v is None:
            if required:
                self.problems.append(f"{where}.{key} is required")
            return {}
        if not isinstance(v, dict):
            self.problems.append(f"{where}.{key} must be an object")
            return {}
        return v

    def skills(self, block: dict, where: str) -> None:
        v = block.get("required_skills")
        if not isinstance(v, list) or not all(isinstance(s, str) for s in v):
            self.problems.append(f"{where}.required_skills must be a list of strings")

    def flag(self, block: dict, key: str, where: str) -> None:
        if key in block and not isinstance(block[key], bool):
            self.problems.append(f"{where}.{key} must be a boolean")


def _trips(v: _V, logistics: dict) -> None:
    trips = logistics.get("trips")
    if not isinstance(trips, list):
        v.problems.append("economics.logistics.trips must be a list")
        return
    for i, t in enumerate(trips):
        w = f"economics.logistics.trips[{i}]"
        if not isinstance(t, dict) or not isinstance(t.get("purpose"), str):
            v.problems.append(f"{w}.purpose is required")
            continue
        v.num(t, "round_trip_miles", w)
    for k in ("fuel_price_per_gal", "wear_per_mile"):
        v.num(logistics, k, "economics.logistics", required=False)
    for k in ("vehicle_mpg", "avg_speed_mph"):
        v.num(logistics, k, "economics.logistics", required=False, positive=True)
    tr = logistics.get("transport")
    if tr is not None:
        if not isinstance(tr, dict):
            v.problems.append("economics.logistics.transport must be an object")
        else:
            if tr.get("mode") not in ("fits_truck", "requires_trailer"):
                v.problems.append("economics.logistics.transport.mode must be fits_truck or requires_trailer")
            for k in ("extra_cash", "extra_hours"):
                v.num(tr, k, "economics.logistics.transport", required=False)


def _context(v: _V, econ: dict) -> None:
    """Optional Michael-situation inputs (C-19). Absent or null = UNKNOWN; the engine never assumes."""
    ctx = econ.get("context")
    if ctx is None:
        return
    if not isinstance(ctx, dict):
        v.problems.append("economics.context must be an object")
        return
    if "current_cash" in ctx:
        v.problems.append("economics.context.current_cash is not accepted: current cash is Michael's profile "
                          "value (config operator_context.current_cash), the single source")
    if ctx.get("personal_use_value") is not None:
        v.num(ctx, "personal_use_value", "economics.context")
    if ctx.get("seasonality_factor") is not None:
        v.prob(ctx, "seasonality_factor", "economics.context")
    if ctx.get("available_to_deploy") is not None:     # capital ledger (C-24); null = UNKNOWN, config cap kept
        v.num(ctx, "available_to_deploy", "economics.context")


def _evidence(v: _V, meta: dict) -> None:
    ev = meta.get("evidence")
    if ev is None:
        return
    if not isinstance(ev, dict):
        v.problems.append("economics.estimates_meta.evidence must be an object")
        return
    for k, val in ev.items():
        if k == "sold_comps_count":
            v.num(ev, k, "economics.estimates_meta.evidence")
        elif k == "evidence_quality":
            v.prob(ev, k, "economics.estimates_meta.evidence")
        elif not isinstance(val, bool):
            v.problems.append(f"economics.estimates_meta.evidence.{k} must be a boolean")


def validate_engine_input(inp: Any) -> None:
    v = _V()
    if not isinstance(inp, dict):
        raise InputError(["engine input must be an object"])
    lane, cat = inp.get("type"), inp.get("category")
    if lane not in ("flip", "service"):
        raise InputError(["type must be 'flip' or 'service'"])
    allowed = FLIP_CATEGORIES if lane == "flip" else SERVICE_CATEGORIES
    if cat not in allowed:
        v.problems.append(f"category {cat!r} is not a {lane} category")
    v.num(inp, "road_miles_one_way", "input", required=False)
    rid = inp.get("research_ids", [])
    if not isinstance(rid, list) or rid != sorted(set(rid)):
        v.problems.append("research_ids must be a sorted, de-duplicated list")
    econ = v.obj(inp, "economics", "input")
    if not econ:
        raise InputError(v.problems)

    logistics = v.obj(econ, "logistics", "economics")
    _trips(v, logistics)
    meta = v.obj(econ, "estimates_meta", "economics")
    _evidence(v, meta)
    _context(v, econ)

    if lane == "flip":
        a = v.obj(econ, "acquisition", "economics")
        v.num(a, "expected_buy_price", "economics.acquisition")
        for k in ("ask_price", "buy_fees", "market_buy_median", "listing_age_hours",
                  "auction_ends_in_hours", "acquire_lead_days"):
            v.num(a, k, "economics.acquisition", required=False)
        r = v.obj(econ, "rehab", "economics")
        for k in ("parts_cost", "materials_cost", "labor_hours"):
            v.num(r, k, "economics.rehab")
        for k in ("admin_hours", "repair_days"):
            v.num(r, k, "economics.rehab", required=False)
        v.prob(r, "repair_success_prob", "economics.rehab")
        v.skills(r, "economics.rehab")
        v.flag(r, "repair_scope_known", "economics.rehab")
        v.flag(r, "requires_license_he_lacks", "economics.rehab")
        h = v.obj(econ, "holding", "economics")
        for k in ("storage_cost_per_day", "expected_hold_days", "disposal_cost", "sell_fees_flat"):
            v.num(h, k, "economics.holding", required=False)
        v.prob(h, "sell_fees_rate", "economics.holding", required=False)
        s = v.obj(econ, "resale", "economics")
        v.num(s, "target_sell_price", "economics.resale")
        v.prob(s, "sale_prob", "economics.resale")
        for k in ("comp_price_low", "comp_price_expected", "comp_price_high",
                  "expected_dom_days", "active_comparable_listings"):
            v.num(s, k, "economics.resale", required=False)
        dn = v.obj(econ, "downside", "economics")
        v.num(dn, "salvage_if_repair_fails", "economics.downside")
        v.num(dn, "salvage_if_unsold", "economics.downside")
        if not v.problems:
            r_net = D(s["target_sell_price"]) * (1 - D(h.get("sell_fees_rate", 0))) - D(h.get("sell_fees_flat", 0))
            for k in ("salvage_if_unsold", "salvage_if_repair_fails"):
                if D(dn[k]) > r_net:
                    v.problems.append(f"economics.downside.{k} exceeds net resale {r_net}: "
                                      "a salvage outcome cannot beat the planned sale")
    else:
        j = v.obj(econ, "job", "economics")
        v.num(j, "quoted_revenue", "economics.job")
        v.num(j, "labor_hours", "economics.job")
        v.prob(j, "win_prob", "economics.job")
        v.skills(j, "economics.job")
        for k in ("labor_revenue", "materials_cost", "material_markup_rate", "admin_hours",
                  "payment_terms_days", "buy_fees", "payment_fee_flat", "disposal_cost",
                  "estimate_hours", "schedule_lag_days", "job_days", "lead_age_hours"):
            v.num(j, k, "economics.job", required=False)
        for k in ("completion_prob", "deposit_rate", "lead_quality", "payment_fee_rate"):
            v.prob(j, k, "economics.job", required=False)
        v.flag(j, "requires_license_he_lacks", "economics.job")

    if v.problems:
        raise InputError(v.problems)
