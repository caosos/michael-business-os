"""C-21: Weekly Money Mission planner (ADR-0013, ``mission.schema.json``).

``plan_week(mission, ledger, scorecards)`` is pure and deterministic: no clock, no random, no LLM
arithmetic, nothing spent or contacted. It chooses the combination of scored opportunities (flips and
services) that maximises the probability of closing the weekly gap, subject to

  * cash: sum of ``cash_at_risk`` <= ``ledger.available_to_deploy``
  * time: sum of ``hours`` <= ``mission.hours_available`` (unconstrained, and said so, when null)
  * class velocity: only cash that returns inside the period counts toward this week

There is NO absolute-profit floor (ADR-0012). The probability is computed exactly by convolving each
leg's scorecard branches (independent legs). Ties within ``probability_resolution`` go to the plan that
puts less cash at risk, so ``DO_NOT_SPEND`` (services alone) wins when the flips add nothing.

Null is UNKNOWN: a null target gives a null ``remaining_gap`` and recommendation ``UNKNOWN``; a null
``hours_available`` leaves time unconstrained and is listed in ``unknowns``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any

from .numeric import D, ZERO, fine, money

PLANNER_CONFIG = Path(__file__).resolve().parent / "config" / "mission-planner.json"
PLAN_VERSION = "1.0.0"


def load_planner_config(path: Path = PLANNER_CONFIG) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)
    return {"version": raw["mission_planner_version"],
            **{k: v["value"] for k, v in raw.items() if isinstance(v, dict) and "value" in v}}


def _usd(x) -> str:
    x = D(x)
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


def _period_days(mission: dict) -> int:
    from datetime import date
    s, e = date.fromisoformat(mission["period"]["start"]), date.fromisoformat(mission["period"]["end"])
    return (e - s).days + 1


def _candidate(item: dict, period_days: int) -> dict | None:
    scores = item.get("scores") or {}
    sc = scores.get("scorecard")
    if not sc or sc.get("decision") == "PASS":
        return None
    d, rk = sc["derived"], sc.get("ranking") or {}
    branches = [(D(b["prob"]), D(b["value"])) for b in d["branches"]]
    values = [v for p, v in branches if p > 0]
    low, high = min(values), max(values)
    ev = D(d["ev_net_profit"])
    likely = min(max(ev, low), high)
    days = D(d["days_to_cash"])
    in_week = days <= period_days
    cls = d.get("deal_class", "OTHER_OPPORTUNITY")
    success = D(d["branches"][0]["prob"])           # the plan-goes-right branch is listed first
    cash = D(d["cash_at_risk"])
    return {
        "item_id": item["item_id"], "scorecard_id": scores["scorecard_id"], "decision": sc["decision"],
        "class": cls, "lane": sc["lane"], "cash": cash, "hours": D(d["total_hours"]),
        "low": money(low), "likely": money(likely), "high": money(high), "days": days, "p": success,
        "in_week": in_week, "branches": branches, "rank_score": D(rk.get("rank_score", 0)),
        "rank": rk, "cash_multiple": d.get("cash_multiple"), "expires": (item.get("recommendation") or {}).get("expires_at"),
    }


def _distribution(legs: list[dict]) -> dict[Decimal, Decimal]:
    """Exact distribution of this week's total (whole dollars). A leg whose cash returns after the
    period contributes 0 to this week in every branch (the cash is locked, not earned)."""
    dist = {ZERO: Decimal(1)}
    for leg in legs:
        nxt: dict[Decimal, Decimal] = {}
        for total, p in dist.items():
            for bp, bv in leg["branches"]:
                if bp == 0:
                    continue
                t = total + (bv.to_integral_value() if leg["in_week"] else ZERO)
                nxt[t] = nxt.get(t, ZERO) + p * bp
        dist = nxt
    return dist


def _p_close(dist: dict, target: Decimal | None) -> Decimal | None:
    if target is None:
        return None
    return sum((p for t, p in dist.items() if t >= target), ZERO)


def _leg_out(c: dict) -> dict:
    cls = c["class"]
    risk = "no capital at risk" if c["cash"] <= 0 else f"{_usd(c['cash'])} at risk"
    r = c["rank"]
    parts = [f"{c['decision']} {cls.lower().replace('_', ' ')}: {risk}, cash back in {c['days']} d, "
             f"{c['hours']} h, P(plan goes right) {fine(c['p'])}"]
    if r:
        parts.append(f"rank {r['rank_score']} = risk-adjusted {_usd(r['risk_adjusted_profit'])} x conf {r['confidence']} "
                     f"x velocity {r['capital_velocity']}/day")
        if c["lane"] == "service" or c["cash"] <= 0:
            parts.append("services rank on profit x confidence: no capital to turn over")
    if not c["in_week"]:
        parts.append("cash returns after this week: counted as locked, not as this week's income")
    if c["decision"] == "MAYBE":
        parts.append("MAYBE: evidence still outstanding")
    return {"item_id": c["item_id"], "scorecard_id": c["scorecard_id"], "opportunity_class": cls,
            "cash_at_risk": float(money(c["cash"])),
            "expected_net": {"low": float(c["low"]), "likely": float(c["likely"]), "high": float(c["high"])},
            "days_to_cash": float(c["days"]), "success_probability": float(fine(c["p"])),
            "hours": float(c["hours"]), "why": "; ".join(parts)}


def plan_week(mission: dict, ledger: dict, scorecards: list[dict], *, planner: dict | None = None) -> dict:
    """Return a ``mission_plan`` (``mission.schema.json``). ``scorecards`` are scored Items."""
    pc = planner or load_planner_config()
    target = D(mission["weekly_target_usd"]) if mission.get("weekly_target_usd") is not None else None
    hours_cap = D(mission["hours_available"]) if mission.get("hours_available") is not None else None
    avail = D(ledger["available_to_deploy"])
    pdays = _period_days(mission)

    cands = []
    for it in sorted(scorecards, key=lambda i: str(i.get("item_id"))):
        c = _candidate(it, pdays)
        if c is None or (c["decision"] == "MAYBE" and not pc["include_maybe"]) or c["likely"] <= 0:
            continue
        cands.append(c)
    cands.sort(key=lambda c: (-c["rank_score"], c["item_id"]))
    pool = cands[: int(pc["max_candidates"])]
    res = pc["probability_resolution"]

    feasible = []
    for n in range(len(pool) + 1):
        for combo in combinations(pool, n):
            cash = sum((c["cash"] for c in combo), ZERO)
            hours = sum((c["hours"] for c in combo), ZERO)
            if cash > avail or (hours_cap is not None and hours > hours_cap):
                continue
            p = _p_close(_distribution(list(combo)), target)
            quant = p if p is not None else ZERO
            likely = sum((c["likely"] for c in combo if c["in_week"]), ZERO)
            feasible.append((quant, likely, cash, combo))
    top = max((f[0] for f in feasible), default=ZERO)
    reachable = top > 0
    if reachable:
        # within `probability_resolution` of the best probability counts as equally good: then risk less cash
        feasible = [f for f in feasible if f[0] >= top - res]

    def pick(f):
        quant, likely, cash, combo = f
        ids = tuple(sorted((c["item_id"] for c in combo), reverse=True))
        # reachable target: (near-)maximal P(close), then risk LESS cash, then more expected net.
        # unreachable or unknown target: maximise expected net, then risk less cash.
        head = (-cash, quant, likely) if reachable else (likely, -cash)
        return head + (-len(combo), ids)

    best = list(max(feasible, key=pick)[3])
    legs = sorted(best, key=lambda c: (-c["rank_score"], c["item_id"]))

    in_week = [c for c in legs if c["in_week"]]
    low = sum((c["low"] for c in in_week), ZERO)
    likely = sum((c["likely"] for c in in_week), ZERO)
    high = sum((c["high"] for c in in_week), ZERO)
    dist = _distribution(legs)
    p_close = _p_close(dist, target)
    spend = sum((c["cash"] for c in legs), ZERO)
    skipped_flips = [c for c in cands if c not in legs and c["lane"] == "flip" and c["cash"] > 0]

    if target is None:
        rec = "UNKNOWN"
    elif not legs:
        rec = "HOLD"
    elif spend <= 0 and skipped_flips:
        rec = "DO_NOT_SPEND"
    elif spend <= 0:
        rec = "DO_NOT_SPEND" if legs else "HOLD"
    else:
        rec = "DEPLOY"

    unknowns = []
    if target is None:
        unknowns.append("weekly_target_usd")
    if hours_cap is None:
        unknowns.append("hours_available (time unconstrained)")
    unknowns.append("current_cash_context" if all(
        (c["rank"] or {}).get("cash_share_of_current_cash") is None for c in legs) else "")
    unknowns = [u for u in unknowns if u]
    if any(c["days"] is None for c in legs):
        unknowns.append("days_to_cash")

    if target is None or hours_cap is None:
        conf = "UNKNOWN" if target is None else "low"
    elif not legs:
        conf = "low"
    elif any(c["decision"] == "MAYBE" for c in legs) or p_close is None or p_close < pc["medium_confidence_probability"]:
        conf = "low"
    elif p_close >= pc["high_confidence_probability"]:
        conf = "high"
    else:
        conf = "medium"

    gap = float(money(target - likely)) if target is not None else None
    exp = _explain(rec, target, legs, skipped_flips, p_close, spend, avail, hours_cap, pc, pdays, likely)
    return {
        "plan_version": PLAN_VERSION,
        "mission": mission,
        "ledger": ledger,
        "recommendation": rec,
        "legs": [_leg_out(c) for c in legs],
        "projected_week": {"low": float(money(low)), "likely": float(money(likely)), "high": float(money(high))},
        "remaining_gap": gap,
        "confidence": conf,
        "replace_if_stale": sorted({c["item_id"] for c in legs if c["decision"] == "MAYBE" or c["expires"]}),
        "unknowns": unknowns,
        "explanation": exp,
    }


def _explain(rec, target, legs, skipped_flips, p_close, spend, avail, hours_cap, pc, pdays, likely) -> str:
    out = [f"Planner {pc['version']}; deterministic; no absolute-profit floor (ADR-0012)."]
    if target is None:
        out.append("Weekly target is UNKNOWN: legs are the best expected-value combination, the gap is not computed.")
    elif p_close is not None:
        out.append(f"Probability this plan reaches {_usd(target)} inside {pdays} days: {fine(p_close)} "
                   f"(independent legs, exact over scorecard branches).")
    out.append(f"Cash at risk {_usd(spend)} of {_usd(avail)} available; "
               + (f"{sum((c['hours'] for c in legs), ZERO)} of {hours_cap} h." if hours_cap is not None
                  else "hours unconstrained (UNKNOWN)."))
    if rec == "DO_NOT_SPEND":
        out.append("DO_NOT_SPEND: the services alone give the best chance; "
                   + (f"{len(skipped_flips)} flip(s) that put cash at risk added no meaningful probability." if skipped_flips
                      else "no flips qualified."))
    if rec == "DEPLOY" and legs and not any(c["lane"] == "flip" for c in legs) and skipped_flips:
        out.append("Services only: no flip capital is deployed (only the service materials cash shown on the legs); "
                   f"{len(skipped_flips)} flip(s) added no meaningful probability of closing the gap.")
    if rec == "HOLD":
        out.append("HOLD: no scored opportunity is worth acting on this week.")
    if target is not None and likely < target:
        out.append(f"The plan does not close the gap (short by about {_usd(target - likely)}); it says so rather "
                   f"than stretching into a risky buy.")
    return " ".join(out)
