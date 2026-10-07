"""MOCK — lane C (Economics, Agent 03). Output conforms to vendor/agent-03 scorecard + Item v1 scores.

A deliberately simple, fully transparent scorer so the end-to-end path has real numbers to show.
It is NOT Agent 03's engine and does not claim its formulas; thresholds are the provisional defaults in
MICHAEL_DECISIONS (#1 $800 max loss / $1,500 cash per deal, #2 $40 floor, $65 flip / $75 service target).
Decision is gates-first, then target: YES / MAYBE / PASS.
REPLACE WITH: Agent 03 engine on scoring-config.json 2026.10.0 (must pass AT-1..21, C22, C23).
"""
from __future__ import annotations

from ..core import sha256_ref

IMPLEMENTATION = "MOCK transparent scorer — stands in for Agent 03 (not its formulas)"
TOOL_NAME, TOOL_VERSION = "mbos_qa.mocks.economics", "0.1.0"
CONFIG_VERSION = "2026.10.0"
THRESHOLDS = {"pph_floor": 40.0, "pph_target": {"flip": 65.0, "service": 75.0}, "max_loss": 800.0,
              "max_cash": 1500.0, "min_confidence": 0.6, "min_profit": 100.0}
WEIGHTS = {  # copied from the contract worked examples (03 vectors) for reconstructability
    "flip": {"ev": 0.25, "pph": 0.25, "roi": 0.1, "ttc": 0.1, "risk": 0.1, "conf": 0.05, "skill": 0.1, "scarcity": 0.05},
    "service": {"ev": 0.2, "pph": 0.35, "roi": 0.0, "ttc": 0.1, "risk": 0.08, "conf": 0.07, "skill": 0.15, "scarcity": 0.05},
}
DEFAULT_VEHICLE = {"vehicle_mpg": 18.0, "fuel_price_per_gal": 3.2, "wear_per_mile": 0.28, "avg_speed_mph": 45.0}


def _clamp(x: float) -> float:
    return round(max(0.0, min(100.0, x)), 1)


def inputs_hash(economics: dict, research_prov_ids: list[str]) -> str:
    return sha256_ref({"economics": economics, "research_ids": sorted(research_prov_ids),
                       "scoring_config_version": economics["estimates_meta"]["scoring_config_version"]})


def score(item_type: str, economics: dict, *, n_comps: int, skills_on_file: set[str], scarcity: float,
          computed_at: str) -> dict:
    lg = {**DEFAULT_VEHICLE, **{k: v for k, v in economics["logistics"].items() if k != "trips"}}
    miles = sum(t["round_trip_miles"] for t in economics["logistics"]["trips"])
    per_mile = lg["fuel_price_per_gal"] / lg["vehicle_mpg"] + lg["wear_per_mile"]
    trips_cash = miles * per_mile
    travel_hours = miles / lg["avg_speed_mph"]
    reasons = ["MOCK SCORER (QA lane) — not Agent 03's engine; numbers illustrate the pipeline only"]

    if item_type == "flip":
        a, r, h, s, d = (economics[k] for k in ("acquisition", "rehab", "holding", "resale", "downside"))
        skills = set(r["required_skills"])
        total_hours = r["labor_hours"] + r.get("admin_hours", 0) + travel_hours
        cash = a["expected_buy_price"] + a.get("buy_fees", 0) + r["parts_cost"] + r["materials_cost"]
        cost_out = cash + h.get("storage_cost_per_day", 0) * h.get("expected_hold_days", 0) + trips_cash
        r_net = s["target_sell_price"] * (1 - h.get("sell_fees_rate", 0)) - h.get("sell_fees_flat", 0)
        p_rep, p_sale = r["repair_success_prob"], s["sale_prob"]
        ev = p_rep * (p_sale * r_net + (1 - p_sale) * d["salvage_if_unsold"]) + (1 - p_rep) * d["salvage_if_repair_fails"] - cost_out
        max_loss = cost_out - min(d["salvage_if_repair_fails"], d["salvage_if_unsold"])
        ttc = h.get("expected_hold_days", 0) + s.get("expected_dom_days", 0)
        conf = min(0.9, 0.5 + 0.1 * n_comps) * (1.0 if r.get("repair_scope_known") else 0.8)
        expected_hours = total_hours
    else:
        j = economics["job"]
        skills = set(j["required_skills"])
        first_trip = economics["logistics"]["trips"][0]["round_trip_miles"]
        total_hours = j["labor_hours"] + j.get("admin_hours", 0) + travel_hours
        cash = j.get("materials_cost", 0) * (1 - j.get("deposit_rate", 0))
        p_win, p_done = j["win_prob"], j.get("completion_prob", 1.0)
        ev = p_win * (j["quoted_revenue"] * p_done - j.get("materials_cost", 0) - trips_cash) - (1 - p_win) * first_trip * per_mile
        expected_hours = p_win * total_hours + (1 - p_win) * (first_trip / lg["avg_speed_mph"] + j.get("admin_hours", 0))
        max_loss = j.get("materials_cost", 0) + trips_cash
        ttc = j.get("payment_terms_days", 7)
        conf = min(0.9, 0.5 + 0.1 * n_comps + 0.2 * j.get("lead_quality", 0))
        r_net = j["quoted_revenue"]
        cost_out = j.get("materials_cost", 0) + trips_cash

    pph = ev / expected_hours if expected_hours else 0.0
    roi = ev / cash if cash else 0.0
    target = THRESHOLDS["pph_target"][item_type]
    gates = {
        "ev_positive": ev > 0, "max_loss_ok": max_loss <= THRESHOLDS["max_loss"],
        "cash_ok": cash <= THRESHOLDS["max_cash"], "skill_ok": skills <= skills_on_file,
        "pph_floor_ok": pph >= THRESHOLDS["pph_floor"], "min_profit_ok": ev >= THRESHOLDS["min_profit"],
    }
    if not all(gates.values()):
        decision = "PASS"
        reasons.append("Gate(s) failed: " + ", ".join(k for k, v in gates.items() if not v))
    elif pph >= target and conf >= THRESHOLDS["min_confidence"]:
        decision = "YES"
        reasons.append(f"EV profit/hour {pph:.1f} >= {target:.0f} {item_type} target; confidence {conf:.2f} >= 0.60")
    else:
        decision = "MAYBE"
        reasons.append(f"Gates pass but EV profit/hour {pph:.1f} < {target:.0f} or confidence {conf:.2f} < 0.60")
    reasons.append(f"EV net ${ev:,.0f}; max loss ${max_loss:,.0f}; cash tied up ${cash:,.0f}; {miles:.0f} road miles")

    sub = {"ev_score": _clamp(ev / 10), "pph_score": _clamp(pph / target * 60), "roi_score": _clamp(roi * 100),
           "ttc_score": _clamp(100 - 2 * ttc), "risk_score": _clamp(100 - max_loss / 10), "conf_score": _clamp(conf * 100),
           "skill_score": 90.0 if gates["skill_ok"] else 0.0, "scarcity_score": _clamp(scarcity * 100)}
    w = WEIGHTS[item_type]
    composite = round(sum(sub[f"{k}_score"] * v for k, v in w.items()), 1)
    r2 = lambda x: round(x, 2)  # noqa: E731
    return {
        "scoring_config_version": CONFIG_VERSION, "computed_at": computed_at,
        "derived": {"trips_cash": r2(trips_cash), "travel_hours": r2(travel_hours), "total_hours": r2(total_hours),
                    "cost_out": r2(cost_out), "r_net": r2(r_net), "cash_tied_up": r2(cash), "ev_net_profit": r2(ev),
                    "ev_profit_per_hour": r2(pph), "ev_roi": r2(roi), "max_loss": r2(max_loss),
                    "time_to_cash_days": r2(ttc), "confidence": r2(conf),
                    "skill_fit": 1.0 if gates["skill_ok"] else 0.0, "scarcity": scarcity},
        "sub_scores": sub, "weights_used": w, "composite": composite, "decision": decision, "alert": False,
        "gates": gates, "reasons": reasons,
    }


def scorer_provenance(pid: str, created_at: str, derived_from: list[str], ihash: str) -> dict:
    return {"provenance_id": pid, "created_at": created_at, "actor_type": "agent", "agent_name": "agent-03-economics",
            "basis": "INFERENCE", "tool_name": TOOL_NAME, "tool_version": TOOL_VERSION, "config_version": CONFIG_VERSION,
            "derived_from": derived_from, "inputs_used": [{"ref": "scores.inputs_hash", "hash": ihash}]}
