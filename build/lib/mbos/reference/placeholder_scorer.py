"""PLACEHOLDER scorer — owner: Lane C Economics (Agent 03). NOT Agent 03's engine.

It exists so the spine can route YES / MAYBE / PASS end to end. The arithmetic is a
simplified reading of 03's gates-first design; the thresholds are the provisional defaults
recorded in agent-01-integration.md §11 (MICHAEL_DECISIONS #1/#2 are undecided):
$40/h floor, $65/h flip target, $75/h service target, $1,500 cash cap, $800 max loss.

Replay contract (AT-1 / C22): output depends only on the Item's economics, research ids and
the config version, and `inputs_hash` covers exactly those.
"""

from __future__ import annotations

from typing import Any

from mbos import __version__
from mbos.hashing import sha256_of
from mbos.interfaces import ScoreResult

CONFIG_VERSION = "2026.10.0"
TOOL = "mbos.reference.placeholder_scorer"
FLOOR_PPH = 40.0
TARGET_PPH = {"flip": 65.0, "service": 75.0}
CASH_CAP = 1500.0
MAX_LOSS_CAP = 800.0
MIN_CONFIDENCE = 0.6
WEIGHTS = {"ev": 0.25, "pph": 0.25, "roi": 0.1, "ttc": 0.1, "risk": 0.1, "conf": 0.05, "skill": 0.1, "scarcity": 0.05}


def _clamp(x: float) -> float:
    return round(max(0.0, min(100.0, x)), 1)


def inputs_hash(item: dict[str, Any]) -> str:
    return sha256_of({
        "economics": item.get("economics"),
        "research_ids": sorted(r["provenance_id"] for r in item.get("research") or []),
        "scoring_config_version": CONFIG_VERSION,
    })


def _travel(logistics: dict[str, Any]) -> tuple[float, float, float]:
    miles = sum(float(t.get("round_trip_miles", 0)) for t in logistics.get("trips", []))
    per_mile = float(logistics.get("fuel_price_per_gal", 3.2)) / float(logistics.get("vehicle_mpg", 18)) \
        + float(logistics.get("wear_per_mile", 0.28))
    return miles, round(miles * per_mile, 2), round(miles / float(logistics.get("avg_speed_mph", 45)), 2)


def _flip(e: dict[str, Any]) -> tuple[dict, dict, list[str], float]:
    acq, rehab, hold, resale, down = e["acquisition"], e["rehab"], e.get("holding", {}), e["resale"], e["downside"]
    miles, trips_cash, travel_h = _travel(e["logistics"])
    buy = float(acq["expected_buy_price"]) + float(acq.get("buy_fees", 0))
    cash = buy + float(rehab["parts_cost"]) + float(rehab["materials_cost"])
    cost_out = cash + trips_cash + float(hold.get("storage_cost_per_day", 0)) * float(hold.get("expected_hold_days", 0)) \
        + float(hold.get("disposal_cost", 0))
    r_net = float(resale["target_sell_price"]) * (1 - float(hold.get("sell_fees_rate", 0))) - float(hold.get("sell_fees_flat", 0))
    hours = float(rehab["labor_hours"]) + float(rehab.get("admin_hours", 0)) + travel_h
    rp, sp = float(rehab["repair_success_prob"]), float(resale["sale_prob"])
    ev_rev = rp * sp * r_net + rp * (1 - sp) * float(down["salvage_if_unsold"]) + (1 - rp) * float(down["salvage_if_repair_fails"])
    ev_net = ev_rev - cost_out
    max_loss = cost_out - min(float(down["salvage_if_repair_fails"]), float(down["salvage_if_unsold"]))
    confidence = round((0.75 if resale.get("comp_price_expected") else 0.45) * (1.0 if rehab.get("repair_scope_known") else 0.8), 2)
    derived = {
        "trips_cash": trips_cash, "travel_hours": travel_h, "total_hours": round(hours, 2), "cost_out": round(cost_out, 2),
        "r_net": round(r_net, 2), "net_profit_deterministic": round(r_net - cost_out, 2),
        "ev_net_profit": round(ev_net, 2), "ev_profit_per_hour": round(ev_net / hours, 2) if hours else 0.0,
        "cash_tied_up": round(cash, 2), "max_loss": round(max(max_loss, 0.0), 2),
        "ev_roi": round(ev_net / cash, 3) if cash else 0.0,
        "time_to_cash_days": float(hold.get("expected_hold_days", resale.get("expected_dom_days", 30))),
        "confidence": confidence,
    }
    reasons = [f"EV net ${derived['ev_net_profit']:.0f} over {derived['total_hours']:.1f} h "
               f"→ ${derived['ev_profit_per_hour']:.0f}/h (flip target ${TARGET_PPH['flip']:.0f}/h)"]
    return derived, {"cash_ok": cash <= CASH_CAP}, reasons, confidence


def _service(e: dict[str, Any]) -> tuple[dict, dict, list[str], float]:
    job = e["job"]
    miles, trips_cash, travel_h = _travel(e["logistics"])
    revenue = float(job["quoted_revenue"])
    cost_out = float(job.get("materials_cost", 0)) + trips_cash
    hours = float(job["labor_hours"]) + float(job.get("admin_hours", 0)) + travel_h
    win, done = float(job["win_prob"]), float(job.get("completion_prob", 1.0))
    net = revenue * done - cost_out
    ev_net = win * net
    confidence = round(float(job.get("lead_quality", 0.5)), 2)
    derived = {
        "trips_cash": trips_cash, "travel_hours": travel_h, "total_hours": round(hours, 2), "cost_out": round(cost_out, 2),
        "net_profit_deterministic": round(revenue - cost_out, 2), "ev_net_profit": round(ev_net, 2),
        "profit_per_hour_deterministic": round(net / hours, 2) if hours else 0.0,
        "ev_profit_per_hour": round(net / hours, 2) if hours else 0.0,  # conditional on winning the job
        "cash_tied_up": round(float(job.get("materials_cost", 0)), 2), "max_loss": round(trips_cash, 2),
        "time_to_cash_days": float(job.get("payment_terms_days", 0)), "confidence": confidence,
    }
    reasons = [f"If won: ${derived['net_profit_deterministic']:.0f} net over {derived['total_hours']:.1f} h "
               f"→ ${derived['ev_profit_per_hour']:.0f}/h (service target ${TARGET_PPH['service']:.0f}/h); win prob {win:.2f}"]
    return derived, {"cash_ok": True}, reasons, confidence


class PlaceholderScorer:
    def score(self, item: dict[str, Any]) -> ScoreResult:
        h = inputs_hash(item)
        e = item.get("economics")
        if not e:
            card = {"scoring_config_version": CONFIG_VERSION, "derived": {}, "sub_scores": {}, "composite": 0,
                    "decision": "MAYBE", "gates": {}, "reasons": ["No economics inputs yet; cannot score"],
                    "cheapest_decisive_evidence": "Comparable sold prices and repair/job scope"}
            return ScoreResult(scorecard=card, inputs_hash=h, verdict="MAYBE", rationale=card["reasons"], confidence=0.0,
                               scoring_config_version=CONFIG_VERSION, tool_name=TOOL, tool_version=__version__,
                               cheapest_decisive_evidence=card["cheapest_decisive_evidence"])
        derived, gates, reasons, conf = (_flip if item["type"] == "flip" else _service)(e)
        pph, ev = derived["ev_profit_per_hour"], derived["ev_net_profit"]
        gates = {"ev_positive": ev > 0, "max_loss_ok": derived["max_loss"] <= MAX_LOSS_CAP, **gates,
                 "pph_floor_ok": pph >= FLOOR_PPH}
        target = TARGET_PPH[item["type"]]
        sub = {"ev_score": _clamp(ev / 10), "pph_score": _clamp(pph / target * 60), "roi_score": _clamp(derived.get("ev_roi", 0.3) * 100),
               "ttc_score": _clamp(100 - derived["time_to_cash_days"] * 2), "risk_score": _clamp(100 - derived["max_loss"] / 10),
               "conf_score": _clamp(conf * 100), "skill_score": 90.0, "scarcity_score": 50.0}
        composite = round(sum(WEIGHTS[k.removesuffix("_score")] * v for k, v in sub.items()), 1)
        if not all(gates.values()):
            verdict = "PASS"
            reasons.append("Hard gate failed: " + ", ".join(k for k, v in gates.items() if not v))
        elif pph >= target and conf >= MIN_CONFIDENCE:
            verdict = "YES"
            reasons.append(f"All gates pass; ${pph:.0f}/h ≥ ${target:.0f}/h target; confidence {conf:.2f} ≥ {MIN_CONFIDENCE}")
        else:
            verdict = "MAYBE"
            reasons.append(f"Gates pass but ${pph:.0f}/h < ${target:.0f}/h target or confidence {conf:.2f} < {MIN_CONFIDENCE}")
        reasons.append("PLACEHOLDER scorer (lane C replaces); thresholds are provisional MICHAEL_DECISIONS #1/#2 defaults")
        card = {"scoring_config_version": CONFIG_VERSION, "derived": derived, "sub_scores": sub, "weights_used": WEIGHTS,
                "composite": composite, "decision": verdict, "alert": False, "gates": gates, "reasons": reasons}
        evidence = None
        if verdict == "MAYBE":
            evidence = "Photos of the work area" if item["type"] == "service" else "Sold comps and a condition check"
            card["cheapest_decisive_evidence"] = evidence
        return ScoreResult(scorecard=card, inputs_hash=h, verdict=verdict, rationale=reasons, confidence=conf,
                           scoring_config_version=CONFIG_VERSION, tool_name=TOOL, tool_version=__version__,
                           cheapest_decisive_evidence=evidence)
