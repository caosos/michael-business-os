"""Lane economics: the cash / hours ledger and the expected-value tree.

FLIP (research §6.1–6.2)
    R_net        = R_sell − (R_sell·sell_fees_rate + sell_fees_flat)
    CostOut      = A + F_buy + P + M + TripsCash + C_store
    NetProfit    = R_net − CostOut                    (Michael's labor is NOT a cash cost)
    TotalHours   = H_travel + H_labor + H_admin
    CashTiedUp   = CostOut
    Tree         B1 repaired & sold     p_r·p_s       R_net − CostOut
                 B2 repaired, unsold    p_r·(1−p_s)   S_unsold − CostOut
                 B3 repair fails        1−p_r         S_fail − (A + F_buy + TripsCash_acq + f_diag·P + C_disp)

SERVICE (research §6.3, made explicit as a tree)
    Rev_net      = Q − (Q·payment_fee_rate + payment_fee_flat)
    Sunk         = buy_fees (lead/permit) + cash of estimate_visit trips   (spent win or lose)
    CostOut      = M + other trips cash + disposal + Sunk
    NetProfit    = Rev_net − CostOut
    CashTiedUp   = max(0, CostOut − deposit),  deposit = Q·deposit_rate
    Tree         won, clean      p_w·p_c        NetProfit
                 won, goes bad   p_w·(1−p_c)    deposit + recover·(Rev_net − deposit) − CostOut
                 lost bid        1−p_w          −Sunk
    ExpectedHours = SunkHours + p_w·(TotalHours − SunkHours)   (quote time is spent win or lose)
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal

from .config import ScoringConfig
from .numeric import D, ONE, ZERO, clamp, fine, money, sqrt

_SALE_SIDE_PURPOSES = {"buyer_meet", "deliver", "delivery", "sale_meet"}


@dataclass
class Branch:
    name: str
    prob: Decimal
    value: Decimal      # net cash result of the branch
    revenue: Decimal    # cash received in the branch


@dataclass
class LaneEconomics:
    lane: str
    v_per_mile: Decimal
    trips: list[dict]
    trips_cash: Decimal
    travel_hours: Decimal
    labor_hours: Decimal
    admin_hours: Decimal
    total_hours: Decimal
    cost_out: Decimal
    r_net: Decimal
    net_profit: Decimal
    pph: Decimal
    cash_tied_up: Decimal
    roi: Decimal
    branches: list[Branch]
    expected_revenue: Decimal
    ev_net_profit: Decimal
    ev_hours: Decimal
    ev_pph: Decimal
    ev_roi: Decimal
    max_loss: Decimal
    p_loss: Decimal
    cov: Decimal
    ttc_days: Decimal
    extra: dict = field(default_factory=dict)


def _g(block: dict, key: str, default: Decimal | None = None) -> Decimal:
    v = block.get(key)
    if v is None:
        if default is None:
            raise KeyError(key)
        return default
    return D(v)


def _trip_ledger(logistics: dict, cfg: ScoringConfig) -> tuple[Decimal, list[dict], Decimal, Decimal, Decimal]:
    fuel = _g(logistics, "fuel_price_per_gal", cfg.num("vehicle.fuel_price_per_gal"))
    mpg = _g(logistics, "vehicle_mpg", cfg.num("vehicle.vehicle_mpg"))
    wear = _g(logistics, "wear_per_mile", cfg.num("vehicle.wear_per_mile"))
    speed = _g(logistics, "avg_speed_mph", cfg.num("vehicle.avg_speed_mph"))
    v = fine(fuel / mpg + wear)
    rows = []
    for t in logistics.get("trips", []):
        miles = D(t["round_trip_miles"])
        rows.append({
            "purpose": t["purpose"],
            "round_trip_miles": miles,
            "cash": money(miles * v),
            "hours": fine(miles / speed),
        })
    cash = sum((r["cash"] for r in rows), ZERO)
    hours = sum((r["hours"] for r in rows), ZERO)
    return v, rows, cash, hours, speed


def _expected_revenue(branches: list[Branch]) -> Decimal:
    return money(sum((b.prob * b.revenue for b in branches), ZERO))


def _tree_stats(branches: list[Branch], ev: Decimal) -> tuple[Decimal, Decimal, Decimal]:
    live = [b for b in branches if b.prob > 0]
    worst = min((b.value for b in live), default=ZERO)
    max_loss = money(max(ZERO, -worst))
    p_loss = fine(sum((b.prob for b in live if b.value < 0), ZERO))
    if ev <= 0:
        cov = ONE
    else:
        var = sum((b.prob * (b.value - ev) ** 2 for b in live), ZERO)
        cov = fine(min(ONE, sqrt(var) / ev))
    return max_loss, p_loss, cov


def flip_economics(econ: dict, cfg: ScoringConfig) -> LaneEconomics:
    acq, rehab, hold = econ["acquisition"], econ["rehab"], econ.get("holding", {})
    resale, down = econ["resale"], econ["downside"]
    v, trips, trips_cash, travel_hours, _ = _trip_ledger(econ["logistics"], cfg)
    trips_cash_acq = sum((t["cash"] for t in trips if t["purpose"] not in _SALE_SIDE_PURPOSES), ZERO)

    a = D(acq["expected_buy_price"])
    f_buy = _g(acq, "buy_fees", ZERO)
    p = D(rehab["parts_cost"])
    m = D(rehab["materials_cost"])
    labor = D(rehab["labor_hours"])
    admin = _g(rehab, "admin_hours", ZERO)

    if hold.get("expected_hold_days") is not None:
        hold_days = D(hold["expected_hold_days"])
    else:
        hold_days = _g(rehab, "repair_days", ZERO) + _g(
            resale, "expected_dom_days", cfg.num("time_to_cash.flip_dom_days_default"))
    c_store = money(_g(hold, "storage_cost_per_day", ZERO) * hold_days)
    c_disp = _g(hold, "disposal_cost", ZERO)

    r_sell = D(resale["target_sell_price"])
    f_sell = money(r_sell * _g(hold, "sell_fees_rate", ZERO) + _g(hold, "sell_fees_flat", ZERO))
    r_net = r_sell - f_sell

    # Transport difficulty is an ECONOMIC input, never a gate: a trailer-requiring deal pays extra cash/hours
    # (borrowed-trailer fuel, wear, hookup, loading) and is still scored on its merits.
    tr = econ["logistics"].get("transport") or {}
    tr_cash, tr_hours = _g(tr, "extra_cash", ZERO), _g(tr, "extra_hours", ZERO)

    cost_out = a + f_buy + p + m + trips_cash + tr_cash + c_store
    net = r_net - cost_out
    total_hours = travel_hours + tr_hours + labor + admin
    if total_hours <= 0:
        raise ValueError("total hours must be > 0 to compute profit/hour")
    pph = money(net / total_hours)
    cash = cost_out
    roi = fine(net / max(cash, ONE))

    p_r = D(rehab["repair_success_prob"])
    p_s = D(resale["sale_prob"])
    f_diag = cfg.num("capital_and_risk.f_diag_parts_fraction_on_fail")
    cost_out_fail = money(a + f_buy + trips_cash_acq + tr_cash + f_diag * p + c_disp)   # the trailer trip happened
    branches = [
        Branch("repaired_and_sold", p_r * p_s, net, r_net),
        Branch("repaired_unsold", p_r * (ONE - p_s), D(down["salvage_if_unsold"]) - cost_out,
               D(down["salvage_if_unsold"])),
        Branch("repair_failed", ONE - p_r, D(down["salvage_if_repair_fails"]) - cost_out_fail,
               D(down["salvage_if_repair_fails"])),
    ]
    ev = money(sum((b.prob * b.value for b in branches), ZERO))
    max_loss, p_loss, cov = _tree_stats(branches, ev)

    acquire_lead = _g(acq, "acquire_lead_days", cfg.num("time_to_cash.flip_acquire_lead_days_default"))
    ttc = acquire_lead + hold_days

    return LaneEconomics(
        lane="flip", v_per_mile=v, trips=trips, trips_cash=trips_cash, travel_hours=travel_hours,
        labor_hours=labor, admin_hours=admin, total_hours=total_hours, cost_out=cost_out,
        r_net=r_net, net_profit=net, pph=pph, cash_tied_up=cash, roi=roi, branches=branches,
        expected_revenue=_expected_revenue(branches), ev_net_profit=ev, ev_hours=total_hours, ev_pph=money(ev / total_hours),
        ev_roi=fine(ev / max(cash, ONE)), max_loss=max_loss, p_loss=p_loss, cov=cov, ttc_days=ttc,
        extra={
            "acquisition": a, "buy_fees": f_buy, "parts": p, "materials": m,
            "storage_cost": c_store, "hold_days": hold_days, "sell_fees": f_sell,
            "trips_cash_acquisition": trips_cash_acq, "cost_out_fail": cost_out_fail,
            **({"transport_mode": tr["mode"], "transport_extra_cash": tr_cash, "transport_extra_hours": tr_hours}
               if tr else {}),
        },
    )


def service_economics(econ: dict, cfg: ScoringConfig) -> LaneEconomics:
    job = econ["job"]
    v, trips, trips_cash, travel_hours, _ = _trip_ledger(econ["logistics"], cfg)
    quote_trips = [t for t in trips if t["purpose"] == "estimate_visit"]
    quote_cash = sum((t["cash"] for t in quote_trips), ZERO)
    quote_travel_hours = sum((t["hours"] for t in quote_trips), ZERO)

    q = D(job["quoted_revenue"])
    m = _g(job, "materials_cost", ZERO)
    buy_fees = _g(job, "buy_fees", ZERO)
    disposal = _g(job, "disposal_cost", ZERO)
    labor = D(job["labor_hours"])
    admin = _g(job, "admin_hours", ZERO)
    estimate_hours = _g(job, "estimate_hours", ZERO)

    pay_fees = money(q * _g(job, "payment_fee_rate", ZERO) + _g(job, "payment_fee_flat", ZERO))
    rev_net = q - pay_fees
    sunk_cash = buy_fees + quote_cash
    sunk_hours = quote_travel_hours + estimate_hours
    cost_out = m + (trips_cash - quote_cash) + disposal + sunk_cash
    net = rev_net - cost_out
    total_hours = travel_hours + labor + admin + estimate_hours
    if total_hours <= 0:
        raise ValueError("total hours must be > 0 to compute profit/hour")
    pph = money(net / total_hours)
    deposit = money(q * _g(job, "deposit_rate", ZERO))
    cash = max(ZERO, cost_out - deposit)
    roi = fine(net / max(cash, ONE))

    p_w = D(job["win_prob"])
    p_c = _g(job, "completion_prob", ONE)
    recover = cfg.num("service.revenue_recovered_if_job_goes_bad")
    bad_revenue = money(deposit + recover * (rev_net - deposit))
    branches = [
        Branch("won_clean", p_w * p_c, net, rev_net),
        Branch("won_goes_bad", p_w * (ONE - p_c), bad_revenue - cost_out, bad_revenue),
        Branch("lost_bid", ONE - p_w, -sunk_cash, ZERO),
    ]
    ev = money(sum((b.prob * b.value for b in branches), ZERO))
    max_loss, p_loss, cov = _tree_stats(branches, ev)
    ev_hours = fine(sunk_hours + p_w * (total_hours - sunk_hours))
    if ev_hours <= 0:
        raise ValueError("expected hours must be > 0")

    per_day = cfg.num("time_to_cash.service_hours_per_job_day")
    job_days = _g(job, "job_days", D(math.ceil(labor / per_day)) if labor > 0 else ONE)
    ttc = (_g(job, "schedule_lag_days", cfg.num("time_to_cash.service_schedule_lag_days_default"))
           + job_days
           + _g(job, "payment_terms_days", cfg.num("time_to_cash.service_payment_terms_days_default")))

    w_min = cfg.num("time_value.w_min_per_hour")
    return LaneEconomics(
        lane="service", v_per_mile=v, trips=trips, trips_cash=trips_cash, travel_hours=travel_hours,
        labor_hours=labor, admin_hours=admin, total_hours=total_hours, cost_out=cost_out,
        r_net=rev_net, net_profit=net, pph=pph, cash_tied_up=cash, roi=roi, branches=branches,
        expected_revenue=_expected_revenue(branches), ev_net_profit=ev, ev_hours=ev_hours, ev_pph=money(ev / ev_hours),
        ev_roi=fine(ev / max(cash, ONE)), max_loss=max_loss, p_loss=p_loss, cov=cov, ttc_days=ttc,
        extra={
            "quoted_revenue": q, "materials": m, "buy_fees": buy_fees, "payment_fees": pay_fees,
            "disposal": disposal, "deposit": deposit, "sunk_cash": sunk_cash, "sunk_hours": sunk_hours,
            "estimate_hours": estimate_hours, "job_days": job_days,
            "cost_to_quote": money(sunk_cash + sunk_hours * w_min),
        },
    )


def scarcity_flip(econ: dict, cfg: ScoringConfig) -> dict[str, Decimal]:
    """Unknown inputs earn no scarcity credit (conservative)."""
    acq, resale = econ["acquisition"], econ["resale"]
    a = D(acq["expected_buy_price"])
    med = acq.get("market_buy_median")
    deal_discount = fine(clamp((D(med) - a) / D(med))) if med is not None and D(med) > 0 else ZERO
    dom = resale.get("expected_dom_days")
    demand = fine(clamp(ONE - D(dom) / cfg.num("normalization_caps.dom_cap_days"))) if dom is not None else ZERO
    active = resale.get("active_comparable_listings")
    supply = fine(clamp(ONE - D(active) / cfg.num("normalization_caps.supply_cap_listings"))) if active is not None else ZERO
    w = cfg.group("scarcity_weights")
    score = fine(w["deal_discount"] * deal_discount + w["demand_velocity"] * demand + w["supply_tightness"] * supply)
    return {"deal_discount": deal_discount, "demand_velocity": demand, "supply_tightness": supply, "scarcity": score}
