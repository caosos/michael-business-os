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

import time

from dataclasses import asdict
from datetime import timedelta
from typing import Any, Optional

from dbos import DBOS, EnqueueOptions, SetWorkflowID

from mbos import __version__, spine  # noqa: F401  (reference backend; S() selects)
from mbos.clock import parse
from mbos.runtime import components, item_workflow_id, owner_tx, runtime, spine_module as S, tx

DECISION_TOPIC = "decision"
FOLLOWUP_QUEUE = "followups"
RECHECK_QUEUE = "rechecks"
WAKE_EVENTS = ("price_change", "auction_ending", "new_info")


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
    """Per-record isolation (07 F-36): a poisonous listing makes THIS record fail with a picklable, readable error;
    it never aborts the batch (a CanonicalError on a NUL would otherwise be unpicklable and kill discover)."""
    from mbos.card import scrub
    from mbos.interfaces import RawListing

    try:
        norm = components().normalizer.normalize(RawListing(**raw))
    except Exception as e:  # noqa: BLE001
        try:  # retry once on scrubbed text so a stray control character does not cost us the listing
            clean, _ = scrub(raw)
            norm = components().normalizer.normalize(RawListing(**clean))
        except Exception as e2:  # noqa: BLE001
            return {"__error__": f"{type(e2).__name__}: {str(e2)[:200]}", "listing": raw.get("source_listing_id")}
    return asdict(norm) if norm is not None else None


@DBOS.step()
def research_step(item: dict[str, Any]) -> dict[str, Any]:
    rr = components().researcher.research(item)
    return asdict(rr)


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
        if isinstance(norm, dict) and "__error__" in norm:
            results.append({"item_id": None, "created": False, "merged": False, "dropped": True, "error": norm["__error__"],
                            "listing": norm.get("listing")})
            continue
        r = tx(S().ingest_safe, raw, norm, adapter_name, version, components())
        if r["created"]:
            with SetWorkflowID(item_workflow_id(r["item_id"])):
                DBOS.start_workflow(item_lifecycle, r["item_id"])
        results.append(r)
    return results


@DBOS.workflow()
def item_lifecycle(item_id: str) -> dict[str, Any]:
    item = tx(S().read_item, item_id)
    if item["state"] not in ("NORMALIZED", "RESEARCHING"):
        return {"status": "skipped", "state": item["state"]}
    if components().enrichers:
        tx(S().run_enrichers, item_id, components())  # listing activity / seller facts exist before scoring
    if components().researcher is not None:  # A-05: RESEARCH (lane C, comps via lane B) before SCORE
        rr = research_step(item)
        out = tx(S().record_research, item_id, rr, components())
        if out["next_state"] != "SCORED":
            return {"status": "researching", "gaps": out["gaps"]}
        sr = rr["score"]
    else:
        sr = score_step(item)
    tx(S().record_score, item_id, sr)
    if components().enrichers:
        tx(S().run_enrichers, item_id, components())  # economics / logistics / seasonality / why need the score
    routed = tx(S().route_recommendation, item_id, components())
    if routed["verdict"] != "YES":
        return {"status": routed["verdict"].lower()}
    if routed.get("policy_denied"):  # nothing to approve: the item stays RECOMMENDED and the card says why
        return {"status": "policy_denied", "action_request_id": routed["action_request_id"]}
    return _approval_gate(item_id, routed["action_request_id"])


@DBOS.workflow()
def recheck_lifecycle(item_id: str) -> dict[str, Any]:
    """A-39: re-run the lifecycle for an Item parked at RESEARCHING (a comp was added since). The original per-item workflow id
    is spent, so this is its own workflow; `item_lifecycle` itself skips anything not NORMALIZED/RESEARCHING."""
    return item_lifecycle(item_id)


def recheck(item_ids: list[str]) -> list[str]:
    """Public API (CLI, UI): enqueue `recheck_lifecycle` per Item on the `rechecks` queue (a running worker executes it)."""
    import time

    from mbos.runtime import client

    ids = []
    c = client()
    try:
        for iid in item_ids:
            wf = f"recheck:{iid}:{int(time.time() * 1000)}"
            c.enqueue({"queue_name": RECHECK_QUEUE, "workflow_name": "recheck_lifecycle", "workflow_id": wf}, iid)
            ids.append(wf)
    finally:
        c.destroy()
    return ids


def _approval_gate(item_id: str, areq_id: str) -> dict[str, Any]:
    """Durable wait for Michael's decision. Zero compute while waiting; survives restarts."""
    poll = runtime().settings.approval_poll_seconds
    after_seq = 0
    hold: Optional[dict[str, Any]] = None
    hold_started = last_notice = None
    while True:
        st = tx(S().poll_decision, areq_id, after_seq)
        appr = st["approval"]
        if appr is not None:
            after_seq = st["approval_seq"]
            d = appr["decision"]
            if d == "YES":
                return _act(item_id, areq_id, appr)
            if d == "NO":
                tx(S().apply_no, item_id, appr)
                return {"status": "rejected", "action_request_id": areq_id}
            if d == "MODIFY":
                areq_id = tx(S().apply_modify, item_id, appr)
                after_seq, hold = 0, None
                continue
            if d == "HOLD":
                out = tx(S().apply_hold, item_id, appr)
                hold, hold_started, last_notice = appr["hold"], parse(appr["decided_at"]), parse(out["now"])
                continue

        now = parse(st["now"])
        deadlines = [parse(st["expires_at"])]
        if now >= deadlines[0]:
            tx(S().expire, item_id, areq_id)
            return {"status": "expired", "action_request_id": areq_id}
        if hold is not None:
            wake_at = [t for t in (
                parse(hold["hold_until"]) if hold.get("hold_until") else None,
                hold_started + _iso_duration(hold["escalate_after"]) if hold.get("escalate_after") else None,
            ) if t is not None]
            if wake_at and now >= min(wake_at):
                why = "hold_until reached" if hold.get("hold_until") and now >= parse(hold["hold_until"]) else "escalate_after elapsed"
                tx(S().wake_from_hold, item_id, areq_id, why, components())
                hold = None
                continue
            renotify_at = last_notice + _iso_duration(hold.get("renotify_after", "PT24H"))
            if now >= renotify_at:
                last_notice = parse(tx(S().renotify, item_id, areq_id, components())["now"])
                continue
            deadlines += wake_at + [renotify_at]
        timeout = max(0.2, min(poll, min((t - now).total_seconds() for t in deadlines)))
        msg = DBOS.recv(DECISION_TOPIC, timeout_seconds=timeout)
        if not isinstance(msg, dict):
            continue
        if msg.get("kind") == "ping" and hold is not None and "michael_ping" in (hold.get("wake_on") or []):
            tx(S().wake_from_hold, item_id, areq_id, "michael_ping", components())
            hold = None
        elif msg.get("kind") == "event" and msg.get("event") in WAKE_EVENTS:
            why = f"{msg['event']}: {str(msg.get('summary', ''))[:120]}".rstrip(": ")
            if hold is not None and msg["event"] in (hold.get("wake_on") or []):
                tx(S().wake_from_hold, item_id, areq_id, why, components())
                hold = None
            elif hold is None:  # awaiting a decision: new facts are re-presented, never acted on
                last_notice = parse(tx(S().renotify, item_id, areq_id, components(), why)["now"])


def _act(item_id: str, areq_id: str, approval: dict[str, Any]) -> dict[str, Any]:
    tx(S().begin_act, item_id, areq_id, approval)
    guard = gateway_step(areq_id, approval["approval_id"])
    result = tx(S().finish_act, item_id, areq_id, approval, guard)
    return {**result, "action_request_id": areq_id, "approval_id": approval["approval_id"]}


# ---------------------------------------------------------------- entry points used by the CLI / UI
def record_decision(action_request_id: str, decision: str, payload_hash_seen: str, **kw: Any) -> dict[str, Any]:
    """Record Michael's decision (one transaction), then wake the item workflow."""

    def decide(conn: Any) -> dict[str, Any]:
        return S().decide(conn, action_request_id, decision, payload_hash_seen, components(), **kw)

    out = owner_tx(decide)   # the Approval is written by the owner login, then the workflow is woken (D-26)
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


def notify_event(item_id: str, event: str, summary: str = "", evidence_provenance_id: str | None = None) -> None:
    """Lane B/C → item workflow: something changed about this item (A-08 / B-05).

    `event` ∈ WAKE_EVENTS. The producer records the evidence's provenance FIRST (in its own transaction) and
    passes its id. Effect: a HOLD with a matching `wake_on` is re-presented; an item awaiting a decision is
    re-notified. Nothing is ever executed by an event."""
    if event not in WAKE_EVENTS:
        raise ValueError(f"event must be one of {WAKE_EVENTS}")
    message = {"kind": "event", "event": event, "summary": summary, "evidence_provenance_id": evidence_provenance_id}
    try:
        DBOS.send(item_workflow_id(item_id), message, topic=DECISION_TOPIC)
    except Exception:
        from mbos.runtime import client

        c = client()
        try:
            c.send(item_workflow_id(item_id), message, topic=DECISION_TOPIC)
        finally:
            c.destroy()


# ---------------------------------------------------------------- follow-up actions on an Item that already acted (A-15)
@DBOS.workflow()
def followup_lifecycle(item_id: str, areq_id: str) -> dict[str, Any]:
    """The approval gate for a follow-up request: same wait/decision/act path as the first action, same receipts."""
    return _approval_gate(item_id, areq_id)


def propose_followup(item_id: str, proposed_action: dict[str, Any]) -> dict[str, Any]:
    """Public API (Operator UI, CLI): propose a follow-up action on an ACTED item. Creates the request in one transaction,
    then starts its approval gate on the `followups` queue (a running worker executes it; if none is running the gate
    starts when one is). The item workflow of the first action has already finished, so this is its own workflow."""
    out = tx(lambda conn: S().propose_followup(conn, item_id, proposed_action, components()))
    if out.get("policy_denied") or not out.get("action_request_id"):
        return out
    opts: EnqueueOptions = {"queue_name": FOLLOWUP_QUEUE, "workflow_name": "followup_lifecycle",
                            "workflow_id": f"followup:{out['action_request_id']}"}
    try:
        DBOS.enqueue_workflow_with_options(opts, item_id, out["action_request_id"])
    except Exception:  # not inside a launched runtime (UI/CLI process): enqueue through the client
        from mbos.runtime import client

        c = client()
        try:
            c.enqueue(opts, item_id, out["action_request_id"])
        finally:
            c.destroy()
    return out


def recover_orphan_gates() -> list[str]:
    """07 F-42: a crash between a follow-up request's commit and its gate being enqueued leaves a request waiting on
    Michael with NO workflow behind it (his YES would be accepted and never executed). Find those and start their gate.

    A request is orphaned when neither its item workflow (`item:<id>`) nor a follow-up gate (`followup:<areq>*`) is
    still active. Run at worker start and periodically (`mbos worker`). Idempotent: an active gate is never duplicated."""
    started: list[str] = []
    for g in tx(lambda conn: S().orphan_gates(conn)):
        item_id, areq_id = g["item_id"], g["action_request_id"]
        active = DBOS.list_workflows(status=["PENDING", "ENQUEUED", "DELAYED"], load_input=False, load_output=False,
                                     workflow_id_prefix=[f"item:{item_id}", f"followup:{areq_id}"])
        if active:
            continue
        wf_id = f"followup:{areq_id}:r{int(time.time())}"
        DBOS.enqueue_workflow_with_options({"queue_name": FOLLOWUP_QUEUE, "workflow_name": "followup_lifecycle",
                                            "workflow_id": wf_id}, item_id, areq_id)
        started.append(wf_id)
    return started
