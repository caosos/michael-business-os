"""Card view-model: everything Michael needs to see WHY the system is asking.

Pure data (no HTML) so the same model backs the web page and the JSON API.
"""

from .approvals import HOLD_PRESETS, needs_step_up
from .util import parse_iso


def _prov_kind(p):
    if p.get("approval_id") and p.get("actor_type") == "human":
        return "human decision"
    if p.get("source_uri"):
        return "external source"
    if p.get("model_id"):
        return "model output"
    if p.get("tool_name"):
        return "deterministic tool"
    return "unresolved"


def _prov_summary(p):
    if p is None:
        return None
    k = _prov_kind(p)
    if k == "external source":
        what = f"{p['source_uri']} (fetched {p.get('fetched_at')})"
    elif k == "model output":
        what = f"{p['model_id']} {p.get('model_version')} · prompt {p['prompt_hash'][:19]}…"
    elif k == "deterministic tool":
        what = f"{p['tool_name']} {p.get('tool_version')}" + (f" · config {p['config_version']}" if p.get("config_version") else "")
    elif k == "human decision":
        what = f"{p.get('human_actor')} · {p['approval_id']}"
    else:
        what = "—"
    return {
        "id": p["provenance_id"], "kind": k, "basis": p.get("basis"),
        "who": p.get("agent_name") or p.get("human_actor") or p.get("actor_type"), "what": what,
        "created_at": p.get("created_at"),
    }


def economics_summary(item):
    sc = ((item.get("scores") or {}).get("scorecard") or {})
    d = sc.get("derived") or {}
    e = item.get("economics") or {}
    rows = []
    if item["type"] == "flip":
        acq, res, reh = e.get("acquisition", {}), e.get("resale", {}), e.get("rehab", {})
        rows += [
            ("Ask", acq.get("ask_price"), "$"), ("Expected buy", acq.get("expected_buy_price"), "$"),
            ("Parts + materials", (reh.get("parts_cost") or 0) + (reh.get("materials_cost") or 0) or None, "$"),
            ("Target sell", res.get("target_sell_price"), "$"),
            ("Comp range", f"${res['comp_price_low']:,}–${res['comp_price_high']:,}" if "comp_price_low" in res and "comp_price_high" in res else None, ""),
            ("Labor hours", (reh.get("labor_hours") or 0) + (reh.get("admin_hours") or 0) or None, "h"),
            ("Hold days", (e.get("holding") or {}).get("expected_hold_days"), "d"),
        ]
    else:
        job = e.get("job", {})
        rows += [
            ("Quoted revenue", job.get("quoted_revenue"), "$"), ("Materials", job.get("materials_cost"), "$"),
            ("Labor + admin hours", (job.get("labor_hours") or 0) + (job.get("admin_hours") or 0) or None, "h"),
            ("Win probability", job.get("win_prob"), "%"), ("Deposit rate", job.get("deposit_rate"), "%"),
        ]
    rows += [
        ("EV net profit", d.get("ev_net_profit"), "$"), ("EV $/Michael-hour", d.get("ev_profit_per_hour"), "$"),
        ("Max loss", d.get("max_loss"), "$"), ("Cash tied up", d.get("cash_tied_up"), "$"),
    ]
    return [{"label": l, "value": v, "unit": u} for l, v, u in rows if v not in (None, "")]


def card(store, areq_id, now):
    areq = store.action_request(areq_id)
    if areq is None:
        return None
    item = store.item(areq["item_id"])
    rec = item.get("recommendation") or {}
    sc = ((item.get("scores") or {}).get("scorecard") or {})
    approvals = store.approvals_for(areq_id)
    receipts = store.receipts(areq_id=areq_id)
    item_receipts = [r for r in store.receipts(item_id=item["item_id"]) if r["type"] == "ITEM_STATE_CHANGED"]
    prov_ids = list(dict.fromkeys(
        list(areq["provenance_ids"]) + list(item.get("provenance_ids", []))
        + [s["provenance_id"] for s in item.get("sources", [])]
        + [r["provenance_id"] for r in item.get("research", [])]
        + ([rec["provenance_id"]] if rec.get("provenance_id") else [])
        + [p for a in approvals for r in receipts if r.get("approval_id") == a["approval_id"] for p in r["provenance_ids"]]
    ))
    provenance = [_prov_summary(store.provenance(p)) or {"id": p, "kind": "MISSING", "what": "not found in store"} for p in prov_ids]
    successors = [a for a in store.action_requests_for_item(item["item_id"]) if a.get("derived_from") == areq_id]
    action_summary = next((pa["summary"] for pa in rec.get("proposed_actions", []) if pa["capability"] == areq["capability"]), None)
    gates = sc.get("gates") or {}
    hold = store.hold_timer(areq_id)
    expires = parse_iso(areq["expires_at"])
    return {
        "item": item,
        "areq": areq,
        "lane": item["type"],
        "title": item["normalized"]["title"],
        "category": item["category"],
        "subcategory": item.get("subcategory"),
        "location": item["normalized"].get("location") or {},
        "verdict": rec.get("verdict"),
        "composite": sc.get("composite"),
        "confidence": rec.get("confidence", (sc.get("derived") or {}).get("confidence")),
        "rationale": rec.get("rationale", []),
        "reasons": sc.get("reasons", []),
        "cheapest_decisive_evidence": rec.get("cheapest_decisive_evidence") or sc.get("cheapest_decisive_evidence"),
        "economics": economics_summary(item),
        "risk": {
            "risk_score": (sc.get("sub_scores") or {}).get("risk_score"),
            "max_loss": (sc.get("derived") or {}).get("max_loss"),
            "reversibility": areq["reversibility"],
            "tier": areq["tier"],
            "untrusted_inputs_present": areq.get("untrusted_inputs_present", False),
            "source_tos_risk": sorted({s.get("tos_risk") for s in item["sources"] if s.get("tos_risk")}),
            "failed_gates": [g for g, ok in gates.items() if not ok],
            "flags": item["normalized"].get("flags", []),
        },
        "sources": item["sources"],
        "research": item.get("research", []),
        "provenance": provenance,
        "action_summary": action_summary,
        "step_up": needs_step_up(areq),
        "decidable": areq["status"] in ("pending_approval", "held") and expires > now,
        "expires_in_hours": round((expires - now).total_seconds() / 3600, 1),
        "approvals": approvals,
        "receipts": receipts,
        "item_receipts": item_receipts,
        "successors": [a["action_request_id"] for a in successors],
        "hold": hold,
        "hold_presets": HOLD_PRESETS,
    }


def queue(store, now):
    rows = []
    for a in store.action_requests():
        item = store.item(a["item_id"])
        sc = ((item.get("scores") or {}).get("scorecard") or {})
        d = sc.get("derived") or {}
        rec = item.get("recommendation") or {}
        rows.append({
            "areq_id": a["action_request_id"], "status": a["status"], "lane": item["type"],
            "category": item["category"], "title": item["normalized"]["title"], "verdict": rec.get("verdict"),
            "confidence": rec.get("confidence", d.get("confidence")), "ev": d.get("ev_net_profit"),
            "pph": d.get("ev_profit_per_hour"), "capability": a["capability"],
            "summary": next((pa["summary"] for pa in rec.get("proposed_actions", []) if pa["capability"] == a["capability"]), a["capability"]),
            "reversibility": a["reversibility"], "expires_at": a["expires_at"],
            "expires_in_hours": round((parse_iso(a["expires_at"]) - now).total_seconds() / 3600, 1),
            "derived_from": a.get("derived_from"),
            "hold_until": (store.hold_timer(a["action_request_id"]) or {}).get("hold_until"),
        })
    return {
        "pending": [r for r in rows if r["status"] == "pending_approval"],
        "held": [r for r in rows if r["status"] == "held"],
        "closed": [r for r in rows if r["status"] not in ("pending_approval", "held")][::-1],
    }
