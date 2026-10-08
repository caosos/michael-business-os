"""Shared test helpers, including an independent reference ledger.

``reference_*`` re-derive the deterministic ledger and the EV tree straight from
the research formulas, in plain float arithmetic and without importing any
engine module. Agreement to the cent is a second, independent check on the
engine's arithmetic (not a copy of it).
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))

from mbos_economics.config import load_config  # noqa: E402
from mbos_economics.engine import score_item  # noqa: E402
from worked_cases import SCORED_AT, fresh  # noqa: E402

CFG = load_config()


def _with_caps(cfg, cash_cap, loss_cap):
    """A copy of ``cfg`` with other per-deal caps. Mechanics tests on big-ticket worked cases (trailer, truck) use
    the pre-C-24 $1,500 / $800 caps so they keep testing arithmetic, not the $500 bankroll (C-24)."""
    import copy
    from decimal import Decimal

    from mbos_economics.canonical import content_hash
    from mbos_economics.config import ScoringConfig
    raw = copy.deepcopy(cfg.raw)
    raw["capital_and_risk"]["risk_capital_per_deal_cap"]["value"] = Decimal(cash_cap)
    raw["capital_and_risk"]["max_loss_cap"]["value"] = Decimal(loss_cap)
    raw["scoring_config_version"] = cfg.version + "-bigcaps"
    return ScoringConfig(version=raw["scoring_config_version"], raw=raw, hash=content_hash(raw))


CFG_BIG = _with_caps(CFG, 1500, 800)


def run(item: dict, cfg=CFG, scored_at: str = SCORED_AT) -> dict:
    return score_item(item, cfg, scored_at)


def sc_of(item: dict, cfg=CFG) -> dict:
    return run(item, cfg)["scores"]["scorecard"]


def case(name: str) -> dict:
    return fresh(name)


def _r2(x: float) -> float:
    return math.floor(x * 100 + 0.5 + 1e-9) / 100


def _trips(trips, fuel=3.20, mpg=18.0, wear=0.28, speed=45.0):
    v = math.floor((fuel / mpg + wear) * 10000 + 0.5) / 10000
    cash = [_r2(t["round_trip_miles"] * v) for t in trips]
    hours = [math.floor(t["round_trip_miles"] / speed * 10000 + 0.5) / 10000 for t in trips]
    return v, cash, hours


def reference_flip(e: dict) -> dict:
    a, r, h, s, d = e["acquisition"], e["rehab"], e.get("holding", {}), e["resale"], e["downside"]
    lg = e["logistics"]
    v, cash, hours = _trips(lg["trips"], lg.get("fuel_price_per_gal", 3.20), lg.get("vehicle_mpg", 18),
                            lg.get("wear_per_mile", 0.28), lg.get("avg_speed_mph", 45))
    trips_cash = sum(cash)
    acq_cash = sum(c for c, t in zip(cash, lg["trips"]) if t["purpose"] not in ("buyer_meet", "deliver"))
    store = _r2(h.get("storage_cost_per_day", 0) * h.get("expected_hold_days", 0))
    r_net = s["target_sell_price"] - _r2(s["target_sell_price"] * h.get("sell_fees_rate", 0) + h.get("sell_fees_flat", 0))
    cost_out = a["expected_buy_price"] + a.get("buy_fees", 0) + r["parts_cost"] + r["materials_cost"] + trips_cash + store
    net = r_net - cost_out
    hrs = sum(hours) + r["labor_hours"] + r.get("admin_hours", 0)
    pr, ps = r["repair_success_prob"], s["sale_prob"]
    fail_cost = _r2(a["expected_buy_price"] + a.get("buy_fees", 0) + acq_cash + 0.3 * r["parts_cost"] + h.get("disposal_cost", 0))
    vals = [net, d["salvage_if_unsold"] - cost_out, d["salvage_if_repair_fails"] - fail_cost]
    probs = [pr * ps, pr * (1 - ps), 1 - pr]
    ev = _r2(sum(p * x for p, x in zip(probs, vals)))
    return {"trips_cash": round(trips_cash, 2), "cost_out": round(cost_out, 2), "net": round(net, 2),
            "hours": round(hrs, 4), "pph": _r2(net / hrs), "ev": ev, "ev_pph": _r2(ev / hrs),
            "max_loss": round(max(0.0, -min(x for p, x in zip(probs, vals) if p > 0)), 2)}


def reference_service(e: dict) -> dict:
    j, lg = e["job"], e["logistics"]
    v, cash, hours = _trips(lg["trips"])
    quote = [i for i, t in enumerate(lg["trips"]) if t["purpose"] == "estimate_visit"]
    sunk_cash = j.get("buy_fees", 0) + sum(cash[i] for i in quote)
    sunk_hours = sum(hours[i] for i in quote) + j.get("estimate_hours", 0)
    q = j["quoted_revenue"]
    rev_net = q - _r2(q * j.get("payment_fee_rate", 0) + j.get("payment_fee_flat", 0))
    cost_out = j.get("materials_cost", 0) + sum(cash) + j.get("disposal_cost", 0) + j.get("buy_fees", 0)
    net = rev_net - cost_out
    hrs = sum(hours) + j["labor_hours"] + j.get("admin_hours", 0) + j.get("estimate_hours", 0)
    deposit = _r2(q * j.get("deposit_rate", 0))
    pw, pc = j["win_prob"], j.get("completion_prob", 1)
    bad = _r2(deposit + 0.5 * (rev_net - deposit)) - cost_out
    ev = _r2(pw * pc * net + pw * (1 - pc) * bad + (1 - pw) * -sunk_cash)
    ev_hours = round(sunk_hours + pw * (hrs - sunk_hours), 4)
    return {"cost_out": round(cost_out, 2), "net": round(net, 2), "hours": round(hrs, 4), "pph": _r2(net / hrs),
            "ev": ev, "ev_pph": _r2(ev / ev_hours), "cash": round(max(0.0, cost_out - deposit), 2)}
