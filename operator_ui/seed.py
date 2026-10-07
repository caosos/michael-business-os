"""ILLUSTRATIVE demo data built from the frozen contract examples (not real listings).

Three opportunities so the queue shows both lanes:
  * flip    / trailer   — YES verdict, irreversible seller email with an offer (step-up)
  * service / drywall   — MAYBE verdict, ask the customer for photos (cheapest decisive evidence)
  * flip    / generator — YES verdict, low confidence, reversible inspection booking
"""

import copy
import json
from datetime import timedelta

from .contracts import CONTRACTS_DIR
from .util import iso, sha256_of

AGENT_DRAFTER = "agent-06-communications"


def _ex(name):
    return json.loads((CONTRACTS_DIR / "examples" / name).read_text())


def _id(prefix, n):
    return f"{prefix}_01JA{n:022d}"


def _prov(n, now, **kw):
    return dict({"provenance_id": _id("prov", n), "created_at": iso(now)}, **kw)


def build(now):
    """Return (items, action_requests, provenance) — all contract-valid."""
    t0 = now - timedelta(hours=2)
    provs = [
        _prov(1, t0, actor_type="agent", agent_name="agent-02-opportunity", basis="FACT",
              source_uri="https://example.invalid/listing/1", fetched_at=iso(t0)),
        _prov(2, t0, actor_type="agent", agent_name="agent-02-opportunity", basis="FACT",
              source_uri="https://example.invalid/comps", fetched_at=iso(t0)),
        _prov(3, t0, actor_type="agent", agent_name="agent-03-economics", basis="RECOMMENDATION",
              tool_name="agent-03-scoring-engine", tool_version="0.0.0-illustrative", config_version="2026.10.0"),
        _prov(4, t0, actor_type="agent", agent_name=AGENT_DRAFTER, basis="RECOMMENDATION",
              model_id="illustrative-model", model_version="n/a", prompt_hash=sha256_of({"template": "seller_condition_q_v1"})),
        _prov(10, t0, actor_type="external", basis="FACT",
              source_uri="https://example.invalid/form/2", fetched_at=iso(t0)),
        _prov(11, t0, actor_type="agent", agent_name="agent-03-economics", basis="RECOMMENDATION",
              tool_name="agent-03-scoring-engine", tool_version="0.0.0-illustrative", config_version="2026.10.0"),
        _prov(12, t0, actor_type="agent", agent_name=AGENT_DRAFTER, basis="RECOMMENDATION",
              model_id="illustrative-model", model_version="n/a", prompt_hash=sha256_of({"template": "customer_photo_request_v1"})),
        _prov(20, t0, actor_type="agent", agent_name="agent-02-opportunity", basis="FACT",
              source_uri="https://example.invalid/listing/3", fetched_at=iso(t0)),
        _prov(21, t0, actor_type="agent", agent_name="agent-03-economics", basis="RECOMMENDATION",
              tool_name="agent-03-scoring-engine", tool_version="0.0.0-illustrative", config_version="2026.10.0"),
    ]

    trailer = _ex("item-flip-trailer.example.json")
    trailer.update(created_at=iso(t0), state="AWAITING_APPROVAL")
    trailer["recommendation"]["expires_at"] = iso(now + timedelta(days=2))

    drywall = _ex("item-service-drywall.example.json")
    drywall.update(created_at=iso(t0), state="AWAITING_APPROVAL", action_request_ids=[_id("areq", 2)])
    drywall["recommendation"]["proposed_actions"] = [{
        "capability": "comms.email.send", "summary": "Ask the customer for 2 photos of the damaged wall",
        "reversibility": "irreversible", "estimated_cost": {"amount": 0, "currency": "USD"},
    }]

    gen = copy.deepcopy(trailer)
    gen.update(item_id=_id("itm", 3), category="generator", subcategory="7500W portable, won't start",
               dedup_key="generator|300-600|cell-34.75-92.29", action_request_ids=[_id("areq", 3)],
               provenance_ids=[_id("prov", 20), _id("prov", 21)])
    gen.pop("content_hash", None)
    gen["sources"][0].update(source="facebook_marketplace", source_listing_id="EXAMPLE-0003",
                             url="https://example.invalid/listing/3", ingestion_method="manual",
                             tos_risk="high", provenance_id=_id("prov", 20))
    gen["normalized"].update(title="7500W generator, won't start (carb?)",
                             price={"amount": 350, "currency": "USD", "type": "fixed"},
                             location={"city": "Little Rock", "state": "AR", "road_miles_one_way": 41, "geo_tier": 1})
    gen["research"] = [{
        "finding": "Only 1 sold comp found; carb-vs-engine fault unknown (illustrative)",
        "field": "rehab.repair_success_prob", "basis": "INFERENCE", "provenance_id": _id("prov", 21),
    }]
    gen["scores"]["scorecard_id"] = _id("scr", 3)
    sc = gen["scores"]["scorecard"]
    sc["derived"].update(ev_net_profit=240.0, ev_profit_per_hour=52.0, confidence=0.55, max_loss=310.0, cash_tied_up=380.0)
    sc["sub_scores"].update(risk_score=48, conf_score=55)
    sc.update(composite=60.4, reasons=["ILLUSTRATIVE ONLY", "EV profit/hour 52 above $40 floor, below $65 target",
                                       "single comp — low evidence quality"])
    gen["recommendation"] = {
        "recommendation_id": _id("rec", 3), "verdict": "YES", "confidence": 0.55,
        "proposed_actions": [{"capability": "schedule.appointment.create",
                              "summary": "Book a 30-min inspection Saturday 10am (no offer made)",
                              "reversibility": "reversible", "estimated_cost": {"amount": 0, "currency": "USD"}}],
        "rationale": ["Composite 60.4 >= 60 but confidence 0.55 — inspect before any offer"],
        "cheapest_decisive_evidence": "Does it run on starter fluid? (carb vs engine)",
        "provenance_id": _id("prov", 21), "expires_at": iso(now + timedelta(days=1)),
    }

    def areq(n, item, capability, category, payload, reversibility, untrusted, prov_ids, hours, target):
        return {
            "action_request_id": _id("areq", n), "item_id": item["item_id"],
            "recommendation_id": item["recommendation"]["recommendation_id"],
            "created_at": iso(t0), "proposed_by": AGENT_DRAFTER, "on_behalf_of": "michael",
            "capability": capability, "category": category, "payload": payload,
            "payload_hash": sha256_of(payload), "idempotency_key": f"{_id('areq', n)}:exec",
            "estimated_cost": {"amount": 0, "currency": "USD"}, "reversibility": reversibility,
            "untrusted_inputs_present": untrusted, "tier": 0, "score_ref": item["scores"]["scorecard_id"],
            "status": "pending_approval", "expires_at": iso(now + timedelta(hours=hours)),
            "provenance_ids": prov_ids, "target": target,
        }

    areqs = [
        areq(1, trailer, "comms.email.send", "email", {
            "to_ref": "relay:EXAMPLE-0001", "template_id": "seller_condition_q_v1", "offer": 1050,
            "subject": "Your 6x12 enclosed trailer",
            "body": "Hi — this is an automated assistant writing for Michael. Is the floor solid and do both "
                    "axles/bearings turn freely? If so, would you take $1,050 cash this week?",
        }, "irreversible", True, [_id("prov", 1), _id("prov", 3), _id("prov", 4)], 48,
            {"kind": "listing_relay", "ref": "relay:EXAMPLE-0001"}),
        areq(2, drywall, "comms.email.send", "email", {
            "to_ref": "party:EXAMPLE-0002", "template_id": "customer_photo_request_v1",
            "subject": "Photos for your drywall patch quote",
            "body": "Thanks for reaching out. Could you send two photos of the damaged area, one up close "
                    "and one from across the room? Then I can give you a firm quote.",
        }, "irreversible", True, [_id("prov", 10), _id("prov", 11), _id("prov", 12)], 72,
            {"kind": "party", "ref": "party:EXAMPLE-0002"}),
        areq(3, gen, "schedule.appointment.create", "scheduling", {
            "calendar": "michael-local", "title": "Inspect 7500W generator (Little Rock)",
            "start_local": "Saturday 10:00", "duration_min": 30, "notify_counterparty": False,
        }, "reversible", True, [_id("prov", 20), _id("prov", 21)], 30,
            {"kind": "calendar", "ref": "calendar:michael-local"}),
    ]
    trailer["action_request_ids"] = [_id("areq", 1)]
    return [trailer, drywall, gen], areqs, provs


def seed(store, now):
    """Insert demo data in one transaction (with ACTION_PROPOSED/APPROVAL_REQUESTED receipts)."""
    if store.action_requests():
        return False
    items, areqs, provs = build(now)
    with store.tx() as tx:
        for p in provs:
            tx.add_provenance(p)
        for it in items:
            tx.put_item(it)
        for a in areqs:
            tx.put_action_request(a)
            for rtype, intent in (("ACTION_PROPOSED", "drafted from recommendation (ILLUSTRATIVE seed)"),
                                  ("APPROVAL_REQUESTED", "tier 0: Michael must decide")):
                tx.add_receipt(
                    now, type=rtype, actor={"type": "agent", "id": AGENT_DRAFTER}, intent=intent, effect="none",
                    item_id=a["item_id"], action_request_id=a["action_request_id"], capability=a["capability"],
                    payload_hash=a["payload_hash"], idempotency_key=f"{a['action_request_id']}:{rtype}",
                    provenance_ids=a["provenance_ids"], after_state={"status": a["status"]}, details={"kind": "generic"},
                )
    return True
