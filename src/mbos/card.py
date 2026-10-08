"""Deal Sniffer opportunity card (ADR-0011): the decision-ready view of one Item.

A PURE, deterministic projection of (Item, its receipts, its action requests, lane-supplied enrichment blocks).
It stores nothing and grants no authority: Michael's decision is still Approval.decision on an ActionRequest.

Honesty rule (enforced by tests): every datum is a value with a basis, or the literal UNKNOWN. This module never
fabricates seller data, dates, ranges, seasonality or model-specific advice. Lanes supply enrichment; if a lane
did not, the card says UNKNOWN and lists the path in `unknowns`.

Enrichment blocks (all optional; each datum may carry `provenance_id`):
    listing_activity  lane B (02)    posted_at, updated_at, recent_activity[], suspected_relist, stale_risk
    seller            lane B (02)    account_age, rating, prior_listings, complaint_signals, response_history,
                                     inconsistencies, confidence
    economics         lane C (03)    opening_offer, max_acquisition, resale_{conservative,likely,optimistic},
                                     transport_cost, days_to_cash ... (ranges)
    value_add         lane C (03)    plan, model_specific_risks[]
    seasonality       lane C (03)    demand_now, hold_likely, peak_months[], note
    logistics         lane C (03)    transport_mode, trip_miles_round_trip, trip_hours, fuel_cost, difficulty
    make_model        lane B (02)
    distance_miles    lane B (02)
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from mbos.clock import iso, parse, utcnow
from mbos.contracts import schemas
from mbos.hashing import sha256_of

CARD_VERSION = "1.0.0"
UNKNOWN: dict[str, Any] = {"value": "UNKNOWN"}

STAGES = ("DISCOVERED", "RESEARCHED", "SCORED", "CONTACT APPROVED", "CONTACT SENT", "SELLER RESPONDED", "NEGOTIATING",
          "QUALIFIED", "AWAITING MICHAEL", "CLOSED", "PASSED")

# Elementary mechanical advice Michael does not want (he is an experienced mechanic). Allowed only when the lane marks the
# entry model-specific with a source.
_VERB = r"(?:check|test|inspect|verify|confirm|see if|make sure|try|look (?:for|at)|pull|do an?|run an?)"
_BASIC = (r"compression|spark|fuel|oil|starts?|starting|runs?|running|turns? over|battery|belts?|hoses?|leaks?|filters?|"
          r"plugs?|carb(?:uretor|urator)?s?|idle|choke|coolant|fluids?|tires?|brakes?|(?:any )?damage|wear|cracks?")
ELEMENTARY_ADVICE = [re.compile(p, re.I) for p in (
    rf"\b{_VERB}\b[^.;\n]{{0,30}}\b(?:{_BASIC})\b(?!\s+(?:pump|housing|module|coupler|gasket|regulator|solenoid)\b)",
    r"\bcompression (?:test|check)\b", r"\bsee if it (?:starts|runs)\b", r"\bpull the (?:spark )?plug\b",
)]


def elementary_advice(text: str) -> list[str]:
    """Phrases in `text` that are elementary for an experienced mechanic (empty list = fine)."""
    return [m.group(0) for rx in ELEMENTARY_ADVICE for m in [rx.search(text or "")] if m]


def load_profile(path: Optional[str | Path] = None) -> dict[str, Any]:
    import os

    if path is None:
        env = os.environ.get("MBOS_OPERATOR_PROFILE")
        candidates = [Path(env)] if env else [Path(__file__).resolve().parents[2] / "config" / "operator_profile.v1.json",
                                              Path(__file__).resolve().parent / "_data" / "config" / "operator_profile.v1.json"]
        found = next((c for c in candidates if c.exists()), None)
        if found is None:  # never guess Michael's capabilities
            raise FileNotFoundError("operator_profile.v1.json not found; set MBOS_OPERATOR_PROFILE")
        path = found
    return json.loads(Path(path).read_text())


# ---------------------------------------------------------------- lane-data validation (F-26/F-27/F-28)
_PROV_RX = re.compile(r"^prov_[0-9A-HJKMNP-TV-Z]{26}$")
_BASES = ("FACT", "INFERENCE", "RECOMMENDATION")
ENUMS = {"stale_risk": ("low", "medium", "high"), "demand_now": ("strong", "normal", "weak"),
         "transport_mode": ("fits_truck", "requires_trailer"), "difficulty": ("easy", "moderate", "hard")}
# datum keys whose value MUST be a finite number (money / counts / hours / miles), and the non-negative subset
NUMERIC = {"asking_price", "opening_offer", "max_acquisition", "transport_cost", "resale_conservative", "resale_likely",
           "resale_optimistic", "days_to_cash", "age_days", "trip_miles_round_trip", "trip_hours", "fuel_cost", "distance_miles",
           "rating", "prior_listings"}
NONNEG = NUMERIC - {"rating"}
JUNK_SOURCES = {"", "n/a", "na", "none", "null", "unknown", "source", "x", "xx", "tbd", "todo", "n.a.", "-", "?", "trust me", "internet", "google", "web"}


def _finite(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and x not in (float("inf"), float("-inf"))


_MAX_MAG = 1e12
_MIN_CASH, _MIN_DAYS = 0.01, 1 / 1440   # one cent, one minute: below these a "multiple" or "velocity" is arithmetic noise (F-53)
_NUMSTR = re.compile(r"^\s*[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?\s*$|^\s*[-+]?(nan|inf(inity)?)\s*$", re.I)


def _sane(obj: Any) -> Any:
    """F-52: lane data is untrusted. NaN/Infinity and numeric STRINGS ("12", "nan") become None (= UNKNOWN downstream) instead of
    crashing arithmetic or leaking into the card as numbers."""
    if isinstance(obj, (int, float)) and not isinstance(obj, bool) and (not _finite(obj) or abs(obj) > _MAX_MAG):
        return None   # NaN/Infinity, and magnitudes beyond I-JSON-safe money/time (1e308 crashed the canonical encoder: F-52)
    if isinstance(obj, str) and _NUMSTR.match(obj):
        return None
    if isinstance(obj, dict):
        return {k: _sane(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sane(v) for v in obj]
    return obj


def _blk(src: Any, key: str) -> dict:
    """A lane block, or {} if absent / not an object. A bad block must never take the card down."""
    v = src.get(key) if isinstance(src, dict) else None
    return v if isinstance(v, dict) else {}


def _strs(v: Any, limit: int = 20, size: int = 300) -> list[str]:
    return [x[:size] for x in v if isinstance(x, str) and x.strip()][:limit] if isinstance(v, list) else []


def _valid_datum(key: str, d: Any) -> bool:
    if not isinstance(d, dict) or d.get("basis") not in _BASES or "value" not in d:
        return False
    v = d["value"]
    if v is None or v == "UNKNOWN" or isinstance(v, str) and not v.strip():
        return False
    if not isinstance(v, (int, float, str, bool, list, dict)):
        return False
    if isinstance(v, float) and not _finite(v):
        return False
    if key in NUMERIC and not _finite(v):
        return False
    if key in NONNEG and v < 0:
        return False
    if key in ENUMS and v not in ENUMS[key]:
        return False
    for k in ("unit", "note"):
        if k in d and not isinstance(d[k], str):
            return False
    lo, hi = d.get("low"), d.get("high")
    for b in (lo, hi):
        if b is not None and not _finite(b):
            return False
    if lo is not None and hi is not None and lo > hi:
        return False
    if "provenance_id" in d and not (isinstance(d["provenance_id"], str) and _PROV_RX.match(d["provenance_id"])):
        return False
    return True


# ---------------------------------------------------------------- text safety (F-35/F-36)
_CTRL = re.compile(r"[\x00-\x1f\x7f-\x9f\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")


def clean_text(s: Any, limit: int = 300) -> str:
    """Untrusted listing/lane text → one safe line: no control characters, ANSI escapes, bidi overrides, zero-width
    characters or newlines (so it cannot forge card sections or drive the terminal)."""
    t = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?|\x1b.", " ", str(s))
    t = _CTRL.sub(" ", t)
    return re.sub(r" {2,}", " ", t).strip()[:limit]


def scrub(obj: Any) -> tuple[Any, bool]:
    """Remove NUL / control characters from every string in a JSON-like structure. Returns (clean, changed)."""
    changed = False

    def go(o: Any) -> Any:
        nonlocal changed
        if isinstance(o, str):
            t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", o)
            changed |= t != o
            return t
        if isinstance(o, dict):
            return {go(k) if isinstance(k, str) else k: go(v) for k, v in o.items()}
        if isinstance(o, list):
            return [go(v) for v in o]
        return o

    return go(obj), changed


# ---------------------------------------------------------------- datum helpers
def _unknown(reason: str = "") -> dict[str, Any]:
    return {"value": "UNKNOWN", **({"reason": reason} if reason else {})}


def _datum(value: Any, basis: str, *, unit: Optional[str] = None, low: Optional[float] = None, high: Optional[float] = None,
           provenance_id: Optional[str] = None, note: Optional[str] = None) -> dict[str, Any]:
    d: dict[str, Any] = {"value": value, "basis": basis}
    for k, v in (("unit", unit), ("low", low), ("high", high), ("provenance_id", provenance_id), ("note", note)):
        if v is not None:
            d[k] = v
    return d


def _from_block(block: Optional[dict], key: str, reason: str) -> dict[str, Any]:
    """Take a lane-supplied datum verbatim ONLY if it validates (shape AND value), else UNKNOWN. Never invent."""
    v = block.get(key) if isinstance(block, dict) else None
    if _valid_datum(key, v):
        out = {k: val for k, val in v.items() if k in ("value", "unit", "low", "high", "basis", "provenance_id", "note")}
        if isinstance(out["value"], str):
            out["value"] = clean_text(out["value"], 500)
        return out
    return _unknown(reason)


def _is_unknown(d: dict) -> bool:
    return d.get("value") == "UNKNOWN"


# ---------------------------------------------------------------- status timeline
CLOSING_OUTCOMES = {"flip_sold", "flip_unsold_salvaged", "flip_repair_failed", "flip_passed_missed", "service_lost",
                    "service_completed", "service_paid", "wasted_trip"}


def _decision_of(r: dict) -> Optional[str]:
    """Michael's decision from an APPROVAL_DECIDED receipt: after_state when present, else the intent text both
    backends write ("Michael decided YES")."""
    d = (r.get("after_state") or {}).get("decision")
    if d in ("YES", "NO", "MODIFY", "HOLD"):
        return d
    m = re.search(r"decided (YES|NO|MODIFY|HOLD)\b", r.get("intent", ""))
    return m.group(1) if m else None


def _outcome_kind(r: dict) -> Optional[str]:
    k = (r.get("after_state") or {}).get("kind")
    if isinstance(k, str):
        return k
    m = re.search(r"outcome ([a-z_]+)", r.get("intent", ""))
    return m.group(1) if m else None


def _stage_events(item: dict, receipts: list[dict], areqs: list[dict]) -> list[tuple[str, dict]]:
    """(stage, receipt) for every stage that has an event source. Stages without one (NEGOTIATING, QUALIFIED until
    inbound comms exist) are never invented. An outcome closes the card only if its kind is a closing one."""
    comms_areq = {a["action_request_id"] for a in areqs if str(a.get("capability", "")).startswith("comms.")}
    ev: list[tuple[str, dict]] = []
    for r in sorted(receipts, key=lambda x: x["seq"]):
        t, after = r["type"], r.get("after_state") or {}
        if t == "ITEM_STATE_CHANGED":
            st = after.get("state")
            if st == "DISCOVERED":
                ev.append(("DISCOVERED", r))
            elif st == "RESEARCHING":
                ev.append(("RESEARCHED", r))
            elif st in ("AWAITING_APPROVAL", "HELD"):
                ev.append(("AWAITING MICHAEL", r))
            elif st in ("ARCHIVED", "REJECTED"):
                ev.append(("PASSED", r))
        elif t == "SCORE_RECORDED":
            ev.append(("SCORED", r))
        elif t == "APPROVAL_DECIDED" and r.get("action_request_id") in comms_areq and _decision_of(r) == "YES":
            ev.append(("CONTACT APPROVED", r))
        elif t == "ACTION_EXECUTED" and r.get("action_request_id") in comms_areq:
            ev.append(("CONTACT SENT", r))
        elif t == "OUTCOME_RECORDED":
            kind = _outcome_kind(r)
            if kind == "message_replied":
                ev.append(("SELLER RESPONDED", r))
            elif kind in CLOSING_OUTCOMES:
                ev.append(("CLOSED", r))  # every other kind (acquired, won, attribution, no-reply) is trail-only
    return ev


def _timeline(events: list[tuple[str, dict]]) -> list[dict]:
    seen: dict[str, dict] = {}
    for stage, r in events:
        e = {"stage": stage, "at": r["ts"], "receipt_id": r["receipt_id"]}  # latest receipt per stage
        if stage == "CONTACT SENT" and (r.get("effector_response") or {}).get("dry_run"):
            e["dry_run"] = True
        seen[stage] = e
    return sorted(seen.values(), key=lambda e: (e["at"], STAGES.index(e["stage"])))


# ---------------------------------------------------------------- activity trail
_WHAT = {
    "ITEM_STATE_CHANGED": "changed the item", "SCORE_RECORDED": "scored the opportunity",
    "RECOMMENDATION_RECORDED": "recorded a recommendation", "ACTION_PROPOSED": "proposed an action",
    "POLICY_DECIDED": "applied policy", "APPROVAL_REQUESTED": "asked Michael to decide",
    "APPROVAL_DECIDED": "recorded Michael's decision", "ACTION_EXECUTING": "handed the action to the gateway",
    "ACTION_EXECUTED": "executed the action (DRY-RUN)", "ACTION_FAILED": "action did not execute",
    "OUTCOME_RECORDED": "recorded an outcome", "BUDGET_RESERVED": "reserved budget", "BUDGET_COMMITTED": "committed budget",
    "BUDGET_RELEASED": "released budget", "INJECTION_SUSPECTED": "flagged suspicious listing text",
    "KILL_SWITCH_CHANGED": "changed the kill switch",
}


def _result(r: dict) -> str:
    er, after = r.get("effector_response") or {}, r.get("after_state") or {}
    if er:
        return f"{er.get('status', 'n/a')}{' (dry-run)' if er.get('dry_run') else ''}"
    parts = [f"{k}={after[k]}" for k in ("state", "status", "decision", "kind") if after.get(k) is not None]
    return ", ".join(parts) or "recorded"


def _next_action(item: dict, areqs: list[dict]) -> str:
    st = item["state"]
    pending = [a for a in areqs if a.get("status") in ("pending_approval", "held")]
    if st == "AWAITING_APPROVAL" and pending:
        return f"Michael decides YES / NO / MODIFY / HOLD on: {pending[-1]['payload'].get('summary', pending[-1]['capability'])}"
    return {"HELD": "Waiting on the HOLD wake condition; never auto-executes", "RESEARCHING": "Gathering more evidence",
            "ACTED": "Waiting for the outcome / seller response", "ARCHIVED": "None (closed)", "REJECTED": "None",
            "FAILED": "Michael reviews why the action did not execute",
            "OUTCOME_RECORDED": "Outcome recorded; the system learns from it. Nothing pending", "LEARNED": "None (closed)"}.get(st, "Next workflow step runs automatically")


def _trail(item: dict, receipts: list[dict], areqs: list[dict]) -> list[dict]:
    rows = []
    for r in sorted(receipts, key=lambda x: x["seq"]):
        rows.append({"at": r["ts"], "agent": clean_text(r["actor"]["id"], 80), "what": _WHAT.get(r["type"], r["type"].lower().replace("_", " ")),
                     "why": clean_text(r["intent"], 400), "inputs": list(r["provenance_ids"]), "result": _result(r),
                     "receipt_id": r["receipt_id"], "next_action": "(done)"})
    if rows:
        rows[-1]["next_action"] = _next_action(item, areqs)
    return rows


# ---------------------------------------------------------------- recommendation
def _sorted_areqs(areqs: list[dict]) -> list[dict]:
    """Deterministic order (F-33): by (created_at, id), independent of the order the caller passes."""
    return sorted((a for a in areqs if isinstance(a, dict)), key=lambda a: (str(a.get("created_at", "")), str(a.get("action_request_id", ""))))


def _recommend(item: dict, areqs: list[dict], stage: str, dry_run_sent: bool = False) -> dict[str, Any]:
    areqs = _sorted_areqs(areqs)
    rec = item.get("recommendation") or {}
    verdict = rec.get("verdict")
    card = (item.get("scores") or {}).get("scorecard") or {}
    live = [a for a in areqs if a.get("status") in ("pending_approval", "held", "approved", "executing", "executed")]
    last = live[-1] if live else None
    cap = (last or {}).get("capability", "")
    action, waiting, why = "HOLD", False, "Not enough information yet to recommend an action; more research is running."
    if item["state"] in ("ARCHIVED", "REJECTED") or verdict == "PASS":
        action, why = "PASS", "; ".join(clean_text(x) for x in (rec.get("rationale") or ["The numbers do not support pursuing this."])[:2])
        if card.get("pass_on_priors"):
            action, why = "HOLD", "A pass here would rest on assumptions, not evidence; gather the missing evidence before discarding it."
    elif (not live) and item["state"] == "RECOMMENDED" and (verdict == "YES" or any(a.get("status") == "rejected" and not a.get("derived_from") for a in areqs)):
        action, why = "HOLD", "The numbers support acting, but policy blocked the proposed action; it needs a policy change or a different action."
    elif stage == "CLOSED":
        action, why = "PASS", "Closed: an outcome has been recorded, so no further action is recommended."
    elif item["state"] == "HELD":
        action, why = "HOLD", "Parked at Michael's request; it wakes on the condition he set and never acts on its own."
    elif verdict == "YES" or last:
        if cap.startswith("purchase."):
            action, why = "BUY", "The numbers clear Michael's thresholds; this is the purchase step."
        elif cap.startswith("offer.") and "counter" in cap:
            action, why = "COUNTER", "The seller has moved; a counter-offer is drafted for Michael's approval."
        elif cap.startswith("offer."):
            action, why = "OFFER", "The numbers clear Michael's thresholds; an offer within the maximum is drafted for approval."
        else:
            action, why = "CONTACT", "Contact first to confirm availability and condition before spending more research time."
        if dry_run_sent:  # F-31: a DRY-RUN is not a send, so there is no seller to wait for
            why += " The contact was only simulated (dry-run); nothing has been sent, and a live send needs Michael's separate go-ahead."
        elif (last or {}).get("status") == "executed" or stage in ("CONTACT SENT", "SELLER RESPONDED"):
            waiting, why = True, why + " Already contacted; waiting on the seller's reply."
    elif verdict == "MAYBE":
        action, why = "HOLD", "Promising but undecided: " + clean_text(rec.get("cheapest_decisive_evidence") or "needs more evidence") + "."
    out: dict[str, Any] = {"action": action, "waiting": waiting, "why": why}
    if last:
        out["action_request_id"] = last["action_request_id"]
        if last.get("status") in ("pending_approval", "held"):  # only meaningful while a decision is still needed
            out["requires_step_up"] = last.get("reversibility") == "irreversible" or last.get("category") in ("offer", "purchase", "money", "external_commitment")
    return out


# ---------------------------------------------------------------- economics from the Item (FACT/INFERENCE as stored)
def _economics(item: dict, enrich: Optional[dict]) -> dict[str, Any]:
    e = item.get("economics") or {}
    card = (item.get("scores") or {}).get("scorecard") or {}
    d = {k: v for k, v in (card.get("derived") or {}).items() if _finite(v)}   # derived values are numbers; anything else is dropped (F-52)
    prov = (item.get("recommendation") or {}).get("provenance_id")
    ask = (item["normalized"].get("price") or {}).get("amount")
    out: dict[str, Any] = {
        "asking_price": _datum(ask, "FACT", unit="USD", provenance_id=item["sources"][0].get("provenance_id")) if ask is not None else _unknown("no asking price in the listing"),
    }
    acq, rehab, resale = e.get("acquisition") or {}, e.get("rehab") or {}, e.get("resale") or {}
    cost = None
    if rehab and (rehab.get("parts_cost") is not None or rehab.get("materials_cost") is not None):
        cost = sum(v for v in (rehab.get("parts_cost"), rehab.get("materials_cost")) if _finite(v))
    ex = (enrich or {}).get("economics") or {}
    out["recommended_opening_offer"] = _from_block(ex, "opening_offer", "not computed yet (lane C)")
    out["maximum_acquisition_price"] = (_from_block(ex, "max_acquisition", "") if not _is_unknown(_from_block(ex, "max_acquisition", ""))
                                        else (_datum(card["walk_away_price"], "INFERENCE", unit="USD", provenance_id=prov,
                                                     note="walk-away price from the scoring engine") if card.get("walk_away_price") is not None
                                              else _unknown("lane C has not computed a walk-away price")))
    out["expected_repair_material_cost"] = (_datum(cost, "INFERENCE", unit="USD", provenance_id=prov) if cost is not None
                                            else _unknown("no repair/material estimate yet"))
    out["transport_cost"] = (_from_block(ex, "transport_cost", "") if not _is_unknown(_from_block(ex, "transport_cost", ""))
                             else (_datum(d["trips_cash"], "INFERENCE", unit="USD", provenance_id=prov) if d.get("trips_cash") is not None
                                   else _unknown("no trip estimate yet")))
    out["total_cash_at_risk"] = (_datum(d["cash_tied_up"], "INFERENCE", unit="USD", provenance_id=prov) if d.get("cash_tied_up") is not None
                                 else _unknown("not scored yet"))
    for key, src in (("resale_conservative", "comp_price_low"), ("resale_likely", "comp_price_expected"), ("resale_optimistic", "comp_price_high")):
        enriched = _from_block(ex, key, "")
        out[key] = enriched if not _is_unknown(enriched) else (
            _datum(resale[src], "INFERENCE", unit="USD", provenance_id=prov) if resale.get(src) is not None
            else _unknown("no sold-comp evidence yet; the system does not guess resale"))
    out["expected_gross_profit"] = (_datum(d["net_profit_deterministic"], "INFERENCE", unit="USD", provenance_id=prov,
                                           note="deterministic, before probability weighting") if d.get("net_profit_deterministic") is not None
                                    else _unknown("not scored yet"))
    if (not _is_unknown(out["expected_gross_profit"]) and _finite(resale.get("comp_price_low")) and _finite(resale.get("comp_price_high"))
            and _finite(d.get("cost_out")) and d["cost_out"] >= 0 and d.get("net_profit_deterministic") is not None):
        lo, hi = round(resale["comp_price_low"] - d["cost_out"], 2), round(resale["comp_price_high"] - d["cost_out"], 2)
        if lo <= hi and lo <= d["net_profit_deterministic"] <= hi:   # F-56: a reversed range, or one that does not contain the value, is not shown
            out["expected_gross_profit"]["low"] = lo    # conservative resale
            out["expected_gross_profit"]["high"] = hi   # optimistic resale
    out["expected_net_profit"] = (_datum(d["ev_net_profit"], "INFERENCE", unit="USD", provenance_id=prov,
                                         note="probability-weighted expected value") if d.get("ev_net_profit") is not None
                                  else _unknown("not scored yet"))
    out["expected_profit_per_hour"] = (_datum(d["ev_profit_per_hour"], "INFERENCE", unit="USD/hour", provenance_id=prov)
                                       if d.get("ev_profit_per_hour") is not None else _unknown("not scored yet"))
    out["expected_days_to_cash"] = (_datum(d["time_to_cash_days"], "INFERENCE", unit="days", provenance_id=prov)
                                    if d.get("time_to_cash_days") is not None else _unknown("not scored yet"))
    if card.get("scoring_config_version"):
        out["scoring_config_version"] = card["scoring_config_version"]
    return out


def class_threshold_errors(dc: Any) -> list[str]:
    """Class thresholds are data; validate them before they classify anything (F-54)."""
    if not isinstance(dc, dict):
        return ["deal_classes is not an object"]
    mi, qt, ci = (dc.get(k) if isinstance(dc.get(k), dict) else {} for k in ("micro_flip", "quick_turn", "capital_intensive_flip"))
    vals = {"micro_flip.max_cash_at_risk": mi.get("max_cash_at_risk"), "micro_flip.max_days_to_cash": mi.get("max_days_to_cash"),
            "quick_turn.max_days_to_cash": qt.get("max_days_to_cash"), "capital_intensive_flip.min_cash_at_risk": ci.get("min_cash_at_risk"),
            "capital_intensive_flip.or_min_days_to_cash": ci.get("or_min_days_to_cash")}
    errs = [f"{k} must be a finite positive number" for k, v in vals.items() if not (_finite(v) and v > 0)]
    if errs:
        return errs
    if not mi["max_cash_at_risk"] < ci["min_cash_at_risk"]:
        errs.append("micro_flip.max_cash_at_risk must be below capital_intensive_flip.min_cash_at_risk")
    if not (mi["max_days_to_cash"] <= qt["max_days_to_cash"] < ci["or_min_days_to_cash"]):
        errs.append("days thresholds must satisfy micro <= quick_turn < capital_intensive")
    return errs


def _class_of(cash: Optional[float], days: Optional[float], profile: dict) -> Optional[str]:
    """MICRO_FLIP / QUICK_TURN / STANDARD_FLIP / CAPITAL_INTENSIVE_FLIP from Michael's class thresholds (profile DATA)."""
    dc = (profile or {}).get("deal_classes") or {}
    if cash is None or days is None or not dc:
        return None
    mi, qt, ci = dc.get("micro_flip") or {}, dc.get("quick_turn") or {}, dc.get("capital_intensive_flip") or {}
    if class_threshold_errors(dc):
        return None   # F-54: broken thresholds never classify
    if cash >= ci.get("min_cash_at_risk", 10**9) or days >= ci.get("or_min_days_to_cash", 10**9):
        return "CAPITAL_INTENSIVE_FLIP"
    if cash <= mi.get("max_cash_at_risk", -1) and days <= mi.get("max_days_to_cash", -1):
        return "MICRO_FLIP"
    if days <= qt.get("max_days_to_cash", -1):
        return "QUICK_TURN"
    return "STANDARD_FLIP"


def _velocity_fields(item: dict, econ: dict, profile: dict, enr: dict) -> dict[str, Any]:
    """Aria/Michael 2026-10-07: capital velocity, cash multiple, class, downside, liquidity, skill, cash context are SEPARATE visible
    fields. Everything here is derived from numbers already on the card/item (INFERENCE) or UNKNOWN; nothing is invented."""
    e = item.get("economics") or {}
    raw_d = ((item.get("scores") or {}).get("scorecard") or {}).get("derived") or {}
    # F-52: if any of the three velocity inputs is PRESENT but unusable (NaN, string, bool, None, absurd magnitude), do not derive from the others
    malformed = bool(item.get("_velocity_malformed")) or any(
        raw_d.get(k) is not None and not (_finite(raw_d[k]) and abs(raw_d[k]) <= _MAX_MAG) for k in ("cash_tied_up", "ev_net_profit", "time_to_cash_days"))
    # None = just missing (F-69): only its own fields go UNKNOWN; NaN/strings/bools/absurd values blank the whole trio
    d = {k: v for k, v in raw_d.items() if _finite(v)}
    prov = (item.get("recommendation") or {}).get("provenance_id")
    rehab, resale, down = e.get("rehab") or {}, e.get("resale") or {}, e.get("downside") or {}
    cash = d.get("cash_tied_up") if _finite(d.get("cash_tied_up")) else None
    net = d.get("ev_net_profit") if _finite(d.get("ev_net_profit")) else None
    days = d.get("time_to_cash_days") if _finite(d.get("time_to_cash_days")) else None
    U = lambda why: _unknown(why)
    out: dict[str, Any] = {}
    flip = item.get("type") == "flip"
    if malformed or (cash is not None and cash < _MIN_CASH):
        cash = None   # F-53: non-positive/negligible cash at risk has no multiple/velocity/class
    if malformed:
        net = None
    if malformed or (days is not None and days < _MIN_DAYS):
        days = None
    if flip and cash and net is not None:
        out["cash_multiple"] = _datum(round(1 + net / cash, 2), "INFERENCE", unit="x", provenance_id=prov, note="1 + expected net / cash at risk")
        if days and days > 0:
            out["capital_velocity"] = _datum(round(net / cash / days, 3), "INFERENCE", unit="return on cash per day", provenance_id=prov,
                                             note=f"{net / cash:.0%} expected return on cash over about {days:g} day(s)")
    out.setdefault("cash_multiple", U("needs a cash-at-risk and an expected net (flips only)"))
    out.setdefault("capital_velocity", U("needs cash at risk, expected net and days to cash"))
    cls = _class_of(cash, days, profile) if flip else None
    if item.get("type") == "service":  # ADR-0013: services are their own class; flip-style cash multiple does not apply
        out["opportunity_class"] = _datum("SERVICE_JOB", "FACT", note="the Item is a service job; flip velocity maths does not apply")
    else:
        out["opportunity_class"] = _datum(cls, "RECOMMENDATION", note="thresholds are provisional data in operator_profile.v1.json (Michael confirms)") if cls \
            else U("needs cash at risk and days to cash (flips only)")
    sal = down.get("salvage_if_repair_fails")
    out["parts_out_floor"] = _datum(sal, "INFERENCE", unit="USD", provenance_id=prov, note="salvage if the repair fails") if _finite(sal) and sal >= 0 \
        else U("no parts-out / liquidation estimate")
    p_ok = rehab.get("repair_success_prob")
    out["catastrophic_downside_probability"] = _datum(round(1 - p_ok, 3), "INFERENCE", provenance_id=prov, note="1 - repair success probability") \
        if _finite(p_ok) and 0 <= p_ok <= 1 else U("no repair success probability")
    if _finite(p_ok) and "repair_scope_known" in rehab:
        lvl = "low" if (rehab["repair_scope_known"] and p_ok >= 0.9) else ("high" if (not rehab["repair_scope_known"] or p_ok < 0.7) else "medium")
        out["repair_uncertainty"] = _datum(lvl, "INFERENCE", provenance_id=prov, note="from repair_scope_known and repair success probability")
    else:
        out["repair_uncertainty"] = U("no repair scope / success estimate")
    sp, dom = resale.get("sale_prob"), resale.get("expected_dom_days")
    out["liquidity"] = _datum(f"{sp:.0%} sale probability, about {dom:g} days on market", "INFERENCE", provenance_id=prov) \
        if _finite(sp) and 0 <= sp <= 1 and _finite(dom) and dom > 0 else U("no valid sale-probability / days-on-market estimate")
    sk = d.get("skill_fit")
    out["skill_fit"] = _datum(sk, "INFERENCE", provenance_id=prov) if _finite(sk) and 0 <= sk <= 1 else U("no skill-fit score")
    out["personal_use_value"] = _from_block(_blk(enr, "economics"), "personal_use_value", "not supplied (only relevant if Michael might keep it)")
    cc = (profile or {}).get("current_cash_context") or {}
    cv = cc.get("value") if isinstance(cc, dict) else None
    valid_cash = (_finite(cv) and cv >= 0) or (isinstance(cv, str) and bool(clean_text(cv, 200).strip()))
    if cv is not None and not valid_cash:   # F-51: only a finite non-negative amount or a known label counts as Michael's statement
        out["current_cash_context"] = U("operator_profile current_cash_context.value is not a non-negative amount or a short statement; ignored (never assumed)")
    else:
        out["current_cash_context"] = _datum(clean_text(cv, 200) if isinstance(cv, str) else cv, "FACT", note="stated by Michael in operator_profile.v1.json") if cv is not None \
            else U("Michael has not stated his cash situation (so lock-up sensitivity cannot be judged)")
    return out


def _logistics(item: dict, enrich: Optional[dict], profile: dict) -> dict[str, Any]:
    t = profile["transport"]
    lg = (enrich or {}).get("logistics") or {}
    mode = _from_block(lg, "transport_mode", "lane C has not classified fits-in-truck vs requires-trailer")
    needed = _datum(mode["value"] == "requires_trailer", "INFERENCE", provenance_id=mode.get("provenance_id")) if not _is_unknown(mode) \
        else _unknown("depends on transport_mode")
    trips = ((item.get("economics") or {}).get("logistics") or {}).get("trips") or []
    miles = sum(x["round_trip_miles"] for x in trips if isinstance(x, dict) and _finite(x.get("round_trip_miles")) and x["round_trip_miles"] >= 0) if trips else None
    out = {
        "transport_mode": mode, "trailer_needed": needed,
        "trailer_owned": _datum(bool(t["trailer_owned"]), "FACT", note="operator_profile.v1.json (Michael)"),
        "borrowed_trailer_possible": _datum(bool(t["borrowed_trailer_possible"]), "FACT", note="operator_profile.v1.json (Michael)"),
        "borrowed_trailer_confirmed": _unknown("must be confirmed with the lender before pickup; the system never assumes it")
        if (needed.get("value") is True) else _unknown("only relevant if a trailer is needed"),
        "trip_miles_round_trip": _from_block(lg, "trip_miles_round_trip", "") if not _is_unknown(_from_block(lg, "trip_miles_round_trip", ""))
        else (_datum(miles, "INFERENCE", unit="miles") if miles else _unknown("no trip plan yet")),
        "trip_hours": _from_block(lg, "trip_hours", "no trip-time estimate yet"),
        "fuel_cost": _from_block(lg, "fuel_cost", "no fuel estimate yet"),
        "difficulty": _from_block(lg, "difficulty", "lane C has not rated transport difficulty"),
    }
    return out


def _collect_unknowns(prefix: str, node: Any, out: list[str]) -> None:
    if isinstance(node, dict):
        if node.get("value") == "UNKNOWN":
            out.append(prefix)
        else:
            for k, v in node.items():
                if k != "value":
                    _collect_unknowns(f"{prefix}.{k}" if prefix else k, v, out)


# ---------------------------------------------------------------- plain-English reasons (facts only)
def _machine_noise(line: str) -> bool:
    """Engine notes meant for the machine/QA (placeholders, provisional thresholds) are not reasons for Michael."""
    return bool(re.search(r"PLACEHOLDER|provisional|MICHAEL_DECISIONS|scorer \(lane", line, re.I))


def _fact_reasons(item: dict, econ: dict, la: dict, lg: dict) -> list[str]:
    """Plain-English lines built ONLY from data already on the card (so nothing here can be fabricated)."""
    out: list[str] = []
    ask, likely, cons = econ["asking_price"], econ["resale_likely"], econ["resale_conservative"]
    if not _is_unknown(ask) and not _is_unknown(likely):
        line = f"Asking ${ask['value']:,.0f} against a likely resale of ${likely['value']:,.0f}"
        if not _is_unknown(cons):
            line += f" (conservative ${cons['value']:,.0f})"
        out.append(line + ".")
    net = econ["expected_net_profit"]
    if not _is_unknown(net):
        out.append(f"Expected net about ${net['value']:,.0f} after repair and transport, with ${econ['total_cash_at_risk']['value']:,.0f} of cash at risk."
                   if not _is_unknown(econ["total_cash_at_risk"]) else f"Expected net about ${net['value']:,.0f} after repair and transport.")
    sr = la["stale_risk"]
    if not _is_unknown(sr):
        recent = f" — {la['recent_activity'][0]}" if la["recent_activity"] else ""
        out.append(f"Stale-listing risk is {sr['value']}{recent}.")
    cls, mult = econ.get("opportunity_class", {}), econ.get("cash_multiple", {})
    if not _is_unknown(cls) and not _is_unknown(mult):
        shape = {"MICRO_FLIP": "a micro flip: a tiny amount of cash that turns almost at once, so a small absolute profit can still be an excellent use of money",
                 "QUICK_TURN": "a quick turn: cash comes back within about a week, so it can be redeployed",
                 "STANDARD_FLIP": "a standard flip",
                 "CAPITAL_INTENSIVE_FLIP": "capital-intensive: a lot of cash tied up and/or a long hold, so it has to clear a meaningful profit to be worth it"}[cls["value"]]
        d_ = econ.get("expected_days_to_cash", {})
        out.append(f"This is {shape} (about {mult['value']:g}x your cash" + (f", back in about {d_['value']:g} day(s)" if not _is_unknown(d_) else "") + ").")
    if lg["transport_mode"]["value"] == "requires_trailer":
        out.append("Needs a trailer. That is a cost and a confirmation step (borrowed trailer), not a reason to skip the deal.")
    elif lg["transport_mode"]["value"] == "fits_truck":
        out.append("Fits the truck; no trailer needed.")
    return out


# ---------------------------------------------------------------- build
def _date_checked(d: dict, item: dict, not_before: Optional[dict]) -> dict:
    """A listing date must parse, cannot be later than a day after we discovered the item, and an edit cannot precede the
    post (07 F-28). Anything else is UNKNOWN, not FACT."""
    if _is_unknown(d):
        return d
    if not isinstance(d["value"], str):  # a bare number such as 20261005 is not an ISO date-time
        return _unknown("lane date is not an ISO date-time string")
    try:
        t = parse(d["value"])
        if t.tzinfo is None:
            t = t.replace(tzinfo=parse("1970-01-01T00:00:00Z").tzinfo)
        limit = parse(item["created_at"]) + timedelta(days=1)
        if t > limit or (not_before is not None and t < parse(str(not_before["value"])).replace(tzinfo=t.tzinfo)):
            return _unknown("lane date is in the future or out of order")
    except (ValueError, TypeError, KeyError):
        return _unknown("lane date is not a valid date-time")
    return d


def _lane_why(enr: dict) -> tuple[list[str], list[str]]:
    """Lane-supplied reasons are shown ONLY with provenance (F-29): (lines, provenance ids)."""
    prov = (enr.get("_prov") or {}).get("why") if isinstance(enr.get("_prov"), dict) else None
    block = enr.get("why")
    lines = block.get("why") if isinstance(block, dict) else block
    if not (isinstance(prov, str) and _PROV_RX.match(prov)):
        return [], []
    return _strs(lines, limit=10, size=300), [prov]


CATEGORY_TAGS = ("mechanic_special", "project", "parts_donor", "quick_turn", "auction_candidate", "contractor_opportunity",
                 "wanted_match")


def _category_tags(enr: dict) -> list[dict]:
    """Audience/category tags (ADR-0013). INFERENCE only, and only with provenance AND quoted evidence; anything else is
    dropped. Absence of a tag is not a "no"."""
    blk = enr.get("category_tags")
    prov = (enr.get("_prov") or {}).get("category_tags") if isinstance(enr.get("_prov"), dict) else None
    items = blk.get("tags") if isinstance(blk, dict) else blk
    if not (isinstance(prov, str) and _PROV_RX.match(prov)) or not isinstance(items, list):
        return []
    out, seen = [], set()
    for t in items:
        if not isinstance(t, dict) or t.get("tag") not in CATEGORY_TAGS or t["tag"] in seen:
            continue
        ev = []
        for e in t.get("evidence") if isinstance(t.get("evidence"), list) else []:
            if isinstance(e, dict) and isinstance(e.get("quote"), str) and e["quote"].strip():
                ev.append({"field": clean_text(e.get("field") if isinstance(e.get("field"), str) else "listing", 60),
                           "quote": clean_text(e["quote"], 200)})
        ev = [e for e in ev if e["quote"]][:5]
        if ev:
            seen.add(t["tag"])
            out.append({"tag": t["tag"], "basis": "INFERENCE", "provenance_id": prov, "evidence": ev})
    return out


def _risks(va_in: dict, dropped: Optional[list] = None) -> list[dict]:
    out = []
    for r in va_in.get("model_specific_risks") if isinstance(va_in.get("model_specific_risks"), list) else []:
        if not isinstance(r, dict) or r.get("basis") not in _BASES or not isinstance(r.get("risk"), str) or not r["risk"].strip():
            continue
        e: dict[str, Any] = {"risk": clean_text(r["risk"], 400), "basis": r["basis"]}
        if r.get("kind") in ("failure_mode", "expensive_part", "parts_availability", "known_weakness", "resale_demand", "economic"):
            e["kind"] = r["kind"]
        if isinstance(r.get("source"), str):
            e["source"] = clean_text(r["source"], 300)
        if isinstance(r.get("provenance_id"), str) and _PROV_RX.match(r["provenance_id"]):
            e["provenance_id"] = r["provenance_id"]
        if not (e.get("provenance_id") or _source_ok(e.get("source"))):
            # an uncheckable model-specific claim is not shown at all (07 F-27): UNKNOWN beats an unsourced claim
            if dropped is not None:
                dropped.append((e["risk"][:80], "no checkable source"))
            continue
        if elementary_advice(e["risk"]):
            if dropped is not None:
                dropped.append((e["risk"][:80], "elementary advice"))
            continue
        out.append(e)
    return out


def build_card(item: dict, receipts: list[dict], areqs: list[dict], enrichment: Optional[dict] = None, *,
               profile: Optional[dict] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """The card for one Item. Pure and total: same inputs → same card_hash (generated_at excluded), and malformed lane
    data degrades to UNKNOWN instead of failing (F-26)."""
    profile = profile or load_profile()
    enr = enrichment if isinstance(enrichment, dict) else {}
    _rd = ((item.get("scores") or {}).get("scorecard") or {}).get("derived") if isinstance(item.get("scores"), dict) else None
    _rd = _rd if isinstance(_rd, dict) else {}
    vel_malformed = any(_rd.get(k) is not None and not (_finite(_rd[k]) and abs(_rd[k]) <= _MAX_MAG)
                        for k in ("cash_tied_up", "ev_net_profit", "time_to_cash_days"))   # judged on the RAW value, before sanitising
    item = {**item, "_velocity_malformed": vel_malformed, "economics": _sane(item.get("economics")) if isinstance(item.get("economics"), dict) else item.get("economics"),
            "scores": _sane(item.get("scores")) if isinstance(item.get("scores"), dict) else item.get("scores")}
    n = item["normalized"]
    src0 = item["sources"][0]
    # only this Item's own receipts (F-38): its item_id, or one of its action requests
    areqs = _sorted_areqs(areqs)
    mine = {a.get("action_request_id") for a in areqs}
    receipts = [r for r in receipts if r.get("item_id") == item["item_id"] or r.get("action_request_id") in mine]
    la_in, sel_in = _blk(enr, "listing_activity"), _blk(enr, "seller")
    loc = n.get("location") or {}
    loc_s = ", ".join(clean_text(x, 80) for x in (loc.get("city"), loc.get("state")) if isinstance(x, str) and x)
    miles = loc.get("road_miles_one_way")
    posted = _date_checked(_from_block(la_in, "posted_at", "this source does not expose the original post date"), item, None)
    updated = _date_checked(_from_block(la_in, "updated_at", "this source does not expose the last edit date"), item,
                            posted if not _is_unknown(posted) else None)
    la = {
        "posted_at": posted,
        "updated_at": updated,
        "age_days": _from_block(la_in, "age_days", "needs the original post date"),
        "recent_activity": [clean_text(x) for x in _strs(la_in.get("recent_activity"))],
        "suspected_relist": _from_block(la_in, "suspected_relist", "relist detection needs prior sightings or dates"),
        "stale_risk": _from_block(la_in, "stale_risk", "listing dates not available from this source"),
    }
    seller = {k: _from_block(sel_in, k, "this source does not expose it") for k in
              ("account_age", "rating", "prior_listings", "complaint_signals", "response_history", "inconsistencies")}
    seller["confidence"] = sel_in.get("confidence") if sel_in.get("confidence") in ("high", "medium", "low") else "UNKNOWN"
    econ = _economics(item, enr)
    econ.update(_velocity_fields(item, econ, profile, enr))
    va_in = _blk(enr, "value_add")
    se_in = _blk(enr, "seasonality")
    seasonality = {"demand_now": _from_block(se_in, "demand_now", "no seasonality evidence for this category"),
                   "hold_likely": _from_block(se_in, "hold_likely", "depends on seasonality"),
                   "note": _from_block(se_in, "note", "no seasonality note")}
    pm = se_in.get("peak_months")
    if isinstance(pm, list) and pm and all(isinstance(m, int) and not isinstance(m, bool) and 1 <= m <= 12 for m in pm):
        seasonality["peak_months"] = sorted(set(pm))
    dropped: list = []
    risks = _risks(va_in, dropped)
    if dropped:  # a rejected claim leaves a trace: on the card, and in the log for lane C (07 residual)
        import logging

        logging.getLogger("mbos.card").warning("card %s dropped %d model-specific risk(s): %s", item["item_id"], len(dropped), dropped)
    lg = _logistics(item, enr, profile)
    events = _stage_events(item, receipts, areqs)
    timeline = _timeline(events)
    state_stage = {"AWAITING_APPROVAL": "AWAITING MICHAEL", "HELD": "AWAITING MICHAEL", "ARCHIVED": "PASSED", "REJECTED": "PASSED"}.get(item["state"])
    closed = any(t["stage"] == "CLOSED" for t in timeline)
    current = state_stage or ("CLOSED" if closed else (timeline[-1]["stage"] if timeline else "DISCOVERED"))
    dry = any(t["stage"] == "CONTACT SENT" and t.get("dry_run") for t in timeline)
    rec = item.get("recommendation") or {}
    lane_lines, why_prov = _lane_why(enr)
    why = list(lane_lines) + _fact_reasons(item, econ, la, lg)
    why += [clean_text(x) for x in (rec.get("rationale") or []) if isinstance(x, str) and not _machine_noise(x)]
    if not why:
        why = ["Discovered; no reasoning yet (still being researched)."]
    flags = [clean_text(f, 60) for f in (n.get("flags") or []) if isinstance(f, str)]
    card: dict[str, Any] = {
        "card_version": CARD_VERSION, "item_id": item["item_id"], "generated_at": iso(now or utcnow()),
        "item": {"title": clean_text(n["title"], 300), "make_model": _from_block(enr, "make_model", "not extracted from the listing"),
                 "category": item["category"], "type": item["type"], "asking_price": econ["asking_price"],
                 "location": _datum(loc_s, "FACT", provenance_id=src0.get("provenance_id")) if loc_s else _unknown("listing has no location"),
                 "distance_miles": (_datum(float(miles), "FACT", unit="miles") if _finite(miles) and miles >= 0 else _from_block(enr, "distance_miles", "no distance computed")),
                 "source": clean_text(src0["source"], 80), "url": clean_text(src0["url"], 500)},
        "listing_activity": la, "seller": seller, "why": why, "economics": econ,
        "value_add_plan": {"plan": _from_block(va_in, "plan", "no value-add plan from lane C yet"), "model_specific_risks": risks},
        "seasonality": seasonality, "logistics": lg,
        "recommendation": _recommend(item, areqs, current, dry_run_sent=dry),
        "status": {"current": current, "timeline": timeline},
        "activity_trail": _trail(item, receipts, areqs), "unknowns": [],
    }
    tags = _category_tags(enr)
    card["category_tags"] = tags
    if flags:
        card["item"]["flags"] = flags
    if why_prov:
        card["why_provenance"] = why_prov
    unk: list[str] = []
    _collect_unknowns("", {k: v for k, v in card.items() if k not in ("activity_trail", "status", "why", "unknowns", "why_provenance")}, unk)
    if not tags:
        unk.append("category_tags (no evidence-based tag; absence is not a 'no')")
    if dropped:
        unk.append(f"value_add_plan.model_specific_risks ({len(dropped)} lane claim(s) rejected: unsourced or elementary)")
    card["unknowns"] = sorted(set(unk))
    card["card_hash"] = sha256_of({k: v for k, v in card.items() if k not in ("generated_at", "card_hash")})
    return card


def _source_ok(src: Any) -> bool:
    """A source must name something checkable: at least a few letters, not a placeholder, and either a URL, a date, or
    two+ words (e.g. "CPSC recall 24-123, 2026-03-01")."""
    if not isinstance(src, str):
        return False
    t = src.strip()
    if t.lower() in JUNK_SOURCES or len(t) < 8 or not re.search(r"[A-Za-z]{3}", t):
        return False
    return bool(re.search(r"https?://|\d{4}-\d{2}-\d{2}|\d{3,}", t) or len(t.split()) >= 3)


def validate_card(card: dict) -> list[str]:
    """Schema errors (card.schema.json) + honesty/lint/integrity rules. Empty list = a card Michael can be shown."""
    errs = schemas.errors("card", card)
    if errs:
        return errs
    plan = card["value_add_plan"]["plan"]
    texts = [str(plan.get("value", ""))] if not _is_unknown(plan) else []
    texts += [r["risk"] for r in card["value_add_plan"]["model_specific_risks"]]
    for t in texts:
        for hit in elementary_advice(t):
            errs.append(f"value_add_plan: elementary advice not allowed: {hit!r}")
    for w in card["why"]:
        for hit in elementary_advice(w):
            errs.append(f"why: elementary advice not allowed: {hit!r}")
    for r in card["value_add_plan"]["model_specific_risks"]:
        if r["basis"] != "FACT" and not r.get("provenance_id") and not _source_ok(r.get("source")):
            errs.append(f"model-specific risk without a checkable source/provenance: {r['risk']!r}")
        elif r["basis"] == "FACT" and not (r.get("provenance_id") or _source_ok(r.get("source"))):
            errs.append(f"FACT risk without a checkable source/provenance: {r['risk']!r}")
    if card["recommendation"]["waiting"] and card["recommendation"]["action"] in ("PASS",):
        errs.append("a PASS cannot be 'waiting'")
    claimed = card.get("card_hash")
    if claimed is not None and claimed != sha256_of({k: v for k, v in card.items() if k not in ("generated_at", "card_hash")}):
        errs.append("card_hash does not match the card's content (tampered or stale)")
    return errs


# ---------------------------------------------------------------- loading (both state backends)
def load_inputs(conn: Any, item_id: str) -> tuple[dict, list[dict], list[dict]]:
    """(item, receipts, action_requests) for one Item, from the reference DDL or lane D's document views."""
    import sqlalchemy as sa

    lane_d = conn.execute(sa.text("SELECT to_regclass('mbos.v_item_documents') IS NOT NULL")).scalar_one()
    if lane_d:
        item = conn.execute(sa.text("SELECT doc FROM mbos.v_item_documents WHERE item_id = :i"), {"i": item_id}).scalar_one()
        receipts = [r[0] for r in conn.execute(sa.text(
            "SELECT d.doc FROM mbos.receipts r JOIN mbos.v_receipt_documents d USING (receipt_id) WHERE r.item_id = :i ORDER BY r.seq"), {"i": item_id})]
        areqs = [r[0] for r in conn.execute(sa.text(
            "SELECT d.doc FROM mbos.action_requests a JOIN mbos.v_action_request_documents d USING (action_request_id) "
            "WHERE a.item_id = :i ORDER BY a.created_at"), {"i": item_id})]
        return item, receipts, areqs
    from mbos.ledger import load_receipts

    item = conn.execute(sa.text("SELECT body FROM mbos.items WHERE item_id = :i"), {"i": item_id}).scalar_one()
    areqs = [r[0] for r in conn.execute(sa.text(
        "SELECT body FROM mbos.action_requests WHERE item_id = :i ORDER BY body->>'created_at'"), {"i": item_id})]
    return item, load_receipts(conn, "item_id = :i", {"i": item_id}), areqs


def enrichment_from_item(conn: Any, item: dict) -> dict[str, Any]:
    """Read back the blocks lanes attached with `record_enrichment` (latest per block). Unreadable or non-JSON
    artifacts are skipped: they degrade to UNKNOWN on the card, never to a guess."""
    import json as _json

    import sqlalchemy as sa

    out: dict[str, Any] = {}
    for r in item.get("research") or []:
        f, uri = r.get("field", ""), r.get("source_uri", "")
        if not (f.startswith("card.") and uri.startswith("artifact:")):
            continue
        row = conn.execute(sa.text("SELECT content FROM mbos.artifacts WHERE sha256 = :h"), {"h": uri[len("artifact:"):]}).first()
        if row is None:
            continue
        try:
            out[f[len("card."):]] = _json.loads(bytes(row[0]))
        except (ValueError, TypeError):
            continue
        out.setdefault("_prov", {})[f[len("card."):]] = r.get("provenance_id")
    return out


# ---------------------------------------------------------------- plain-text rendering (CLI / digest / notifications)
def _fmt(d: dict, money: bool = False) -> str:
    if d.get("value") == "UNKNOWN":
        return "UNKNOWN"
    v = d["value"]
    if d.get("low") is not None and d.get("high") is not None:
        return f"${d['low']:,.0f}–${d['high']:,.0f}" if money else f"{d['low']}–{d['high']}"
    if money and isinstance(v, (int, float)):
        return f"${v:,.0f}"
    return str(v)


def render_text(card: dict) -> str:
    """Michael's decision-ready view. Untrusted listing text is included as plain text only."""
    i, la, e, lg, r = card["item"], card["listing_activity"], card["economics"], card["logistics"], card["recommendation"]
    sep = "-" * 50
    ago = lambda d: _fmt(d) if d.get("value") == "UNKNOWN" else str(d["value"])[:10]
    T = clean_text
    lines = [sep, T(i["title"]).upper(), f"{_fmt(i['location'])} — {_fmt(i['asking_price'], True)}   [{T(i['source'], 80)}]"]
    if i.get("flags"):
        lines.append("FLAGS: " + ", ".join(T(f, 60) for f in i["flags"]) + "  (listing text needs Michael's eyes)")
    lines.append("")
    lines += [f"POSTED: {ago(la['posted_at'])}   UPDATED: {ago(la['updated_at'])}   AGE: {_fmt(la['age_days'])} days"
              if la["age_days"]["value"] != "UNKNOWN" else f"POSTED: {ago(la['posted_at'])}   UPDATED: {ago(la['updated_at'])}",
              f"STALE RISK: {_fmt(la['stale_risk'])}" + (f"   SUSPECTED RELIST: {_fmt(la['suspected_relist'])}" if la['suspected_relist']['value'] != 'UNKNOWN' else "")]
    lines += [f"  · {T(a)}" for a in la["recent_activity"]]
    s = card["seller"]
    lines += ["", "SELLER: " + "; ".join(f"{k.replace('_', ' ')} {_fmt(s[k])}" for k in ("account_age", "rating", "prior_listings", "response_history")
                                         if s[k]["value"] != "UNKNOWN") + (f" (confidence {s['confidence']})" if s["confidence"] != "UNKNOWN" else "")
              if any(s[k]["value"] != "UNKNOWN" for k in ("account_age", "rating", "prior_listings", "response_history"))
              else "SELLER: UNKNOWN (this source does not expose seller history)"]
    lines += ["", "WHY IT'S INTERESTING:"] + [f"  {T(w)}" for w in card["why"]]
    lines += ["", "ESTIMATED NUMBERS:",
              f"  Ask: {_fmt(e['asking_price'], True)}   Opening offer: {_fmt(e['recommended_opening_offer'], True)}   Max acquisition: {_fmt(e['maximum_acquisition_price'], True)}",
              f"  Repair/material: {_fmt(e['expected_repair_material_cost'], True)}   Transport: {_fmt(e['transport_cost'], True)}   Cash at risk: {_fmt(e['total_cash_at_risk'], True)}",
              f"  Resale: conservative {_fmt(e['resale_conservative'], True)} / likely {_fmt(e['resale_likely'], True)} / optimistic {_fmt(e['resale_optimistic'], True)}",
              f"  Gross {_fmt(e['expected_gross_profit'], True)}   Net {_fmt(e['expected_net_profit'], True)}   Per hour {_fmt(e['expected_profit_per_hour'], True)}   Days to cash {_fmt(e['expected_days_to_cash'])}"]
    def _v(k: str, money: bool = False) -> str:
        return _fmt(e[k], money) if k in e else "UNKNOWN"

    cap = [f"  Class: {_v('opportunity_class')}   Cash multiple: {_v('cash_multiple')}x   Capital velocity: {_v('capital_velocity')}/day"
           if e.get("cash_multiple", {}).get("value") != "UNKNOWN" else f"  Class: {_v('opportunity_class')}   Cash multiple: UNKNOWN   Capital velocity: UNKNOWN",
           f"  Downside: repair fails outright {_v('catastrophic_downside_probability')} · parts-out floor {_v('parts_out_floor', True)} · repair uncertainty {_v('repair_uncertainty')}",
           f"  Liquidity: {_v('liquidity')} · skill fit {_v('skill_fit')} · personal-use value {_v('personal_use_value')}",
           f"  Cash situation: {_v('current_cash_context')}"]
    lines += ["", "CAPITAL (why a small fast flip can outrank a big slow one):"] + cap
    plan = card["value_add_plan"]
    lines += ["", f"VALUE-ADD PLAN: {_fmt(plan['plan'])}"] + [f"  ! {T(x['risk'])} [{x['basis']}{', ' + T(x['source'], 120) if x.get('source') else ''}]" for x in plan["model_specific_risks"]]
    se = card["seasonality"]
    lines += ["", f"SEASONALITY: {_fmt(se['note'])}" + (f" (demand now: {_fmt(se['demand_now'])}; hold likely: {_fmt(se['hold_likely'])})" if se['demand_now']['value'] != 'UNKNOWN' else "")]
    if card.get("category_tags"):
        lines += ["", "TAGS (inferred from the listing): " + "; ".join(f"{T(t['tag'])} (\"{T(t['evidence'][0]['quote'], 80)}\")" for t in card["category_tags"])]
    mode = lg["transport_mode"]["value"]
    lines += ["", "TRANSPORT: " + {"fits_truck": "Fits truck. No trailer required.", "requires_trailer": "Requires a trailer (not owned; borrowing is possible but MUST be confirmed with the lender before pickup)."}.get(mode, "UNKNOWN (not yet classified)")
              + f" Trip: {_fmt(lg['trip_miles_round_trip'])} mi round trip, {_fmt(lg['trip_hours'])} h, fuel {_fmt(lg['fuel_cost'], True)}, difficulty {_fmt(lg['difficulty'])}."]
    st = card["status"]
    _dry = any(t["stage"] == "CONTACT SENT" and t.get("dry_run") for t in st["timeline"])
    lines += ["", "SYSTEM STATUS: " + " → ".join(t["stage"].title() + (" (dry-run)" if t.get("dry_run") else "") for t in st["timeline"])
              + f"   [now: {st['current']}{' (DRY-RUN: simulated, nothing sent)' if _dry and st['current'] == 'CONTACT SENT' else ''}]"]
    lines += [f"  {t['at'][:16]}  {t['stage']}" + ("  (DRY-RUN: simulated, nothing sent)" if t.get("dry_run") else "") for t in st["timeline"]]
    lines += ["", f"RECOMMENDATION: {r['action']}" + (" / WAIT FOR RESPONSE" if r["waiting"] else "") + (" (needs step-up approval)" if r.get("requires_step_up") else ""), f"  {T(r['why'], 600)}"]
    if card["unknowns"]:
        lines += ["", f"UNKNOWN ({len(card['unknowns'])}): " + ", ".join(card["unknowns"])]
    lines += ["", "ACTIVITY (every action has a receipt):"] + [f"  {t['at'][:16]}  {T(t['agent'], 60)}: {T(t['what'], 80)} — {T(t['why'], 90)}  → {T(t['result'], 80)}  [{t['receipt_id']}]" for t in card["activity_trail"]]
    lines += [f"  NEXT: {T(card['activity_trail'][-1]['next_action'], 200)}"] if card["activity_trail"] else []
    return "\n".join(lines + [sep])
