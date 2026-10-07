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
from datetime import datetime
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
ELEMENTARY_ADVICE = [re.compile(p, re.I) for p in (
    r"\bcheck (the )?(engine )?compression\b", r"\bcheck (for )?(a )?spark\b", r"\binspect (the )?fuel\b",
    r"\bcheck (the )?(engine )?oil\b", r"\bcheck (the )?(air )?filter\b", r"\bcheck (the )?(spark ?plug|plugs)\b",
    r"\binspect (the )?(belts?|hoses?)\b", r"\bverify (it )?(starts|runs)\b(?! after)", r"\bmake sure (it|the engine) (starts|runs)\b",
    r"\bcheck (the )?battery\b", r"\blook for (any )?(leaks|damage)\b",
)]


def elementary_advice(text: str) -> list[str]:
    """Phrases in `text` that are elementary for an experienced mechanic (empty list = fine)."""
    return [m.group(0) for rx in ELEMENTARY_ADVICE for m in [rx.search(text or "")] if m]


def load_profile(path: Optional[str | Path] = None) -> dict[str, Any]:
    p = Path(path) if path else Path(__file__).resolve().parents[2] / "config" / "operator_profile.v1.json"
    return json.loads(p.read_text())


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
    """Take a lane-supplied datum verbatim if it is well-formed, else UNKNOWN. Never invent."""
    v = (block or {}).get(key)
    if isinstance(v, dict) and (v.get("value") == "UNKNOWN" or ("value" in v and v.get("basis") in ("FACT", "INFERENCE", "RECOMMENDATION"))):
        if v.get("value") == "UNKNOWN" and v.get("basis"):
            return _unknown(v.get("reason") or reason)
        return {k: val for k, val in v.items() if k in ("value", "unit", "low", "high", "basis", "provenance_id", "note", "reason")}
    return _unknown(reason)


def _is_unknown(d: dict) -> bool:
    return d.get("value") == "UNKNOWN"


# ---------------------------------------------------------------- status timeline
def _stage_events(item: dict, receipts: list[dict], areqs: list[dict]) -> list[tuple[str, dict]]:
    """(stage, receipt) for every stage that has an event source. Stages without one (NEGOTIATING, QUALIFIED until
    inbound comms exist) are never invented."""
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
            elif st == "AWAITING_APPROVAL" or st == "HELD":
                ev.append(("AWAITING MICHAEL", r))
            elif st in ("ARCHIVED", "REJECTED"):
                ev.append(("PASSED", r))
        elif t == "SCORE_RECORDED":
            ev.append(("SCORED", r))
        elif t == "APPROVAL_DECIDED" and r.get("action_request_id") in comms_areq and after.get("decision") == "YES":
            ev.append(("CONTACT APPROVED", r))
        elif t == "ACTION_EXECUTED" and r.get("action_request_id") in comms_areq:
            ev.append(("CONTACT SENT", r))
        elif t == "OUTCOME_RECORDED":
            kind = (after or {}).get("kind", "")
            ev.append(("SELLER RESPONDED" if kind == "message_replied" else "CLOSED", r)
                      if kind not in ("message_no_reply", "wasted_trip") else ("CONTACT SENT", r))
    return ev


def _timeline(events: list[tuple[str, dict]]) -> list[dict]:
    seen: dict[str, dict] = {}
    for stage, r in events:
        seen[stage] = {"stage": stage, "at": r["ts"], "receipt_id": r["receipt_id"]}  # latest receipt per stage
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
        rows.append({"at": r["ts"], "agent": r["actor"]["id"], "what": _WHAT.get(r["type"], r["type"].lower().replace("_", " ")),
                     "why": r["intent"], "inputs": list(r["provenance_ids"]), "result": _result(r),
                     "receipt_id": r["receipt_id"], "next_action": "(done)"})
    if rows:
        rows[-1]["next_action"] = _next_action(item, areqs)
    return rows


# ---------------------------------------------------------------- recommendation
def _recommend(item: dict, areqs: list[dict], stage: str) -> dict[str, Any]:
    rec = item.get("recommendation") or {}
    verdict = rec.get("verdict")
    card = (item.get("scores") or {}).get("scorecard") or {}
    live = [a for a in areqs if a.get("status") in ("pending_approval", "held", "approved", "executing", "executed")]
    last = live[-1] if live else None
    cap = (last or {}).get("capability", "")
    action, waiting, why = "HOLD", False, "Not enough information yet to recommend an action; more research is running."
    if item["state"] in ("ARCHIVED", "REJECTED") or verdict == "PASS":
        action, why = "PASS", "; ".join((rec.get("rationale") or ["The numbers do not support pursuing this."])[:2])
        if card.get("pass_on_priors"):
            action, why = "HOLD", "A pass here would rest on assumptions, not evidence; gather the missing evidence before discarding it."
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
        if (last or {}).get("status") in ("executed",) or stage in ("CONTACT SENT", "SELLER RESPONDED"):
            waiting, why = True, why + " Already contacted; waiting on the seller's reply."
    elif verdict == "MAYBE":
        action, why = "HOLD", "Promising but undecided: " + (rec.get("cheapest_decisive_evidence") or "needs more evidence") + "."
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
    d = card.get("derived") or {}
    prov = (item.get("recommendation") or {}).get("provenance_id")
    ask = (item["normalized"].get("price") or {}).get("amount")
    out: dict[str, Any] = {
        "asking_price": _datum(ask, "FACT", unit="USD", provenance_id=item["sources"][0].get("provenance_id")) if ask is not None else _unknown("no asking price in the listing"),
    }
    acq, rehab, resale = e.get("acquisition") or {}, e.get("rehab") or {}, e.get("resale") or {}
    cost = None
    if rehab and (rehab.get("parts_cost") is not None or rehab.get("materials_cost") is not None):
        cost = float(rehab.get("parts_cost", 0)) + float(rehab.get("materials_cost", 0))
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


def _logistics(item: dict, enrich: Optional[dict], profile: dict) -> dict[str, Any]:
    t = profile["transport"]
    lg = (enrich or {}).get("logistics") or {}
    mode = _from_block(lg, "transport_mode", "lane C has not classified fits-in-truck vs requires-trailer")
    needed = _datum(mode["value"] == "requires_trailer", "INFERENCE", provenance_id=mode.get("provenance_id")) if not _is_unknown(mode) \
        else _unknown("depends on transport_mode")
    trips = ((item.get("economics") or {}).get("logistics") or {}).get("trips") or []
    miles = sum(float(x.get("round_trip_miles", 0)) for x in trips) if trips else None
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
    if lg["transport_mode"]["value"] == "requires_trailer":
        out.append("Needs a trailer. That is a cost and a confirmation step (borrowed trailer), not a reason to skip the deal.")
    elif lg["transport_mode"]["value"] == "fits_truck":
        out.append("Fits the truck; no trailer needed.")
    return out


# ---------------------------------------------------------------- build
def build_card(item: dict, receipts: list[dict], areqs: list[dict], enrichment: Optional[dict] = None, *,
               profile: Optional[dict] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """The card for one Item. Pure: same inputs → same card_hash (generated_at excluded from the hash)."""
    profile = profile or load_profile()
    enr = enrichment or {}
    n = item["normalized"]
    src0 = item["sources"][0]
    la_in, sel_in = enr.get("listing_activity") or {}, enr.get("seller") or {}
    loc = n.get("location") or {}
    loc_s = ", ".join(x for x in (loc.get("city"), loc.get("state")) if x)
    miles = loc.get("road_miles_one_way")
    stale = _from_block(la_in, "stale_risk", "listing dates not available from this source")
    la = {
        "posted_at": _from_block(la_in, "posted_at", "this source does not expose the original post date"),
        "updated_at": _from_block(la_in, "updated_at", "this source does not expose the last edit date"),
        "age_days": _from_block(la_in, "age_days", "needs the original post date"),
        "recent_activity": [str(x) for x in (la_in.get("recent_activity") or [])],
        "suspected_relist": _from_block(la_in, "suspected_relist", "relist detection needs prior sightings or dates"),
        "stale_risk": stale,
    }
    seller = {k: _from_block(sel_in, k, "this source does not expose it") for k in
              ("account_age", "rating", "prior_listings", "complaint_signals", "response_history", "inconsistencies")}
    seller["confidence"] = sel_in.get("confidence") if sel_in.get("confidence") in ("high", "medium", "low") else "UNKNOWN"
    econ = _economics(item, enr)
    va_in = enr.get("value_add") or {}
    plan = _from_block(va_in, "plan", "no value-add plan from lane C yet")
    risks = []
    for r in va_in.get("model_specific_risks") or []:
        if r.get("basis") in ("FACT", "INFERENCE", "RECOMMENDATION") and r.get("risk"):
            risks.append({k: v for k, v in r.items() if k in ("risk", "kind", "basis", "source", "provenance_id")})
    se_in = enr.get("seasonality") or {}
    seasonality = {"demand_now": _from_block(se_in, "demand_now", "no seasonality evidence for this category"),
                   "hold_likely": _from_block(se_in, "hold_likely", "depends on seasonality"),
                   "note": _from_block(se_in, "note", "no seasonality note")}
    if isinstance(se_in.get("peak_months"), list):
        seasonality["peak_months"] = [int(m) for m in se_in["peak_months"]]
    events = _stage_events(item, receipts, areqs)
    timeline = _timeline(events)
    state_stage = {"AWAITING_APPROVAL": "AWAITING MICHAEL", "HELD": "AWAITING MICHAEL", "ARCHIVED": "PASSED", "REJECTED": "PASSED",
                   "OUTCOME_RECORDED": "CLOSED", "LEARNED": "CLOSED"}.get(item["state"])
    current = state_stage or (timeline[-1]["stage"] if timeline else "DISCOVERED")
    rec = item.get("recommendation") or {}
    why = [str(x) for x in (enr.get("why") or [])]  # lane C's plain-English reasons come first
    why += _fact_reasons(item, econ, la, _logistics(item, enr, profile))
    why += [x for x in (rec.get("rationale") or []) if not _machine_noise(x)]
    if not why:
        why = ["Discovered; no reasoning yet (still being researched)."]
    card: dict[str, Any] = {
        "card_version": CARD_VERSION, "item_id": item["item_id"], "generated_at": iso(now or utcnow()),
        "item": {"title": n["title"], "make_model": _from_block(enr, "make_model", "not extracted from the listing"),
                 "category": item["category"], "type": item["type"],
                 "asking_price": econ["asking_price"],
                 "location": _datum(loc_s, "FACT", provenance_id=src0.get("provenance_id")) if loc_s else _unknown("listing has no location"),
                 "distance_miles": (_datum(float(miles), "FACT", unit="miles") if miles is not None else _from_block(enr, "distance_miles", "no distance computed")),
                 "source": src0["source"], "url": src0["url"]},
        "listing_activity": la, "seller": seller, "why": why, "economics": econ,
        "value_add_plan": {"plan": plan, "model_specific_risks": risks},
        "seasonality": seasonality, "logistics": _logistics(item, enr, profile),
        "recommendation": _recommend(item, areqs, current),
        "status": {"current": current, "timeline": timeline},
        "activity_trail": _trail(item, receipts, areqs), "unknowns": [],
    }
    unk: list[str] = []
    _collect_unknowns("", {k: v for k, v in card.items() if k not in ("activity_trail", "status", "why", "unknowns")}, unk)
    card["unknowns"] = sorted(set(unk))
    body = {k: v for k, v in card.items() if k not in ("generated_at", "card_hash")}
    card["card_hash"] = sha256_of(body)
    return card


def validate_card(card: dict) -> list[str]:
    """Schema errors (card.schema.json) + honesty/lint rules. Empty list = a card Michael can be shown."""
    errs = schemas.errors("card", card)
    plan = card["value_add_plan"]["plan"]
    texts = [str(plan.get("value", ""))] if not _is_unknown(plan) else []
    texts += [r["risk"] for r in card["value_add_plan"]["model_specific_risks"] if not r.get("source")]
    for t in texts:
        for hit in elementary_advice(t):
            errs.append(f"value_add_plan: elementary advice not allowed without a model-specific source: {hit!r}")
    for r in card["value_add_plan"]["model_specific_risks"]:
        if r["basis"] != "FACT" and not r.get("source") and not r.get("provenance_id"):
            errs.append(f"model-specific risk without source/provenance: {r['risk']!r}")
    if card["recommendation"]["waiting"] and card["recommendation"]["action"] in ("PASS",):
        errs.append("a PASS cannot be 'waiting'")
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
    lines = [sep, i["title"].upper(), f"{_fmt(i['location'])} — {_fmt(i['asking_price'], True)}   [{i['source']}]", ""]
    lines += [f"POSTED: {ago(la['posted_at'])}   UPDATED: {ago(la['updated_at'])}   AGE: {_fmt(la['age_days'])} days"
              if la["age_days"]["value"] != "UNKNOWN" else f"POSTED: {ago(la['posted_at'])}   UPDATED: {ago(la['updated_at'])}",
              f"STALE RISK: {_fmt(la['stale_risk'])}" + (f"   SUSPECTED RELIST: {_fmt(la['suspected_relist'])}" if la['suspected_relist']['value'] != 'UNKNOWN' else "")]
    lines += [f"  · {a}" for a in la["recent_activity"]]
    s = card["seller"]
    lines += ["", "SELLER: " + "; ".join(f"{k.replace('_', ' ')} {_fmt(s[k])}" for k in ("account_age", "rating", "prior_listings", "response_history")
                                         if s[k]["value"] != "UNKNOWN") + (f" (confidence {s['confidence']})" if s["confidence"] != "UNKNOWN" else "")
              if any(s[k]["value"] != "UNKNOWN" for k in ("account_age", "rating", "prior_listings", "response_history"))
              else "SELLER: UNKNOWN (this source does not expose seller history)"]
    lines += ["", "WHY IT'S INTERESTING:"] + [f"  {w}" for w in card["why"]]
    lines += ["", "ESTIMATED NUMBERS:",
              f"  Ask: {_fmt(e['asking_price'], True)}   Opening offer: {_fmt(e['recommended_opening_offer'], True)}   Max acquisition: {_fmt(e['maximum_acquisition_price'], True)}",
              f"  Repair/material: {_fmt(e['expected_repair_material_cost'], True)}   Transport: {_fmt(e['transport_cost'], True)}   Cash at risk: {_fmt(e['total_cash_at_risk'], True)}",
              f"  Resale: conservative {_fmt(e['resale_conservative'], True)} / likely {_fmt(e['resale_likely'], True)} / optimistic {_fmt(e['resale_optimistic'], True)}",
              f"  Gross {_fmt(e['expected_gross_profit'], True)}   Net {_fmt(e['expected_net_profit'], True)}   Per hour {_fmt(e['expected_profit_per_hour'], True)}   Days to cash {_fmt(e['expected_days_to_cash'])}"]
    plan = card["value_add_plan"]
    lines += ["", f"VALUE-ADD PLAN: {_fmt(plan['plan'])}"] + [f"  ! {x['risk']} [{x['basis']}{', ' + x['source'] if x.get('source') else ''}]" for x in plan["model_specific_risks"]]
    se = card["seasonality"]
    lines += ["", f"SEASONALITY: {_fmt(se['note'])}" + (f" (demand now: {_fmt(se['demand_now'])}; hold likely: {_fmt(se['hold_likely'])})" if se['demand_now']['value'] != 'UNKNOWN' else "")]
    mode = lg["transport_mode"]["value"]
    lines += ["", "TRANSPORT: " + {"fits_truck": "Fits truck. No trailer required.", "requires_trailer": "Requires a trailer (not owned; borrowing is possible but MUST be confirmed with the lender before pickup)."}.get(mode, "UNKNOWN (not yet classified)")
              + f" Trip: {_fmt(lg['trip_miles_round_trip'])} mi round trip, {_fmt(lg['trip_hours'])} h, fuel {_fmt(lg['fuel_cost'], True)}, difficulty {_fmt(lg['difficulty'])}."]
    st = card["status"]
    lines += ["", "SYSTEM STATUS: " + " → ".join(t["stage"].title() for t in st["timeline"]) + f"   [now: {st['current']}]"]
    lines += [f"  {t['at'][:16]}  {t['stage']}" for t in st["timeline"]]
    lines += ["", f"RECOMMENDATION: {r['action']}" + (" / WAIT FOR RESPONSE" if r["waiting"] else "") + (" (needs step-up approval)" if r.get("requires_step_up") else ""), f"  {r['why']}"]
    if card["unknowns"]:
        lines += ["", f"UNKNOWN ({len(card['unknowns'])}): " + ", ".join(card["unknowns"])]
    lines += ["", "ACTIVITY (every action has a receipt):"] + [f"  {t['at'][:16]}  {t['agent']}: {t['what']} — {t['why'][:90]}  → {t['result']}  [{t['receipt_id']}]" for t in card["activity_trail"]]
    lines += [f"  NEXT: {card['activity_trail'][-1]['next_action']}"] if card["activity_trail"] else []
    return "\n".join(lines + [sep])
