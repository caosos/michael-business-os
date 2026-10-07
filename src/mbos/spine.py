"""Transactional spine operations: DISCOVER → NORMALIZE → SCORE → RECOMMEND → APPROVE → ACT → RECEIPT.

Every function here takes the caller's open `sa.Connection` (first argument) and runs inside
ONE transaction: state change + receipt(s) + outbox commit together or not at all (A1).
Workflows call them through `mbos.runtime.tx`, which makes each call exactly-once under DBOS.
They must be deterministic given their arguments and the DB: no wall-clock branching that a
workflow replay would see differently (time is read here and returned for the workflow to use).
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

import sqlalchemy as sa

from mbos.clock import iso, now_iso, parse, utcnow
from mbos.config import settings
from mbos.contracts.models import ActionRequest, Approval
from mbos.hashing import canonical_json, sha256_bytes, sha256_of
from mbos.ids import new_id
from mbos.ledger import (
    _j, append_receipt, create_item, load_item, record_provenance, tool_provenance, update_item,
)
from mbos.reference.governance import GATEWAY_TOOL, classify_capability
from mbos.state_machine import check_action_transition

SPINE_AGENT = "agent-01-coordinator"  # agent ids == branch names (ADR-05-003)
MICHAEL = {"type": "human", "id": "michael"}


class DecisionRefused(ValueError):
    """A decision that the request's current status, or its payload hash, does not allow."""


STEP_UP_CATEGORIES = {"money", "purchase", "offer", "external_commitment"}


def requires_step_up(areq: dict) -> bool:
    """ADR-05-001 / Agent 04 approvals trigger: irreversible or money-like YES needs step-up."""
    return areq["reversibility"] == "irreversible" or areq["category"] in STEP_UP_CATEGORIES


# ---------------------------------------------------------------- DISCOVER + NORMALIZE
def ingest(conn: sa.Connection, raw: dict[str, Any], norm: Optional[dict[str, Any]], adapter_name: str,
           adapter_version: str, components: Any) -> dict[str, Any]:
    """Store the raw artifact, then create a new Item or merge a duplicate sighting.

    Identity first: the same (source, source_listing_id) is the same sighting → no-op.
    Then `dedup_key` (a blocking bucket) nominates candidates and the lane-B Deduper decides.
    """
    from mbos.interfaces import NormalizedListing

    if norm is None:
        return {"item_id": None, "created": False, "merged": False, "dropped": True}
    ident = {"source": raw["source"]}
    ident.update({"source_listing_id": raw["source_listing_id"]} if raw["source_listing_id"] else {"url": raw["url"]})
    seen = conn.execute(sa.text("SELECT item_id FROM mbos.items WHERE body->'sources' @> CAST(:s AS jsonb) LIMIT 1"),
                        {"s": _j([ident])}).scalar_one_or_none()
    if seen is not None:
        return {"item_id": seen, "created": False, "merged": False, "dropped": False}
    existing = None
    for row in conn.execute(sa.text("SELECT body FROM mbos.items WHERE dedup_key = :k ORDER BY body->>'created_at' FOR UPDATE"),
                            {"k": norm["dedup_key"]}).all():
        if components.deduper.is_duplicate(row.body, NormalizedListing(**norm)):
            existing = row
            break

    raw_bytes = canonical_json(raw["payload"])
    raw_ref = sha256_bytes(raw_bytes)
    conn.execute(sa.text("INSERT INTO mbos.artifacts (sha256, media_type, content) VALUES (:h, 'application/json', :c) "
                         "ON CONFLICT (sha256) DO NOTHING"), {"h": raw_ref, "c": raw_bytes})
    src_prov = record_provenance(
        conn, actor_type="agent", agent_name=adapter_name, basis="FACT", source_uri=raw["url"],
        fetched_at=raw["fetched_at"], tool_name=adapter_name, tool_version=adapter_version,
        inputs_used=[{"ref": raw_ref, "hash": raw_ref}],
    )
    sighting = {k: v for k, v in {
        "source": raw["source"], "source_listing_id": raw["source_listing_id"], "url": raw["url"],
        "ingestion_method": raw["ingestion_method"], "tos_risk": raw["tos_risk"],
        "first_seen_at": raw["fetched_at"], "raw_ref": raw_ref, "provenance_id": src_prov,
    }.items() if v is not None}

    if existing is not None:
        item = existing.body
        update_item(conn, item["item_id"], patch={"sources": item["sources"] + [sighting]},
                    intent=f"dedup: merged duplicate sighting from {raw['source']} into existing item",
                    provenance_ids=[src_prov])
        return {"item_id": item["item_id"], "created": False, "merged": True, "dropped": False}

    item_id = new_id("itm")
    item = {k: v for k, v in {
        "item_id": item_id, "schema_version": "1.0.0", "type": norm["type"], "category": norm["category"],
        "subcategory": norm.get("subcategory"), "opportunity_kind": norm.get("opportunity_kind"),
        "state": "DISCOVERED", "created_at": raw["fetched_at"], "sources": [sighting],
        "dedup_key": norm["dedup_key"], "content_hash": norm.get("content_hash"), "normalized": norm["normalized"],
        "provenance_ids": [src_prov],
    }.items() if v is not None}
    create_item(conn, item, intent=f"discovered via {adapter_name}", provenance_ids=[src_prov],
                actor={"type": "agent", "id": adapter_name})
    norm_prov = tool_provenance(conn, f"{adapter_name}.normalizer", inputs=[raw_ref], derived_from=[src_prov])
    patch = {"economics": norm["economics"]} if norm.get("economics") else None
    update_item(conn, item_id, to_state="NORMALIZED", patch=patch, intent="normalized to Item v1",
                provenance_ids=[norm_prov], actor={"type": "agent", "id": adapter_name})
    return {"item_id": item_id, "created": True, "merged": False, "dropped": False}


# ---------------------------------------------------------------- SCORE + RECOMMEND
def read_item(conn: sa.Connection, item_id: str) -> dict[str, Any]:
    return load_item(conn, item_id)


def record_score(conn: sa.Connection, item_id: str, sr: dict[str, Any]) -> dict[str, Any]:
    """Item → SCORED (SCORE_RECORDED) → RECOMMENDED (RECOMMENDATION_RECORDED), one transaction."""
    item = load_item(conn, item_id, for_update=True)
    actor = {"type": "agent", "id": "lane-c-economics"}
    prov = record_provenance(
        conn, actor_type="agent", agent_name=sr["tool_name"], basis="INFERENCE", tool_name=sr["tool_name"],
        tool_version=sr["tool_version"], config_version=sr["scoring_config_version"],
        inputs_used=[{"ref": item_id, "hash": sr["inputs_hash"]}],
        derived_from=[s["provenance_id"] for s in item["sources"]], confidence=sr["confidence"],
    )
    scores = {"scorecard_id": sr.get("scorecard_id") or new_id("scr"), "inputs_hash": sr["inputs_hash"], "scorecard": sr["scorecard"]}
    update_item(conn, item_id, to_state="SCORED", patch={"scores": scores}, intent="scored", provenance_ids=[prov], actor=actor)
    append_receipt(conn, type="SCORE_RECORDED", intent=f"scorecard {scores['scorecard_id']}: {sr['verdict']}",
                   provenance_ids=[prov], actor=actor, item_id=item_id, entity_type="scorecard",
                   entity_id=scores["scorecard_id"], effect="create", inputs_hash=sr["inputs_hash"],
                   tool_name=f"{sr['tool_name']}@{sr['tool_version']}")
    rec = {k: v for k, v in {
        "recommendation_id": sr.get("recommendation_id") or new_id("rec"), "verdict": sr["verdict"], "proposed_actions": sr["proposed_actions"] or None,
        "rationale": sr["rationale"], "confidence": sr["confidence"],
        "cheapest_decisive_evidence": sr.get("cheapest_decisive_evidence"), "alert": sr.get("alert"),
        "provenance_id": prov,
    }.items() if v is not None}
    update_item(conn, item_id, to_state="RECOMMENDED", patch={"recommendation": rec}, intent=f"recommended {sr['verdict']}",
                provenance_ids=[prov], actor=actor)
    append_receipt(conn, type="RECOMMENDATION_RECORDED", intent=f"machine verdict {sr['verdict']} (not Michael's decision)",
                   provenance_ids=[prov], actor=actor, item_id=item_id, entity_type="recommendation",
                   entity_id=rec["recommendation_id"], effect="create", inputs_hash=sr["inputs_hash"])
    return {"verdict": sr["verdict"], "recommendation_id": rec["recommendation_id"], "scorecard_id": scores["scorecard_id"]}


def route_recommendation(conn: sa.Connection, item_id: str, components: Any) -> dict[str, Any]:
    """PASS → ARCHIVED · MAYBE → RESEARCHING · YES → ActionRequest (tier 0) → AWAITING_APPROVAL."""
    item = load_item(conn, item_id, for_update=True)
    rec = item["recommendation"]
    prov = tool_provenance(conn, "mbos.spine.route_recommendation", basis="RECOMMENDATION",
                           inputs=[item_id, rec["recommendation_id"]], derived_from=[rec["provenance_id"]])
    if rec["verdict"] == "PASS":
        update_item(conn, item_id, to_state="ARCHIVED", intent="machine verdict PASS: archived", provenance_ids=[prov])
        return {"verdict": "PASS", "action_request_id": None}
    proposed = rec.get("proposed_actions") or (components.planner.plan(item) if rec["verdict"] == "YES" else [])
    if rec["verdict"] == "MAYBE" or not proposed:
        why = rec.get("cheapest_decisive_evidence") or "more evidence"
        update_item(conn, item_id, to_state="RESEARCHING", intent=f"MAYBE: needs {why}", provenance_ids=[prov])
        components.notifier.notify(conn, kind="research_needed", item_id=item_id, action_request_id=None,
                                   summary=f"{item['normalized']['title']}: needs {why}")
        return {"verdict": "MAYBE", "action_request_id": None}
    # MVP: the item proceeds on its primary proposed action; further actions are proposed after it settles.
    areq = _propose(conn, item, proposed[0], prov, components)
    update_item(conn, item_id, to_state="AWAITING_APPROVAL",
                patch={"action_request_ids": (item.get("action_request_ids") or []) + [areq["action_request_id"]]},
                intent=f"awaiting Michael: {areq['capability']}", provenance_ids=[prov])
    return {"verdict": "YES", "action_request_id": areq["action_request_id"]}


def _set_status(conn: sa.Connection, areq_id: str, to_status: str) -> dict[str, Any]:
    body = conn.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a FOR UPDATE"),
                        {"a": areq_id}).one().body
    check_action_transition(body["status"], to_status)
    body = {**body, "status": to_status}
    conn.execute(sa.text("UPDATE mbos.action_requests SET body = CAST(:b AS jsonb) WHERE action_request_id = :a"),
                 {"b": _j(body), "a": areq_id})
    return body


def _areq_receipt(conn: sa.Connection, areq: dict, rtype: str, intent: str, provenance_ids: list[str],
                  actor: Optional[dict] = None, **fields: Any) -> dict:
    return append_receipt(conn, type=rtype, intent=intent, provenance_ids=provenance_ids, actor=actor,
                          item_id=areq["item_id"], action_request_id=areq["action_request_id"],
                          capability=areq["capability"], payload_hash=areq["payload_hash"],
                          entity_type="action_request", entity_id=areq["action_request_id"], **fields)


def _insert_and_classify(conn: sa.Connection, areq: dict, prov: str, components: Any, actor: Optional[dict]) -> dict:
    decision = components.pdp.decide(areq)  # the PDP sees the FULL request (lane E contract)
    areq = {**areq, "tier": decision.tier, "category": decision.category,
            "policy_decision_ref": decision.policy_version}
    ActionRequest.from_doc(areq)  # frozen-contract check, incl. irreversible/untrusted/money ⇒ tier 0
    conn.execute(sa.text("INSERT INTO mbos.action_requests (body) VALUES (CAST(:b AS jsonb))"), {"b": _j(areq)})
    _areq_receipt(conn, areq, "ACTION_PROPOSED", f"proposed {areq['capability']}: {areq['payload']['summary']}",
                  [prov], actor=actor, effect="create")
    _set_status(conn, areq["action_request_id"], "classified")
    _areq_receipt(conn, areq, "POLICY_DECIDED", f"PDP: {decision.decision}, tier {decision.tier} — {decision.reason}",
                  [prov], policy_decision_ref=decision.policy_version,
                  details={"kind": "generic", "decision": decision.decision, "tier": decision.tier})
    if decision.decision == "deny":
        _set_status(conn, areq["action_request_id"], "rejected")
        return {**areq, "status": "rejected"}
    _set_status(conn, areq["action_request_id"], "pending_approval")
    _areq_receipt(conn, areq, "APPROVAL_REQUESTED", "presented to Michael: YES / NO / MODIFY / HOLD", [prov])
    components.notifier.notify(conn, kind="approval_requested", item_id=areq["item_id"],
                               action_request_id=areq["action_request_id"], summary=areq["payload"]["summary"])
    return {**areq, "status": "pending_approval"}


def _propose(conn: sa.Connection, item: dict, pa: dict, prov: str, components: Any) -> dict:
    areq_id = new_id("areq")
    category, _ = classify_capability(pa["capability"])
    counterparty = item["normalized"].get("counterparty") or {}
    payload = {
        "capability": pa["capability"],
        "summary": pa["summary"],
        "item_id": item["item_id"],
        "recommendation_id": item["recommendation"]["recommendation_id"],
        "target": {"kind": counterparty.get("role", "counterparty"), "ref": item["sources"][0]["url"]},
        "dry_run": True,
    }
    now = utcnow()
    expires = now + timedelta(hours=settings().approval_ttl_hours)
    ends_at = item["normalized"].get("ends_at")
    if ends_at and parse(ends_at) < expires:
        expires = parse(ends_at)
    areq = {k: v for k, v in {
        "action_request_id": areq_id, "item_id": item["item_id"],
        "recommendation_id": item["recommendation"]["recommendation_id"], "created_at": iso(now),
        "proposed_by": SPINE_AGENT, "on_behalf_of": "michael", "capability": pa["capability"], "category": category,
        "payload": payload, "payload_hash": sha256_of(payload), "idempotency_key": f"act:{areq_id}",
        "estimated_cost": pa.get("estimated_cost") or {"amount": 0, "currency": "USD"},
        "reversibility": pa["reversibility"], "untrusted_inputs_present": True,  # listing-derived ⇒ tainted
        "tier": 0, "score_ref": item["scores"]["scorecard_id"],
        "status": "drafted", "expires_at": iso(expires), "provenance_ids": [prov],
        "target": payload["target"],
    }.items() if v is not None}
    return _insert_and_classify(conn, areq, prov, components, None)


# ---------------------------------------------------------------- APPROVE (Michael)
def decide(conn: sa.Connection, action_request_id: str, decision: str, payload_hash_seen: str, components: Any, *,
           decider: str = "michael", channel: str = "cli", reason: Optional[str] = None,
           hold: Optional[dict] = None, payload_changes: Optional[dict] = None,
           new_payload: Optional[dict] = None, auth_context: Optional[dict] = None) -> dict[str, Any]:
    """Record Michael's YES / NO / MODIFY / HOLD. Append-only; the item workflow reacts to it.

    The caller must then wake the workflow: `DBOS.send(f"item:{item_id}", {...}, topic="decision")`
    (see mbos.runtime.notify_decision). If that send is lost, the workflow still finds the decision
    on its next poll — the DB row is the source of truth, the message is only a wake-up.
    """
    areq = conn.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a FOR UPDATE"),
                        {"a": action_request_id}).one_or_none()
    if areq is None:
        raise DecisionRefused(f"unknown action request {action_request_id}")
    areq = areq.body
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
    doc: dict[str, Any] = {
        "approval_id": approval_id, "action_request_id": action_request_id, "decision": decision, "decider": decider,
        "decided_at": iso(now), "channel": channel, "payload_hash_seen": payload_hash_seen, "scope": "once",
    }
    if auth_context:
        doc["auth_context"] = auth_context
    if reason:
        doc["reason"] = reason
    new_areq = None
    prov = record_provenance(conn, actor_type="human", human_actor=decider, basis="FACT", approval_id=approval_id)
    if decision == "HOLD":
        doc["hold"] = {"wake_on": ["time", "michael_ping"], "renotify_after": "PT24H", "escalate_after": "P7D",
                       "hold_until": iso(now + timedelta(hours=24)), **(hold or {})}
    elif decision == "MODIFY":
        if new_payload is not None:  # Operator UI sends the whole edited payload; store the diff
            payload_changes = {k: v for k, v in new_payload.items() if areq["payload"].get(k) != v}
            if set(areq["payload"]) - set(new_payload):
                raise DecisionRefused("MODIFY cannot remove payload fields")
        if not payload_changes:
            raise DecisionRefused("MODIFY needs payload changes")
        forbidden = {"capability", "item_id", "dry_run"} & set(payload_changes)
        if forbidden:
            raise DecisionRefused(f"MODIFY cannot change {sorted(forbidden)}; propose a different action instead")
        new_payload = {**areq["payload"], **payload_changes}
        new_id_ = new_id("areq")
        new_areq = {**areq, "action_request_id": new_id_, "derived_from": action_request_id, "created_at": iso(now),
                    "payload": new_payload, "payload_hash": sha256_of(new_payload), "idempotency_key": f"act:{new_id_}",
                    "status": "drafted", "provenance_ids": [prov]}
        doc["modifications"] = {"diff": payload_changes, "new_action_request_id": new_id_,
                                "new_payload_hash": new_areq["payload_hash"]}
    Approval.from_doc(doc)  # frozen contract: MODIFY ⇒ modifications, HOLD ⇒ hold, NO ⇒ reason
    if new_areq is not None:
        # The successor must exist before anything references it.
        _insert_and_classify(conn, new_areq, prov, components, MICHAEL)
    conn.execute(sa.text("INSERT INTO mbos.approvals (body) VALUES (CAST(:b AS jsonb))"), {"b": _j(doc)})
    _areq_receipt(conn, areq, "APPROVAL_DECIDED", f"Michael decided {decision}" + (f": {reason}" if reason else ""),
                  [prov], actor={"type": "human", "id": decider}, approval_id=approval_id)
    to_status = {"YES": "approved", "NO": "rejected", "HOLD": "held", "MODIFY": "rejected"}[decision]
    _set_status(conn, action_request_id, to_status)
    return {"approval": doc, "item_id": areq["item_id"],
            "new_action_request_id": new_areq["action_request_id"] if new_areq else None}


def pending_decisions(conn: sa.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(sa.text(
        "SELECT a.body AS areq, i.body AS item FROM mbos.action_requests a JOIN mbos.items i USING (item_id) "
        "WHERE a.status IN ('pending_approval', 'held') ORDER BY a.body->>'created_at'")).all()
    return [{"action_request": r.areq, "item": r.item} for r in rows]


# ---------------------------------------------------------------- workflow wait-state helpers
def poll_decision(conn: sa.Connection, action_request_id: str, after_seq: int) -> dict[str, Any]:
    areq = conn.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a"),
                        {"a": action_request_id}).one().body
    row = conn.execute(sa.text("SELECT seq, body FROM mbos.approvals WHERE action_request_id = :a AND seq > :s "
                               "ORDER BY seq LIMIT 1"), {"a": action_request_id, "s": after_seq}).one_or_none()
    return {"now": now_iso(), "status": areq["status"], "expires_at": areq["expires_at"],
            "approval": row.body if row else None, "approval_seq": row.seq if row else after_seq}


def _approval_prov(conn: sa.Connection, approval: dict) -> str:
    return record_provenance(conn, actor_type="system", agent_name=SPINE_AGENT, basis="FACT",
                             tool_name="mbos.workflows.item_lifecycle", tool_version="0.1.0",
                             approval_id=approval["approval_id"])


def apply_no(conn: sa.Connection, item_id: str, approval: dict) -> None:
    prov = _approval_prov(conn, approval)
    item = load_item(conn, item_id)
    update_item(conn, item_id, to_state="REJECTED", patch={"approval_ids": (item.get("approval_ids") or []) + [approval["approval_id"]]},
                intent=f"Michael said NO: {approval.get('reason', '')}", provenance_ids=[prov])
    update_item(conn, item_id, to_state="ARCHIVED", intent="archived after NO (reason feeds LEARN)", provenance_ids=[prov])


def apply_hold(conn: sa.Connection, item_id: str, approval: dict) -> dict:
    prov = _approval_prov(conn, approval)
    item = load_item(conn, item_id)
    patch = {"approval_ids": (item.get("approval_ids") or []) + [approval["approval_id"]]}
    if item["state"] == "HELD":
        update_item(conn, item_id, patch=patch, intent="HOLD renewed", provenance_ids=[prov])
    else:
        update_item(conn, item_id, to_state="HELD", patch=patch, intent="Michael said HOLD (parked; never auto-executes)",
                    provenance_ids=[prov])
    return {"now": now_iso()}


def apply_modify(conn: sa.Connection, item_id: str, approval: dict) -> str:
    prov = _approval_prov(conn, approval)
    item = load_item(conn, item_id)
    new_id_ = approval["modifications"]["new_action_request_id"]
    patch = {"approval_ids": (item.get("approval_ids") or []) + [approval["approval_id"]],
             "action_request_ids": (item.get("action_request_ids") or []) + [new_id_]}
    to_state = "AWAITING_APPROVAL" if item["state"] == "HELD" else None
    update_item(conn, item_id, to_state=to_state, patch=patch,
                intent=f"MODIFY: superseded by {new_id_}; awaiting Michael on the modified request", provenance_ids=[prov])
    return new_id_


def wake_from_hold(conn: sa.Connection, item_id: str, action_request_id: str, why: str, components: Any) -> dict:
    """HOLD wake / escalation: re-present the request. NEVER executes it."""
    areq = conn.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a"),
                        {"a": action_request_id}).one().body
    prov = tool_provenance(conn, "mbos.workflows.item_lifecycle", inputs=[action_request_id])
    if areq["status"] == "held":
        _set_status(conn, action_request_id, "pending_approval")
    update_item(conn, item_id, to_state="AWAITING_APPROVAL", intent=f"woke from HOLD ({why}); re-presented, not executed",
                provenance_ids=[prov])
    _areq_receipt(conn, areq, "APPROVAL_REQUESTED", f"re-presented after HOLD ({why}); never auto-executed", [prov])
    components.notifier.notify(conn, kind="hold_woke", item_id=item_id, action_request_id=action_request_id,
                            summary=f"HOLD ended ({why}): {areq['payload']['summary']}")
    return {"now": now_iso()}


def renotify(conn: sa.Connection, item_id: str, action_request_id: str, components: Any) -> dict:
    areq = conn.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a"),
                        {"a": action_request_id}).one().body
    prov = tool_provenance(conn, "mbos.workflows.item_lifecycle", inputs=[action_request_id])
    _areq_receipt(conn, areq, "APPROVAL_REQUESTED", "re-notify: still on HOLD after renotify_after TTL (no execution)", [prov])
    components.notifier.notify(conn, kind="hold_renotify", item_id=item_id, action_request_id=action_request_id,
                            summary=f"Still on HOLD: {areq['payload']['summary']}")
    return {"now": now_iso()}


def expire(conn: sa.Connection, item_id: str, action_request_id: str) -> None:
    """No decision before expires_at: the request expires and the item is archived. Nothing executes.
    (ACTION_FAILED needs an approval_id by contract, so expiry is receipted as the item transition.)"""
    areq = _set_status(conn, action_request_id, "expired")
    prov = tool_provenance(conn, "mbos.workflows.item_lifecycle", inputs=[action_request_id])
    update_item(conn, item_id, to_state="ARCHIVED",
                intent=f"{action_request_id} expired at {areq['expires_at']} without a decision; nothing executed",
                provenance_ids=[prov])


# ---------------------------------------------------------------- DRY-RUN ACT + RECEIPT
def begin_act(conn: sa.Connection, item_id: str, action_request_id: str, approval: dict) -> None:
    prov = _approval_prov(conn, approval)
    item = load_item(conn, item_id)
    update_item(conn, item_id, to_state="APPROVED",
                patch={"approval_ids": (item.get("approval_ids") or []) + [approval["approval_id"]]},
                intent="Michael said YES", provenance_ids=[prov])
    areq = _set_status(conn, action_request_id, "executing")
    update_item(conn, item_id, to_state="ACTING", intent=f"executing {areq['capability']} (DRY-RUN)", provenance_ids=[prov])
    _areq_receipt(conn, areq, "ACTION_EXECUTING", "handing the frozen payload to the action gateway (DRY-RUN)", [prov],
                  approval_id=approval["approval_id"])


def finish_act(conn: sa.Connection, item_id: str, action_request_id: str, approval: dict, guard: dict) -> dict:
    areq = conn.execute(sa.text("SELECT body FROM mbos.action_requests WHERE action_request_id = :a"),
                        {"a": action_request_id}).one().body
    prov = record_provenance(conn, actor_type="system", agent_name="action-gateway", basis="FACT",
                             tool_name=GATEWAY_TOOL, tool_version="0.1.0", approval_id=approval["approval_id"],
                             inputs_used=[{"ref": action_request_id, "hash": areq["payload_hash"]}])
    _, effect = classify_capability(areq["capability"])
    kind = "comms" if areq["capability"].startswith("comms.") else "generic"
    details = {"kind": kind, "dry_run": True, "guard_checks": guard["checks"], "guard_reason": guard["reason"],
               "action_idempotency_key": areq["idempotency_key"]}
    if guard["ok"]:
        _areq_receipt(conn, areq, "ACTION_EXECUTED", f"DRY-RUN {areq['capability']} executed via gateway (no external effect)",
                      [prov], approval_id=approval["approval_id"], effect=effect, tool_name=GATEWAY_TOOL,
                      effector_response=guard["effector_response"], details=details)
        _set_status(conn, action_request_id, "executed")
        update_item(conn, item_id, to_state="ACTED", intent="dry-run action receipted", provenance_ids=[prov])
        return {"status": "acted"}
    _areq_receipt(conn, areq, "ACTION_FAILED", f"gateway refused: {guard['reason']}", [prov],
                  approval_id=approval["approval_id"], effect="none", tool_name=GATEWAY_TOOL,
                  effector_response=guard["effector_response"], details=details)
    _set_status(conn, action_request_id, "cancelled_by_freeze" if guard.get("frozen") else "failed")
    update_item(conn, item_id, to_state="FAILED", intent=f"action not executed: {guard['reason']}", provenance_ids=[prov])
    return {"status": "failed", "reason": guard["reason"]}


# ---------------------------------------------------------------- OUTCOME (feeds LEARN, lane C)
def record_outcome(conn: sa.Connection, item_id: str, kind: str, *, realized: Optional[dict] = None,
                   predicted_vs_actual: Optional[list] = None, notes: Optional[str] = None,
                   recorded_by: str = "michael") -> dict[str, Any]:
    from mbos.contracts.models import Outcome

    item = load_item(conn, item_id, for_update=True)
    outcome_id = new_id("outc")
    prov = record_provenance(conn, actor_type="human", human_actor=recorded_by, basis="FACT",
                             tool_name="mbos.cli.outcome", tool_version="0.1.0", inputs_used=[{"ref": item_id}])
    doc = {k: v for k, v in {
        "outcome_id": outcome_id, "item_id": item_id, "observed_at": now_iso(), "kind": kind,
        "action_request_id": (item.get("action_request_ids") or [None])[-1],
        "scorecard_id": (item.get("scores") or {}).get("scorecard_id"),
        "realized": realized, "predicted_vs_actual": predicted_vs_actual, "notes": notes, "provenance_ids": [prov],
    }.items() if v is not None}
    Outcome.from_doc(doc)
    conn.execute(sa.text("INSERT INTO mbos.outcomes (body) VALUES (CAST(:b AS jsonb))"), {"b": _j(doc)})
    append_receipt(conn, type="OUTCOME_RECORDED", intent=f"outcome {kind}", provenance_ids=[prov],
                   actor={"type": "human", "id": recorded_by}, item_id=item_id, outcome_id=outcome_id,
                   entity_type="outcome", entity_id=outcome_id, effect="create")
    to_state = "OUTCOME_RECORDED" if item["state"] == "ACTED" else None
    update_item(conn, item_id, to_state=to_state, patch={"outcome_ids": (item.get("outcome_ids") or []) + [outcome_id]},
                intent=f"outcome {kind} recorded", provenance_ids=[prov], actor={"type": "human", "id": recorded_by})
    return doc


# ---------------------------------------------------------------- KILL SWITCH (lane E owns semantics)
def set_kill_switch(conn: sa.Connection, key: str, frozen: bool, *, reason: str, actor_id: str = "michael") -> dict:
    """Set an L3 ('global_freeze'), L2 ('capability_freeze:<cap>') or L1 ('agent_freeze:<agent>') flag, receipted."""
    if not (key == "global_freeze" or key.startswith(("capability_freeze:", "agent_freeze:"))):
        raise ValueError(f"unknown kill-switch key {key!r}")
    before = conn.execute(sa.text("SELECT value FROM mbos.governance_flags WHERE key = :k FOR UPDATE"),
                          {"k": key}).scalar_one_or_none()
    value = {"frozen": frozen, "reason": reason}
    conn.execute(sa.text("INSERT INTO mbos.governance_flags (key, value, updated_at) VALUES (:k, CAST(:v AS jsonb), now()) "
                         "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()"),
                 {"k": key, "v": _j(value)})
    prov = record_provenance(conn, actor_type="human" if actor_id == "michael" else "system", human_actor=actor_id,
                             basis="FACT", tool_name="mbos.kill_switch", tool_version="0.1.0")
    append_receipt(conn, type="KILL_SWITCH_CHANGED", intent=f"{key} -> frozen={frozen}: {reason}", provenance_ids=[prov],
                   actor={"type": "human" if actor_id == "michael" else "system", "id": actor_id},
                   entity_type="governance_flag", entity_id=key, effect="update",
                   before_state=before if isinstance(before, dict) else None, after_state=value)
    return value
