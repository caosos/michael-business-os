"""C-33: trailer / donor chassis / machine valuation on top of the C-32 auction cost model.

Value paths (the best expected net is the headline; both are shown):
- ``parts_out``: sum of named components (frame, axles, springs, hubs, running gear, steel, pump, cylinder, ...).
  Only parts with ``basis`` sold or scrap are the FLOOR; ``estimate`` parts count at a haircut in the expected case.
- ``resale``: sold comps (or an owner resale target) less repair cost; used for machines and towables.
A donor chassis is valued by parts only: camping comps are never used. A missing or dead engine is a repair cost
or a parts-out case, not an automatic PASS. Untitled trailers (bill_of_sale / no_title / salvage) carry title path,
cost and delay, show as-is vs resolved resale, never assume legal transfer, and are never YES until title is in hand.
Asking prices never count as sales. Owner resale target overrides the system estimate; both are shown with provenance.
Pure, deterministic, DRY-RUN. Config: ``config/asset-deal-model.json``.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .auction import _flags, _num, _o, all_in_cost, load_auction_config, split_comps
from .comps import aggregate_sold_comps
from .config import ScoringConfig, load_config
from .numeric import D, ONE, ZERO, fine, money

ASSET_VERSION = "1.0.0"
ASSET_CONFIG = Path(__file__).resolve().parent / "config" / "asset-deal-model.json"
_REQUIRED = ("hammer_price", "buyer_premium_pct", "sales_tax_rate", "pickup_cost", "transport_cost",
             "labor_hours", "days_to_sell", "pickup_wait_hours")
_CLASSES = ("donor_chassis", "component_machine", "towable")
_UNTITLED = ("bill_of_sale", "no_title", "salvage")
_TITLED = ("titled",)


def load_asset_config(path: Path = ASSET_CONFIG) -> dict:
    raw = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal, parse_int=Decimal)
    return {k: (v["value"] if isinstance(v, dict) and "value" in v else v) for k, v in raw.items()}


def forecast_bid(current_bid, bid_count, hours_left, f: dict) -> dict:
    """FORECAST of the final hammer from current bid, bid count and time left. Heuristic; never an observation."""
    cb, n, hl = D(current_bid), D(bid_count), D(hours_left)
    uplift = (D(f["time_coeff"]) * min(hl, D(f["horizon_hours"])) / D(f["horizon_hours"])
              * (ONE + D(f["bid_coeff"]) * min(n, D(f["bid_cap"]))))
    return {"label": "FORECAST (heuristic, REC; not observed)", "current_bid": _o(money(cb)), "bid_count": _o(n),
            "hours_left": _o(hl), "uplift_pct": _o(fine(uplift)),
            "final_hammer": {"low": _o(money(cb)), "expected": _o(money(cb * (ONE + uplift))),
                             "high": _o(money(cb * (ONE + 2 * uplift)))}}


def _parts(parts, haircut):
    floor = sum((D(p["value"]) for p in parts if p.get("basis") in ("sold", "scrap")), ZERO)
    est = sum((D(p["value"]) for p in parts if p.get("basis") not in ("sold", "scrap")), ZERO)
    return floor, floor + est * haircut, floor + est


def evaluate(inp: dict, cfg: ScoringConfig | None = None, acfg: dict | None = None, kcfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    a = acfg or load_auction_config()
    k = kcfg or load_asset_config()
    cls = inp.get("asset_class")
    pw = inp.get("paperwork") or {}
    pclass = pw.get("class")
    rep = inp.get("repair") or {}
    parts = inp.get("parts") or []
    own = inp.get("owner_resale_target")
    missing = [f"asset:{x}" for x in _REQUIRED if not _num(inp.get(x))]
    if cls not in _CLASSES:
        missing.append("asset:asset_class")
    if cls in ("donor_chassis", "towable") and pclass not in _UNTITLED + _TITLED:
        missing.append("paperwork:class")
    if pclass in _UNTITLED and not (pw.get("title_path") and _num(pw.get("title_cost")) and _num(pw.get("title_delay_days"))):
        missing += [x for x, ok in (("paperwork:title_path", pw.get("title_path")), ("paperwork:title_cost", _num(pw.get("title_cost"))),
                                    ("paperwork:title_delay_days", _num(pw.get("title_delay_days")))) if not ok]
    if rep and not rep.get("skills_cover_repair") and not _num(rep.get("shop_cost")):
        missing.append("repair:shop_cost")
    sold, asking = split_comps(inp.get("comps") or [])
    agg = aggregate_sold_comps(sold, cfg) if cls != "donor_chassis" else None
    own_v = D(own["value"]) if isinstance(own, dict) and _num(own.get("value")) else None
    if own is not None and (own_v is None or not own.get("source")):
        missing.append("owner_resale_target:value_and_source")
    floor, parts_exp, parts_high = _parts(parts, D(k["estimate_haircut"]))
    if cls == "donor_chassis" and not parts:
        missing.append("asset:parts")
    elif cls == "component_machine" and agg is None and own_v is None and not parts:
        missing.append("asset:sold_comps_or_parts")
    elif cls == "towable" and agg is None and own_v is None and not parts:
        missing.append("asset:sold_comps_or_parts")
    out = {"asset_deal_model_version": k["asset_deal_model_version"], "module_version": ASSET_VERSION, "item_id": inp.get("item_id"),
           "asset_class": cls, "dry_run": True,
           "evidence": {"sold_comps_used": agg["n_used"] if agg else 0, "sold_comps_count": len(sold), "asking_comps_count": len(asking),
                        "asking_counted_as_sold": False, "camping_value_used": False}}
    if missing:
        out.update(computable=False, verdict="HOLD", unknowns=sorted(set(missing)), reasons=["missing inputs: " + ", ".join(sorted(set(missing)))])
        return out
    h, p, t = D(inp["hammer_price"]), D(inp["buyer_premium_pct"]), D(inp["sales_tax_rate"])
    fixed = D(inp["pickup_cost"]) + D(inp["transport_cost"]) + D(inp.get("other_fixed_cost", 0))
    cost = all_in_cost(h, p, t, fixed)
    covers = bool(rep.get("skills_cover_repair"))
    repair_cost = D(rep.get("parts_cost", 0)) + (ZERO if covers else D(rep.get("shop_cost", 0)))
    repair_hours = D(rep.get("michael_hours", 0)) if covers else ZERO
    teardown = D(inp.get("teardown_cost", 0))
    title_cost = D(pw.get("title_cost", 0)) if pclass in _UNTITLED else ZERO
    title_delay = D(pw.get("title_delay_days", 0)) if pclass in _UNTITLED else ZERO
    fee = D(inp.get("resale_fee_pct", 0))
    keep = ONE - fee
    cap = D(k["cash_cap_per_buy"])
    resolved_cost = cost["all_in"] + repair_cost + title_cost
    as_is_cost = cost["all_in"] + repair_cost
    hours = D(inp["labor_hours"]) + repair_hours + D(inp.get("teardown_hours", 0))
    days_base = (D(inp["pickup_wait_hours"]) / 24 + D(inp["days_to_sell"]) + D(rep.get("repair_days", 0))
                 + D(inp.get("payout_lag_days", a["payout_lag_days"])))

    # resale basis: owner target overrides the system estimate; both are shown
    system = agg["comp_price_expected"] if agg else None
    resale = {"system_estimate": _o(system), "owner_target": _o(own_v), "used": "owner" if own_v is not None else ("system" if system is not None else None)}
    if own_v is not None:
        resale["owner_provenance"] = {"source": own["source"], "note": own.get("note"), "basis": "HUMAN-ATTESTED"}
    base = own_v if own_v is not None else system
    paths = {}
    if parts:
        paths["parts_out"] = {"floor": floor, "expected": parts_exp, "high": parts_high, "value_scale": ONE}
    if base is not None:
        low = agg["comp_price_low"] if agg and own_v is None else base
        high = agg["comp_price_high"] if agg and own_v is None else base
        paths["resale"] = {"floor": low, "expected": base, "high": high}
    asis_f = D(pw.get("as_is_resale_factor", k["as_is_resale_factor"])) if pclass in _UNTITLED else ONE
    rows = {}
    for name, v in paths.items():
        f = asis_f if name == "resale" else ONE
        rows[name] = {"value_expected_resolved": _o(money(v["expected"])), "value_expected_as_is": _o(money(v["expected"] * f)),
                      "net_resolved": {x: _o(money(v[x] * keep - resolved_cost - teardown)) for x in ("floor", "expected", "high")},
                      "net_as_is": {x: _o(money(v[x] * f * keep - as_is_cost - teardown)) for x in ("floor", "expected", "high")}}
    # headline: conservative (as-is) for untitled; best expected path
    key = "net_as_is" if pclass in _UNTITLED else "net_resolved"
    best = max(rows, key=lambda n: (rows[n][key]["expected"], n))
    net = {x: D(rows[best][key][x]) for x in ("floor", "expected", "high")}
    days_resolved = days_base + title_delay
    pd_days = fine(days_base)
    ppd = fine(net["expected"] / pd_days) if pd_days > 0 else None
    pph = fine(net["expected"] / hours) if hours > 0 else None
    invested = as_is_cost + teardown if pclass in _UNTITLED else resolved_cost + teardown
    recover = floor * keep if parts else ZERO
    at_risk = max(ZERO, invested - recover)
    flags = _flags(pd_days * 24, D(inp["days_to_sell"]), a)
    # max bid: walk-away at min net, and the $500 cap
    min_net = D(a["min_net_usd_for_yes"])
    v_exp = paths[best]["expected"] * (asis_f if best == "resale" else ONE)
    extras = fixed + repair_cost + teardown + (ZERO if pclass in _UNTITLED else title_cost)
    div = (ONE + p) * (ONE + t)
    walk = (v_exp * keep - min_net - extras) / div
    capb = (cap - extras) / div
    max_bid = max(ZERO, min(walk, capb))
    mb = {"max_bid": _o(money(max_bid)), "binding": "cash_cap" if capb < walk else "min_net",
          "assumptions": [f"path={best}", f"value basis={'owner target' if own_v is not None and best == 'resale' else 'sold/parts evidence'}",
                          f"expected value {_o(money(v_exp))} ({'as-is' if pclass in _UNTITLED and best == 'resale' else 'resolved'}) after {_o(fee)} resale fee",
                          f"buyer premium {_o(p)}, tax {_o(t)} on hammer+premium", f"fixed+repair+teardown+title extras {_o(money(extras))}",
                          f"min net {_o(min_net)}, cash cap {_o(cap)}"]}
    over_cap = invested > cap
    reasons = []
    ev_ok = (best == "parts_out" and floor > ZERO and rows[best]["net_resolved"]["floor"] >= 0 and net["floor"] >= 0) or \
            (best == "resale" and len(sold) >= int(a["min_sold_comps_for_yes"]) and own_v is None and net["floor"] >= 0)
    if best == "resale" and own_v is not None:
        reasons.append("owner resale target overrides the system estimate; human-attested, not market evidence, so not YES")
    if best == "resale" and len(sold) < int(a["min_sold_comps_for_yes"]):
        reasons.append(f"{len(sold)} sold comps < {a['min_sold_comps_for_yes']} required" + (f"; {len(asking)} asking-only comps do not count" if asking else ""))
    if pclass in _UNTITLED:
        reasons.append(f"{pclass}: legal transfer not assumed; no YES until title is in hand (path: {pw['title_path']}, {title_delay} days, cost {_o(title_cost)})")
    if over_cap:
        reasons.append(f"cash needed {_o(money(invested))} exceeds cap {_o(cap)}")
    if net["expected"] < min_net:
        reasons.append(f"expected net {_o(money(net['expected']))} below {_o(min_net)}")
    if pph is None or pph < D(a["min_profit_per_labor_hour_for_yes"]):
        reasons.append("profit per labor hour below threshold")
    if flags["slow_inventory"]:
        reasons.append(f"slow inventory: {inp['days_to_sell']} days to sell > {a['slow_inventory_days']}")
    if net["expected"] <= ZERO:
        verdict = "PASS"
    elif (ev_ok and net["expected"] >= min_net and pph is not None and pph >= D(a["min_profit_per_labor_hour_for_yes"])
          and pclass not in _UNTITLED and not over_cap and not flags["slow_inventory"]):
        verdict = "YES"
    else:
        verdict = "MAYBE"
    out.update(computable=True, unknowns=[], cost={x: _o(v) for x, v in cost.items()},
               extras={"repair_cost": _o(money(repair_cost)), "repair_hours_michael": _o(repair_hours), "teardown_cost": _o(money(teardown)),
                       "title_cost": _o(money(title_cost))},
               resale=resale, paths=rows, headline_path=best, headline_basis="as_is" if pclass in _UNTITLED else "resolved",
               paperwork={"class": pclass, "legal_transfer_assumed": False, "title_path": pw.get("title_path"), "title_delay_days": _o(title_delay),
                          "days_to_cash_resolved": _o(fine(days_resolved)), "net_resolved_expected": rows[best]["net_resolved"]["expected"],
                          "net_as_is_expected": rows[best]["net_as_is"]["expected"]} if pclass else None,
               net={x: _o(money(v)) for x, v in net.items()}, profit_per_day=_o(ppd), profit_per_labor_hour=_o(pph),
               days_to_cash=_o(pd_days), capital_tied_up=_o(money(invested)), capital_at_risk=_o(money(at_risk)),
               cash_cap={"cap": _o(cap), "over_cap": over_cap}, suggested_max_bid=mb, flags=flags, verdict=verdict, reasons=reasons)
    if all(_num(inp.get(x)) for x in ("current_bid", "bid_count", "hours_left")):
        fc = forecast_bid(inp["current_bid"], inp["bid_count"], inp["hours_left"], k["forecast"])
        fc["likely_exceeds_max_bid"] = D(fc["final_hammer"]["expected"]) > max_bid
        out["bid_forecast"] = fc
    return out
