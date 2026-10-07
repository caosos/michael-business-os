"""The spine on lane D's canonical store (task A-01 phase 2; rulings R1/R2/R12).

Same function names and signatures as `mbos.spine` (the reference backend); the workflows call whichever
module `mbos.runtime` selects (`Settings.state_backend`). Every write goes through Agent 04's SQL API via
`Pg04Ledger`, so lane D's guarantees apply: state + receipt in one transaction, the receipt trigger writes the
outbox, gapless MBOS-RH-1 chain (ADR-0010), role-checked action-status edges, step-up on irreversible YES,
FROZEN-by-default PANIC.

Idempotency keys are deterministic: item writes key on the item's current `version`, action writes on the
request id + event, so a DBOS replay of a transaction step can never double-write.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import sqlalchemy as sa

from mbos.adapters.state04 import Pg04Ledger
from mbos.clock import iso, now_iso, parse, utcnow
from mbos.config import settings
from mbos.contracts import ContractViolation
from mbos.contracts.models import ActionRequest, Approval
from mbos.hashing import canonical_json, sha256_of
from mbos.ids import new_id
from mbos.reference.governance import GATEWAY_TOOL, classify_capability
from mbos.spine import (  # shared, backend-independent pieces
    MICHAEL, PAYLOAD_RESERVED, PROPOSED_ACTION_CORE, SPINE_AGENT, DecisionRefused, requires_step_up,
)

L = Pg04Ledger()
SYSTEM = {"type": "system", "id": SPINE_AGENT}
LANE_C = {"type": "agent", "id": "agent-03-economics"}


# ---------------------------------------------------------------- helpers
def _version(conn: sa.Connection, item_id: str) -> int:
    return conn.execute(sa.text("SELECT version FROM mbos.items WHERE item_id = :i FOR UPDATE"), {"i": item_id}).scalar_one()


def _to(conn: sa.Connection, item_id: str, to_state: str, intent: str, prov: list[str], actor: dict = SYSTEM) -> None:
    v = _version(conn, item_id)
    L.transition_item(conn, item_id, to_state, actor, intent, prov, f"{item_id}:v{v}:{to_state}")


def _patch(conn: sa.Connection, item_id: str, patch: dict, intent: str, prov: list[str], actor: dict = SYSTEM,
           receipt_type: str = "ITEM_STATE_CHANGED", extra: Optional[dict] = None) -> None:
    v = _version(conn, item_id)
    L.patch_item(conn, item_id, patch, receipt_type, actor, intent, prov,
                 f"{item_id}:v{v}:{receipt_type}:{sha256_of(patch)[7:19]}", extra=extra)


def _prov(conn: sa.Connection, tool: str, *, basis: str = "FACT", inputs: tuple = (), **kw: Any) -> str:
    return L.record_provenance(conn, actor_type="system", agent_name=SPINE_AGENT, basis=basis, tool_name=tool,
                               tool_version="0.1.0", inputs_used=[{"ref": r} for r in inputs] or None, **kw)


def _areq(conn: sa.Connection, areq_id: str, *, lock: bool = False) -> dict:
    if lock:
        conn.execute(sa.text("SELECT 1 FROM mbos.action_requests WHERE action_request_id = :a FOR UPDATE"), {"a": areq_id})
    return L.load_action_request(conn, areq_id)


def _status(conn: sa.Connection, areq: dict, to: str, rtype: str, intent: str, prov: list[str], *,
            actor: dict = SYSTEM, extra: Optional[dict] = None, tier: Optional[int] = None, key: Optional[str] = None) -> None:
    L.set_action_status(conn, areq["action_request_id"], to, rtype, actor, intent, prov,
                        key or f"{areq['action_request_id']}:{rtype}:{to}", extra=extra, tier=tier)


def _receipt(conn: sa.Connection, areq: dict, rtype: str, intent: str, prov: list[str], key: str, **fields: Any) -> dict:
    return L.append_receipt(conn, {"type": rtype, "actor": fields.pop("actor", SYSTEM), "intent": intent,
                                   "item_id": areq["item_id"], "action_request_id": areq["action_request_id"],
                                   "capability": areq["capability"], "payload_hash": areq["payload_hash"],
                                   "entity_type": "action_request", "entity_id": areq["action_request_id"],
                                   "provenance_ids": prov, "idempotency_key": key, **fields})



# ---------------------------------------------------------------- DISCOVER + NORMALIZE
def _dedup_context(raw: dict, norm: dict) -> dict:
    """A-14: the candidate sighting's source/fetch context for lane B's Deduper (relist + pHash rules)."""
    return {"source": raw["source"], "source_listing_id": raw["source_listing_id"], "url": raw["url"],
            "fetched_at": raw["fetched_at"], "match_hints": norm.get("match_hints")}
def ingest(conn: sa.Connection, raw: dict, norm: Optional[dict], adapter_name: str, adapter_version: str,
           components: Any) -> dict:
    from mbos.interfaces import NormalizedListing

    if norm is None:
        return {"item_id": None, "created": False, "merged": False, "dropped": True}
    ident = {"source": raw["source"]}
    ident.update({"source_listing_id": raw["source_listing_id"]} if raw["source_listing_id"] else {"url": raw["url"]})
    seen = conn.execute(sa.text("SELECT item_id FROM mbos.items WHERE doc->'sources' @> CAST(:s AS jsonb) LIMIT 1"),
                        {"s": canonical_json([ident]).decode()}).scalar_one_or_none()
    if seen is not None:
        return {"item_id": seen, "created": False, "merged": False, "dropped": False}
    existing = None
    for (item_id,) in conn.execute(sa.text("SELECT item_id FROM mbos.items WHERE dedup_key = :k ORDER BY created_at"),
                                   {"k": norm["dedup_key"]}).all():
        doc = L.load_item(conn, item_id)
        if components.deduper.is_duplicate(doc, NormalizedListing(**norm), context=_dedup_context(raw, norm)):
            existing = doc
            break
    raw_bytes = canonical_json(raw["payload"])
    raw_ref = conn.execute(sa.text("SELECT mbos.put_artifact(:c, 'application/json')"), {"c": raw_bytes}).scalar_one()
    src_prov = L.record_provenance(conn, actor_type="agent", agent_name=adapter_name, basis="FACT", source_uri=raw["url"],
                                   fetched_at=raw["fetched_at"], tool_name=adapter_name, tool_version=adapter_version,
                                   inputs_used=[{"ref": raw_ref, "hash": raw_ref}])
    sighting = {k: v for k, v in {
        "source": raw["source"], "source_listing_id": raw["source_listing_id"], "url": raw["url"],
        "ingestion_method": raw["ingestion_method"], "tos_risk": raw["tos_risk"], "first_seen_at": raw["fetched_at"],
        "raw_ref": raw_ref, "provenance_id": src_prov}.items() if v is not None}
    actor = {"type": "agent", "id": adapter_name}
    if existing is not None:
        _patch(conn, existing["item_id"], {"sources": existing["sources"] + [sighting]},
               f"dedup: merged duplicate sighting from {raw['source']}", [src_prov], actor)
        return {"item_id": existing["item_id"], "created": False, "merged": True, "dropped": False}
    item_id = new_id("itm")
    doc = {k: v for k, v in {
        "item_id": item_id, "schema_version": "1.0.0", "type": norm["type"], "category": norm["category"],
        "subcategory": norm.get("subcategory"), "opportunity_kind": norm.get("opportunity_kind"), "state": "DISCOVERED",
        "created_at": raw["fetched_at"], "sources": [sighting], "dedup_key": norm["dedup_key"],
        "content_hash": norm.get("content_hash"), "normalized": norm["normalized"], "provenance_ids": [src_prov],
    }.items() if v is not None}
    L.create_item(conn, doc, actor, f"discovered via {adapter_name}", [src_prov], f"{item_id}:create")
    norm_prov = _prov(conn, f"{adapter_name}.normalizer", inputs=(raw_ref,), derived_from=[src_prov])
    _to(conn, item_id, "NORMALIZED", "normalized to Item v1", [norm_prov], actor)
    if norm.get("economics"):
        _patch(conn, item_id, {"economics": norm["economics"]}, "source-supplied economics", [norm_prov], actor)
    return {"item_id": item_id, "created": True, "merged": False, "dropped": False}


def read_item(conn: sa.Connection, item_id: str) -> dict:
    return L.load_item(conn, item_id)


# ---------------------------------------------------------------- RESEARCH / SCORE / RECOMMEND
def record_research(conn: sa.Connection, item_id: str, rr: dict, components: Any) -> dict:
    existing = set(conn.execute(sa.text("SELECT provenance_id FROM mbos.provenance WHERE provenance_id = ANY(:ids)"),
                                {"ids": [p["provenance_id"] for p in rr["provenance_records"]]}).scalars())
    for doc in rr["provenance_records"]:
        if doc["provenance_id"] not in existing:
            L.record_provenance(conn, **doc)
            existing.add(doc["provenance_id"])
    prov = [p["provenance_id"] for p in rr["provenance_records"]] or [_prov(conn, "mbos.spine_d.record_research")]
    if read_item(conn, item_id)["state"] == "NORMALIZED":
        _to(conn, item_id, "RESEARCHING", "RESEARCH: gathering evidence (comps) and estimating", prov, LANE_C)
    patch = {k: v for k, v in {"economics": rr.get("economics"), "research": rr.get("research") or None}.items() if v}
    if patch:
        _patch(conn, item_id, patch, f"RESEARCH result: {rr['next_state']}", prov, LANE_C)
    return {"next_state": rr["next_state"], "gaps": rr.get("gaps", [])}


def record_score(conn: sa.Connection, item_id: str, sr: dict) -> dict:
    item = read_item(conn, item_id)
    prov = L.record_provenance(conn, actor_type="agent", agent_name=sr["tool_name"], basis="INFERENCE",
                               tool_name=sr["tool_name"], tool_version=sr["tool_version"],
                               config_version=sr["scoring_config_version"],
                               inputs_used=[{"ref": item_id, "hash": sr["inputs_hash"]}],
                               derived_from=[s["provenance_id"] for s in item["sources"]], confidence=sr["confidence"])
    if item["state"] == "NORMALIZED":
        _to(conn, item_id, "RESEARCHING", "RESEARCH: scoring on the inputs supplied so far", [prov], LANE_C)
    scores = {"scorecard_id": sr.get("scorecard_id") or new_id("scr"), "inputs_hash": sr["inputs_hash"],
              "scorecard": sr["scorecard"]}
    _to(conn, item_id, "SCORED", "scored", [prov], LANE_C)
    _patch(conn, item_id, {"scores": scores}, f"scorecard {scores['scorecard_id']}: {sr['verdict']}", [prov], LANE_C,
           receipt_type="SCORE_RECORDED", extra={"inputs_hash": sr["inputs_hash"],
                                                 "tool_name": f"{sr['tool_name']}@{sr['tool_version']}"})
    rec = {k: v for k, v in {
        "recommendation_id": sr.get("recommendation_id") or new_id("rec"), "verdict": sr["verdict"],
        "proposed_actions": sr.get("proposed_actions") or None, "rationale": sr["rationale"],
        "confidence": sr["confidence"], "cheapest_decisive_evidence": sr.get("cheapest_decisive_evidence"),
        "alert": sr.get("alert"), "provenance_id": prov}.items() if v is not None}
    _to(conn, item_id, "RECOMMENDED", f"recommended {sr['verdict']}", [prov], LANE_C)
    _patch(conn, item_id, {"recommendation": rec}, f"machine verdict {sr['verdict']} (not Michael's decision)", [prov],
           LANE_C, receipt_type="RECOMMENDATION_RECORDED", extra={"inputs_hash": sr["inputs_hash"]})
    return {"verdict": sr["verdict"], "recommendation_id": rec["recommendation_id"], "scorecard_id": scores["scorecard_id"]}


def route_recommendation(conn: sa.Connection, item_id: str, components: Any) -> dict:
    item = read_item(conn, item_id)
    rec = item["recommendation"]
    prov = _prov(conn, "mbos.spine_d.route_recommendation", basis="RECOMMENDATION",
                 inputs=(item_id, rec["recommendation_id"]), derived_from=[rec["provenance_id"]])
    if rec["verdict"] == "PASS":
        _to(conn, item_id, "ARCHIVED", "machine verdict PASS: archived", [prov])
        return {"verdict": "PASS", "action_request_id": None}
    proposed = rec.get("proposed_actions") or (components.planner.plan(item) if rec["verdict"] == "YES" else [])
    if rec["verdict"] == "MAYBE" or not proposed:
        _to(conn, item_id, "RESEARCHING", f"MAYBE: needs {rec.get('cheapest_decisive_evidence') or 'more evidence'}", [prov])
        return {"verdict": "MAYBE", "action_request_id": None}
    areq = _propose(conn, item, proposed[0], prov, components)
    _to(conn, item_id, "AWAITING_APPROVAL", f"awaiting Michael: {areq['capability']}", [prov])
    return {"verdict": "YES", "action_request_id": areq["action_request_id"]}


def _classify_and_present(conn: sa.Connection, areq: dict, prov: list[str], components: Any, actor: dict) -> dict:
    """propose → POLICY_DECIDED → APPROVAL_REQUESTED, all through lane D's API."""
    decision = components.pdp.decide(areq)
    areq = {**areq, "tier": decision.tier, "category": decision.category, "policy_decision_ref": decision.policy_version}
    ActionRequest.from_doc({**areq, "status": "drafted"})
    L.propose_action(conn, {k: v for k, v in areq.items() if k != "status"}, actor,
                     f"proposed {areq['capability']}: {areq['payload']['summary']}", f"{areq['action_request_id']}:propose")
    _status(conn, areq, "classified", "POLICY_DECIDED", f"PDP: {decision.decision}, tier {decision.tier} — {decision.reason}",
            prov, extra={"policy_decision_ref": decision.policy_version,
                         "details": {"kind": "generic", "decision": decision.decision, "tier": decision.tier}},
            tier=decision.tier)
    if decision.decision == "deny":
        _status(conn, areq, "rejected", "POLICY_DECIDED", "PDP denied", prov, key=f"{areq['action_request_id']}:deny")
        return _areq(conn, areq["action_request_id"])
    _status(conn, areq, "pending_approval", "APPROVAL_REQUESTED", "presented to Michael: YES / NO / MODIFY / HOLD", prov)
    return _areq(conn, areq["action_request_id"])


def _propose(conn: sa.Connection, item: dict, pa: dict, prov: str, components: Any) -> dict:
    areq_id = new_id("areq")
    category, _ = classify_capability(pa["capability"])
    counterparty = item["normalized"].get("counterparty") or {}
    extension = {k: v for k, v in pa.items() if k not in PROPOSED_ACTION_CORE and k not in PAYLOAD_RESERVED}
    payload = {**extension, "capability": pa["capability"], "summary": pa["summary"], "item_id": item["item_id"],
               "recommendation_id": item["recommendation"]["recommendation_id"],
               "target": {"kind": counterparty.get("role", "counterparty"), "ref": item["sources"][0]["url"]},
               "dry_run": True}
    now = utcnow()
    expires = now + timedelta(hours=settings().approval_ttl_hours)
    if item["normalized"].get("ends_at") and parse(item["normalized"]["ends_at"]) < expires:
        expires = parse(item["normalized"]["ends_at"])
    areq = {k: v for k, v in {
        "action_request_id": areq_id, "item_id": item["item_id"],
        "recommendation_id": item["recommendation"]["recommendation_id"], "created_at": iso(now),
        "proposed_by": SPINE_AGENT, "on_behalf_of": "michael", "capability": pa["capability"], "category": category,
        "payload": payload, "payload_hash": sha256_of(payload), "idempotency_key": f"act:{areq_id}",
        "estimated_cost": pa.get("estimated_cost") or {"amount": 0, "currency": "USD"}, "reversibility": pa["reversibility"],
        "untrusted_inputs_present": True, "tier": 0, "score_ref": item["scores"]["scorecard_id"], "status": "drafted",
        "expires_at": iso(expires), "provenance_ids": [prov], "target": payload["target"]}.items() if v is not None}
    return _classify_and_present(conn, areq, [prov], components, SYSTEM)


# ---------------------------------------------------------------- APPROVE
def decide(conn: sa.Connection, action_request_id: str, decision: str, payload_hash_seen: str, components: Any, *,
           decider: str = "michael", channel: str = "cli", reason: Optional[str] = None, hold: Optional[dict] = None,
           payload_changes: Optional[dict] = None, new_payload: Optional[dict] = None,
           auth_context: Optional[dict] = None) -> dict:
    try:
        areq = _areq(conn, action_request_id, lock=True)
    except sa.exc.NoResultFound:
        raise DecisionRefused(f"unknown action request {action_request_id}") from None
    if areq["status"] not in ("pending_approval", "held"):
        raise DecisionRefused(f"{action_request_id} is {areq['status']}; decisions are accepted only while pending or held")
    if payload_hash_seen != areq["payload_hash"]:
        raise DecisionRefused("payload_hash_seen does not match the request — re-read the request before deciding")
    if parse(areq["expires_at"]) <= utcnow():
        raise DecisionRefused(f"{action_request_id} expired at {areq['expires_at']}")
    if decision == "YES" and requires_step_up(areq) and not (auth_context or {}).get("step_up"):
        raise DecisionRefused("YES on an irreversible / money / purchase / offer / commitment request needs step-up "
                              "(auth_context.step_up=true; CLI: --step-up)")
    approval_id = new_id("appr")
    now = utcnow()
    doc: dict[str, Any] = {"approval_id": approval_id, "action_request_id": action_request_id, "decision": decision,
                           "decider": decider, "decided_at": iso(now), "channel": channel,
                           "payload_hash_seen": payload_hash_seen, "scope": "once"}
    for k, v in (("auth_context", auth_context), ("reason", reason)):
        if v:
            doc[k] = v
    new_areq_id = None
    if decision == "HOLD":
        doc["hold"] = {"wake_on": ["time", "michael_ping"], "renotify_after": "PT24H", "escalate_after": "P7D",
                       "hold_until": iso(now + timedelta(hours=24)), **(hold or {})}
    elif decision == "MODIFY":
        if new_payload is not None:
            if set(areq["payload"]) - set(new_payload):
                raise DecisionRefused("MODIFY cannot remove payload fields")
            payload_changes = {k: v for k, v in new_payload.items() if areq["payload"].get(k) != v}
        if not payload_changes:
            raise DecisionRefused("MODIFY needs payload changes")
        forbidden = {"capability", "item_id", "dry_run"} & set(payload_changes)
        if forbidden:
            raise DecisionRefused(f"MODIFY cannot change {sorted(forbidden)}; propose a different action instead")
        payload = {**areq["payload"], **payload_changes}
        new_areq_id = new_id("areq")
        prov_m = L.record_provenance(conn, actor_type="human", human_actor=decider, basis="FACT", approval_id=approval_id)
        successor = {**{k: v for k, v in areq.items() if k not in ("status", "policy_decision_ref")},
                     "action_request_id": new_areq_id, "derived_from": action_request_id, "created_at": iso(now),
                     "payload": payload, "payload_hash": sha256_of(payload), "idempotency_key": f"act:{new_areq_id}",
                     "provenance_ids": [prov_m]}
        # lane D (0007): the successor must exist BEFORE the MODIFY approval that references it
        _classify_and_present(conn, successor, [prov_m], components, MICHAEL)
        doc["modifications"] = {"diff": payload_changes, "new_action_request_id": new_areq_id,
                                "new_payload_hash": successor["payload_hash"]}
    try:
        Approval.from_doc(doc)  # frozen contract: MODIFY ⇒ modifications, HOLD ⇒ hold, NO ⇒ reason
    except ContractViolation as e:  # one exception type for UIs/CLI (07 F-18)
        raise DecisionRefused(f"decision not valid under the contract: {'; '.join(e.errors[:3])}") from None
    L.record_approval(conn, doc, {"type": "human", "id": decider}, f"Michael decided {decision}" + (f": {reason}" if reason else ""),
                      f"{approval_id}:decide")
    return {"approval": doc, "item_id": areq["item_id"], "new_action_request_id": new_areq_id}


def pending_decisions(conn: sa.Connection) -> list[dict]:
    rows = conn.execute(sa.text(
        "SELECT a.doc AS areq, i.doc AS item FROM mbos.v_action_request_documents a "
        "JOIN mbos.v_item_documents i ON i.item_id = a.doc->>'item_id' "
        "WHERE a.doc->>'status' IN ('pending_approval', 'held') ORDER BY a.doc->>'created_at'")).all()
    return [{"action_request": r.areq, "item": r.item} for r in rows]


# ---------------------------------------------------------------- workflow wait-state helpers
def poll_decision(conn: sa.Connection, action_request_id: str, after_seq: int) -> dict:
    areq = _areq(conn, action_request_id)
    row = conn.execute(sa.text(
        "SELECT ap.seq, d.doc FROM mbos.approvals ap JOIN mbos.v_approval_documents d USING (approval_id) "
        "WHERE ap.action_request_id = :a AND ap.seq > :s ORDER BY ap.seq LIMIT 1"),
        {"a": action_request_id, "s": after_seq}).one_or_none()
    return {"now": now_iso(), "status": areq["status"], "expires_at": areq["expires_at"],
            "approval": row.doc if row else None, "approval_seq": row.seq if row else after_seq}


def _approval_prov(conn: sa.Connection, approval: dict) -> str:
    return _prov(conn, "mbos.workflows.item_lifecycle", approval_id=approval["approval_id"])


def apply_no(conn: sa.Connection, item_id: str, approval: dict) -> None:
    prov = _approval_prov(conn, approval)
    _to(conn, item_id, "REJECTED", f"Michael said NO: {approval.get('reason', '')}", [prov])
    _to(conn, item_id, "ARCHIVED", "archived after NO (reason feeds LEARN)", [prov])


def apply_hold(conn: sa.Connection, item_id: str, approval: dict) -> dict:
    prov = _approval_prov(conn, approval)
    if read_item(conn, item_id)["state"] != "HELD":
        _to(conn, item_id, "HELD", "Michael said HOLD (parked; never auto-executes)", [prov])
    return {"now": now_iso()}


def apply_modify(conn: sa.Connection, item_id: str, approval: dict) -> str:
    prov = _approval_prov(conn, approval)
    new_id_ = approval["modifications"]["new_action_request_id"]
    if read_item(conn, item_id)["state"] == "HELD":
        _to(conn, item_id, "AWAITING_APPROVAL", f"MODIFY: superseded by {new_id_}", [prov])
    return new_id_


def wake_from_hold(conn: sa.Connection, item_id: str, action_request_id: str, why: str, components: Any) -> dict:
    areq = _areq(conn, action_request_id)
    prov = _prov(conn, "mbos.workflows.item_lifecycle", inputs=(action_request_id,))
    n = conn.execute(sa.text("SELECT count(*) FROM mbos.receipts WHERE action_request_id = :a"), {"a": action_request_id}).scalar_one()
    if areq["status"] == "held":
        _status(conn, areq, "pending_approval", "APPROVAL_REQUESTED", f"re-presented after HOLD ({why}); never auto-executed",
                [prov], key=f"{action_request_id}:wake:{n}")
    if read_item(conn, item_id)["state"] == "HELD":
        _to(conn, item_id, "AWAITING_APPROVAL", f"woke from HOLD ({why}); re-presented, not executed", [prov])
    return {"now": now_iso()}


def renotify(conn: sa.Connection, item_id: str, action_request_id: str, components: Any,
             why: str = "still on HOLD after renotify_after TTL") -> dict:
    areq = _areq(conn, action_request_id)
    prov = _prov(conn, "mbos.workflows.item_lifecycle", inputs=(action_request_id,))
    n = conn.execute(sa.text("SELECT count(*) FROM mbos.receipts WHERE action_request_id = :a"), {"a": action_request_id}).scalar_one()
    _receipt(conn, areq, "APPROVAL_REQUESTED", f"re-notify: {why} (no execution)", [prov], f"{action_request_id}:renotify:{n}",
             effect="none")
    return {"now": now_iso()}


def expire(conn: sa.Connection, item_id: str, action_request_id: str) -> None:
    areq = _areq(conn, action_request_id)
    prov = _prov(conn, "mbos.workflows.item_lifecycle", inputs=(action_request_id,))
    _status(conn, areq, "expired", "POLICY_DECIDED", f"expired at {areq['expires_at']} without a decision; nothing executed", [prov])
    _to(conn, item_id, "ARCHIVED", f"{action_request_id} expired without a decision; nothing executed", [prov])


# ---------------------------------------------------------------- DRY-RUN ACT + RECEIPT
def begin_act(conn: sa.Connection, item_id: str, action_request_id: str, approval: dict) -> None:
    prov = _approval_prov(conn, approval)
    if read_item(conn, item_id)["state"] == "HELD":
        _to(conn, item_id, "AWAITING_APPROVAL", "re-presented: Michael decided YES on a held request", [prov])
    _to(conn, item_id, "APPROVED", "Michael said YES", [prov], MICHAEL)
    areq = _areq(conn, action_request_id)
    _to(conn, item_id, "ACTING", f"executing {areq['capability']} (DRY-RUN)", [prov])
    _status(conn, areq, "executing", "ACTION_EXECUTING", "handing the frozen payload to the action gateway (DRY-RUN)", [prov],
            extra={"approval_id": approval["approval_id"]})


def finish_act(conn: sa.Connection, item_id: str, action_request_id: str, approval: dict, guard: dict) -> dict:
    areq = _areq(conn, action_request_id)
    prov = L.record_provenance(conn, actor_type="system", agent_name="action-gateway", basis="FACT", tool_name=GATEWAY_TOOL,
                               tool_version="0.1.0", approval_id=approval["approval_id"],
                               inputs_used=[{"ref": action_request_id, "hash": areq["payload_hash"]}])
    _, effect = classify_capability(areq["capability"])
    details = {"kind": "comms" if areq["capability"].startswith("comms.") else "generic", "dry_run": True,
               "guard_checks": guard["checks"], "guard_reason": guard["reason"],
               "action_idempotency_key": areq["idempotency_key"]}
    response = guard.get("effector_response") or {}
    if isinstance(response.get("comms"), dict):
        details.update(response["comms"])
        details.update(kind="comms", dry_run=True)
    if guard["ok"] and response.get("status") == "blocked":
        reasons = response.get("blocked") or (response.get("comms") or {}).get("blocked_reasons") or ["see details"]
        guard = {**guard, "ok": False, "reason": "effector blocked: " + ", ".join(map(str, reasons))}
    base = {"approval_id": approval["approval_id"], "tool_name": GATEWAY_TOOL, "effector_response": response, "details": details}
    if guard["ok"]:
        _status(conn, areq, "executed", "ACTION_EXECUTED", f"DRY-RUN {areq['capability']} executed via gateway (no external effect)",
                [prov], extra={**base, "effect": effect})
        _to(conn, item_id, "ACTED", "dry-run action receipted", [prov])
        return {"status": "acted"}
    to = "cancelled_by_freeze" if guard.get("frozen") else "failed"
    _status(conn, areq, to, "ACTION_FAILED", f"gateway refused: {guard['reason']}", [prov],
            extra={**base, "effect": "none", "effector_response": {**response, "dry_run": True}})
    _to(conn, item_id, "FAILED", f"action not executed: {guard['reason']}", [prov])
    return {"status": "failed", "reason": guard["reason"]}


# ---------------------------------------------------------------- OUTCOME / KILL SWITCH
def record_outcome(conn: sa.Connection, item_id: str, kind: str, *, realized: Optional[dict] = None,
                   predicted_vs_actual: Optional[list] = None, notes: Optional[str] = None,
                   recorded_by: str = "michael", channel: str = "cli",
                   attribution: Optional[dict] = None) -> dict:
    item = read_item(conn, item_id)
    prov = L.record_provenance(conn, actor_type="human", human_actor=recorded_by, basis="FACT",
                               tool_name=f"mbos.{channel}.outcome", tool_version="0.1.0", inputs_used=[{"ref": item_id}])
    outcome_id = new_id("outc")
    doc = {k: v for k, v in {"outcome_id": outcome_id, "item_id": item_id, "observed_at": now_iso(), "kind": kind,
                             "action_request_id": (item.get("action_request_ids") or [None])[-1],
                             "scorecard_id": (item.get("scores") or {}).get("scorecard_id"), "realized": realized,
                             "predicted_vs_actual": predicted_vs_actual, "notes": notes, "attribution": attribution,
                             "provenance_ids": [prov]}.items() if v is not None}
    L.record_outcome(conn, doc, {"type": "human", "id": recorded_by}, f"outcome {kind}", f"{outcome_id}:record")
    if item["state"] == "ACTED":
        _to(conn, item_id, "OUTCOME_RECORDED", f"outcome {kind} recorded", [prov], {"type": "human", "id": recorded_by})
    return doc


def set_kill_switch(conn: sa.Connection, key: str, frozen: bool, *, reason: str, actor_id: str = "michael") -> dict:
    """Lane D PANIC (0007): engage needs gateway/approver/policy_admin; RELEASE needs approver (Michael)."""
    level, target = ("L3", None) if key == "global_freeze" else (
        ("L2", key.split(":", 1)[1]) if key.startswith("capability_freeze:") else ("L1", key.split(":", 1)[1]))
    prov = L.record_provenance(conn, actor_type="human" if actor_id == "michael" else "system", human_actor=actor_id,
                               basis="FACT", tool_name="mbos.kill_switch", tool_version="0.1.0")
    rid = conn.execute(sa.text("SELECT mbos.panic_set(:l, :t, :e, CAST(:a AS jsonb), :r, :p, :k)"),
                       {"l": level, "t": target, "e": frozen, "a": canonical_json({"type": "human", "id": actor_id}).decode(),
                        "r": reason, "p": [prov], "k": f"panic:{level}:{target}:{frozen}:{new_id('rcpt')}"}).scalar_one()
    return {"frozen": frozen, "reason": reason, "receipt_id": rid}
