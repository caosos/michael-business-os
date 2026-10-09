"""C-32: auction all-in cost model, time to cash, capital turnover and profit per labor hour.

All-in cost = hammer + buyer premium + sales tax (on hammer + premium) + pickup + transport + other fixed.
Resale value comes from SOLD comps only (``aggregate_sold_comps``); asking prices are listed in ``evidence`` for
context and never count as completed sales, so asking-only evidence cannot yield YES (capped at MAYBE).
Missing required inputs make the figure ``None`` and are named in ``unknowns``; nothing is invented.
Pure and deterministic. Config: ``config/auction-model.json`` (separate file, additive).
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .comps import aggregate_sold_comps
from .config import ScoringConfig, load_config
from .numeric import D, ONE, ZERO, fine, money, to_json_number

AUCTION_VERSION = "1.0.0"
AUCTION_CONFIG = Path(__file__).resolve().parent / "config" / "auction-model.json"
_REQUIRED = ("hammer_price", "buyer_premium_pct", "sales_tax_rate", "pickup_cost", "transport_cost",
             "labor_hours", "days_to_sell", "pickup_wait_hours")


def load_auction_config(path: Path = AUCTION_CONFIG) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)
    return {k: (v["value"] if isinstance(v, dict) and "value" in v else v) for k, v in raw.items()}


def _num(v) -> bool:
    return isinstance(v, (int, float, Decimal)) and not isinstance(v, bool) and v >= 0


def _o(x):
    return None if x is None else to_json_number(x)


def split_comps(comps: list[dict]) -> tuple[list[dict], list[dict]]:
    """(sold, asking). A comp is sold only with a ``sold_price`` and no asking/listed status."""
    sold, asking = [], []
    for c in comps or []:
        if c.get("sold_price") is not None and c.get("kind", "sold") == "sold" and c.get("status") not in ("asking", "listed"):
            sold.append(c)
        elif c.get("asking_price") is not None or c.get("sold_price") is not None:
            asking.append(c)
    return sold, asking


def all_in_cost(hammer: Decimal, premium_pct: Decimal, tax_rate: Decimal, fixed: Decimal) -> dict:
    premium = money(hammer * premium_pct)
    tax = money((hammer + premium) * tax_rate)
    return {"hammer": money(hammer), "buyer_premium": premium, "sales_tax": tax, "pickup_and_transport": money(fixed),
            "all_in": money(hammer + premium + tax + fixed)}


def evaluate(inp: dict, cfg: ScoringConfig | None = None, acfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    a = acfg or load_auction_config()
    missing = [f"auction:{k}" for k in _REQUIRED if not _num(inp.get(k))]
    sold, asking = split_comps(inp.get("comps") or [])
    agg = aggregate_sold_comps(sold, cfg)
    if agg is None:
        missing.append("auction:sold_comps")
    out = {"auction_model_version": a["auction_model_version"], "module_version": AUCTION_VERSION,
           "item_id": inp.get("item_id"), "dry_run": True,
           "evidence": {"sold_comps_used": agg["n_used"] if agg else 0, "sold_comps_count": len(sold),
                        "asking_comps_count": len(asking), "asking_counted_as_sold": False,
                        "asking_prices": sorted(_o(D(c.get("asking_price", c.get("sold_price")))) for c in asking)}}
    if missing:
        out.update(computable=False, verdict="HOLD", unknowns=sorted(set(missing)), cost=None, flags=_flags(None, None, a),
                   reasons=["missing inputs: " + ", ".join(sorted(set(missing)))])
        return out
    h, p, t = D(inp["hammer_price"]), D(inp["buyer_premium_pct"]), D(inp["sales_tax_rate"])
    fixed = D(inp["pickup_cost"]) + D(inp["transport_cost"]) + D(inp.get("other_fixed_cost", 0))
    cost = all_in_cost(h, p, t, fixed)
    allin = cost["all_in"]
    fee = D(inp.get("resale_fee_pct", 0))
    keep = ONE - fee
    net = {k: money(agg[f"comp_price_{k}"] * keep - allin) for k in ("low", "expected", "high")}
    hours = D(inp["labor_hours"])
    pph = fine(net["expected"] / hours) if hours > 0 else None
    ttc_h = fine(D(inp["pickup_wait_hours"]) + D(inp["days_to_sell"]) * 24 + D(inp.get("payout_lag_days", a["payout_lag_days"])) * 24)
    turns_30d = fine(D(30) * 24 / ttc_h) if ttc_h > 0 else None
    flags = _flags(ttc_h, D(inp["days_to_sell"]), a)
    # walk-away hammer: net_expected == min_net  =>  h*(1+p)*(1+t) = resale*keep - min_net - fixed
    min_net = D(a["min_net_usd_for_yes"])
    walk = (agg["comp_price_expected"] * keep - min_net - fixed) / ((ONE + p) * (ONE + t))
    reasons = []
    ok = (len(sold) >= int(a["min_sold_comps_for_yes"]) and net["expected"] >= min_net and net["low"] >= ZERO
          and (pph is not None and pph >= D(a["min_profit_per_labor_hour_for_yes"])))
    if len(sold) < int(a["min_sold_comps_for_yes"]):
        reasons.append(f"{len(sold)} sold comps < {a['min_sold_comps_for_yes']} required"
                       + (f"; {len(asking)} asking-only comps do not count as sales" if asking else ""))
    if net["expected"] < min_net:
        reasons.append(f"expected net {net['expected']} below {min_net}")
    if net["low"] < ZERO:
        reasons.append("net is negative at the low sold comp")
    if pph is None or pph < D(a["min_profit_per_labor_hour_for_yes"]):
        reasons.append("profit per labor hour below threshold")
    if net["expected"] <= ZERO:
        verdict = "PASS"
    elif ok and not flags["slow_inventory"]:
        verdict = "YES"
    else:
        verdict = "MAYBE"
    if flags["slow_inventory"]:
        reasons.append(f"slow inventory: {inp['days_to_sell']} days to sell > {a['slow_inventory_days']}")
    out.update(computable=True, unknowns=[], cost={k: _o(v) for k, v in cost.items()},
               resale={"basis": "sold comps only", **{k: (v if k == "n_used" else _o(v)) for k, v in agg.items()}, "resale_fee_pct": _o(fee)},
               net={k: _o(v) for k, v in net.items()}, time_to_cash_hours=_o(ttc_h), capital_turns_per_30d=_o(turns_30d),
               profit_per_labor_hour=_o(pph), walk_away_hammer=_o(money(walk)) if walk > 0 else 0,
               flags=flags, verdict=verdict, reasons=reasons)
    return out


def _flags(ttc_h, days_to_sell, a) -> dict:
    lo, hi = (D(x) for x in a["fast_turn_hours"])
    return {"fast_24h": ttc_h is not None and ttc_h <= lo, "fast_48h": ttc_h is not None and ttc_h <= hi,
            "slow_inventory": days_to_sell is not None and days_to_sell > D(a["slow_inventory_days"])}
