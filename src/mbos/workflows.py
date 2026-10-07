"""DBOS durable workflows — the canonical Item lifecycle.

    discover(adapter)            DISCOVER → NORMALIZE (dedup) → start item_lifecycle per new Item
    item_lifecycle(item_id)      SCORE → RECOMMEND → (PASS: ARCHIVED | MAYBE: RESEARCHING |
                                 YES: ActionRequest → APPROVAL GATE (durable wait) → DRY-RUN ACT → RECEIPT)

Determinism rules (DBOS replays the workflow body on recovery):
- every DB effect goes through `tx(...)` (checkpointed, exactly-once); every non-DB call is a `@DBOS.step`
- ids and wall-clock time come from step/tx results, never from the workflow body
- approvals are read from the DB; a DBOS message is only a wake-up, never the source of truth
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import timedelta
from typing import Any, Optional

from dbos import DBOS, SetWorkflowID

from mbos import __version__, spine
from mbos.clock import parse
from mbos.runtime import components, item_workflow_id, runtime, tx

DECISION_TOPIC = "decision"


def _iso_duration(text: str) -> timedelta:
    """Minimal ISO-8601 duration parser for HOLD TTLs (PnDTnHnMnS)."""
    import re

    m = re.fullmatch(r"P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?)?", text)
    if not m or text in ("P", "PT"):
        raise ValueError(f"bad ISO-8601 duration {text!r}")
    d, h, mi, s = m.groups()
    return timedelta(days=int(d or 0), hours=int(h or 0), minutes=int(mi or 0), seconds=float(s or 0))


# ---------------------------------------------------------------- steps (non-DB calls)
@DBOS.step()
def fetch_step(adapter_name: str, since: Optional[str]) -> list[dict[str, Any]]:
    return [asdict(r) for r in components().adapters[adapter_name].fetch(since)]


@DBOS.step()
def normalize_step(raw: dict[str, Any]) -> Optional[dict[str, Any]]:
    from mbos.interfaces import RawListing

    norm = components().normalizer.normalize(RawListing(**raw))
    return asdict(norm) if norm is not None else None


@DBOS.step()
def score_step(item: dict[str, Any]) -> dict[str, Any]:
    return asdict(components().scorer.score(item))


@DBOS.step()
def gateway_step(action_request_id: str, approval_id: str) -> dict[str, Any]:
    """The ONLY path to an effector. If the process dies after the effector ran but before this
    step was checkpointed, recovery re-runs the step; the gateway sees the used idempotency key
    and replays the original response instead of acting again (A5)."""
    return asdict(components().gateway.execute(runtime().engine, action_request_id, approval_id))


# ---------------------------------------------------------------- workflows
@DBOS.workflow()
def discover(adapter_name: str, since: Optional[str] = None) -> list[dict[str, Any]]:
    adapter = components().adapters[adapter_name]
    version = getattr(adapter, "version", __version__)
    results = []
    for raw in fetch_step(adapter_name, since):
        norm = normalize_step(raw)
        r = tx(spine.ingest, raw, norm, adapter_name, version, components())
        if r["created"]:
            with SetWorkflowID(item_workflow_id(r["item_id"])):
                DBOS.start_workflow(item_lifecycle, r["item_id"])
        results.append(r)
    return results


@DBOS.workflow()
def item_lifecycle(item_id: str) -> dict[str, Any]:
    item = tx(spine.read_item, item_id)
    if item["state"] not in ("NORMALIZED", "RESEARCHING"):
        return {"status": "skipped", "state": item["state"]}
    sr = score_step(item)
    tx(spine.record_score, item_id, sr)
    routed = tx(spine.route_recommendation, item_id, components())
    if routed["verdict"] != "YES":
        return {"status": routed["verdict"].lower()}
    return _approval_gate(item_id, routed["action_request_id"])


def _approval_gate(item_id: str, areq_id: str) -> dict[str, Any]:
    """Durable wait for Michael's decision. Zero compute while waiting; survives restarts."""
    poll = runtime().settings.approval_poll_seconds
    after_seq = 0
    hold: Optional[dict[str, Any]] = None
    hold_started = last_notice = None
    while True:
        st = tx(spine.poll_decision, areq_id, after_seq)
        appr = st["approval"]
        if appr is not None:
            after_seq = st["approval_seq"]
            d = appr["decision"]
            if d == "YES":
                return _act(item_id, areq_id, appr)
            if d == "NO":
                tx(spine.apply_no, item_id, appr)
                return {"status": "rejected", "action_request_id": areq_id}
            if d == "MODIFY":
                areq_id = tx(spine.apply_modify, item_id, appr)
                after_seq, hold = 0, None
                continue
            if d == "HOLD":
                out = tx(spine.apply_hold, item_id, appr)
                hold, hold_started, last_notice = appr["hold"], parse(appr["decided_at"]), parse(out["now"])
                continue

        now = parse(st["now"])
        deadlines = [parse(st["expires_at"])]
        if now >= deadlines[0]:
            tx(spine.expire, item_id, areq_id)
            return {"status": "expired", "action_request_id": areq_id}
        if hold is not None:
            wake_at = [t for t in (
                parse(hold["hold_until"]) if hold.get("hold_until") else None,
                hold_started + _iso_duration(hold["escalate_after"]) if hold.get("escalate_after") else None,
            ) if t is not None]
            if wake_at and now >= min(wake_at):
                why = "hold_until reached" if hold.get("hold_until") and now >= parse(hold["hold_until"]) else "escalate_after elapsed"
                tx(spine.wake_from_hold, item_id, areq_id, why, components())
                hold = None
                continue
            renotify_at = last_notice + _iso_duration(hold.get("renotify_after", "PT24H"))
            if now >= renotify_at:
                last_notice = parse(tx(spine.renotify, item_id, areq_id, components())["now"])
                continue
            deadlines += wake_at + [renotify_at]
        timeout = max(0.2, min(poll, min((t - now).total_seconds() for t in deadlines)))
        msg = DBOS.recv(DECISION_TOPIC, timeout_seconds=timeout)
        if isinstance(msg, dict) and msg.get("kind") == "ping" and hold is not None \
                and "michael_ping" in (hold.get("wake_on") or []):
            tx(spine.wake_from_hold, item_id, areq_id, "michael_ping", components())
            hold = None


def _act(item_id: str, areq_id: str, approval: dict[str, Any]) -> dict[str, Any]:
    tx(spine.begin_act, item_id, areq_id, approval)
    guard = gateway_step(areq_id, approval["approval_id"])
    result = tx(spine.finish_act, item_id, areq_id, approval, guard)
    return {**result, "action_request_id": areq_id, "approval_id": approval["approval_id"]}


# ---------------------------------------------------------------- entry points used by the CLI / UI
def record_decision(action_request_id: str, decision: str, payload_hash_seen: str, **kw: Any) -> dict[str, Any]:
    """Record Michael's decision (one transaction), then wake the item workflow."""

    def decide(conn: Any) -> dict[str, Any]:
        return spine.decide(conn, action_request_id, decision, payload_hash_seen, components(), **kw)

    out = tx(decide)
    DBOS.send(item_workflow_id(out["item_id"]), {"kind": "decision", "approval_id": out["approval"]["approval_id"]},
              topic=DECISION_TOPIC)
    return out


def ping(item_id: str) -> None:
    DBOS.send(item_workflow_id(item_id), {"kind": "ping"}, topic=DECISION_TOPIC)


def notify_decision(item_id: str, approval_id: str) -> None:
    """Wake an item workflow after a decision was recorded with `spine.decide` in the caller's own transaction
    (Operator UI, CLI). Works from any process: uses DBOS inside a launched runtime, else a DBOSClient.
    The approval row is the truth; this message is only a wake-up (the workflow re-polls on its own)."""
    message = {"kind": "decision", "approval_id": approval_id}
    try:
        DBOS.send(item_workflow_id(item_id), message, topic=DECISION_TOPIC)
    except Exception:
        from mbos.runtime import client

        c = client()
        try:
            c.send(item_workflow_id(item_id), message, topic=DECISION_TOPIC)
        finally:
            c.destroy()
