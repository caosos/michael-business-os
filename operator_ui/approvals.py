"""Michael's YES / NO / MODIFY / HOLD decisions (approval.schema.json semantics).

Rules enforced here, each with a test in tests/test_approvals.py:

* YES    — executes the FROZEN payload only. The decision carries the payload_hash
           Michael was shown; if it differs from the stored request the decision is
           refused (StaleView). Nothing from the form can reach the payload.
* NO     — requires a reason; closes the request and (by default) archives the Item.
* MODIFY — never mutates. Creates a NEW ActionRequest (derived_from, new hash, new
           idempotency key) in pending_approval; it needs its own YES.
* HOLD   — durable parked state (approval row + hold_timers row in the DB). `tick()`
           can only remind or re-present a held request; it has no path to execute.

Every decision is one transaction: approval row + provenance + receipts + state.
"""

import hmac
import json
from datetime import timedelta
from zoneinfo import ZoneInfo

from . import TOOL_NAME, __version__
from .util import iso, new_id, parse_duration, parse_iso, sha256_of

MICHAEL = "michael"
LOCAL_TZ = ZoneInfo("America/Chicago")  # Conway / Little Rock AR (ADR-0007 examples)
DECIDABLE = ("pending_approval", "held")
OPEN = ("drafted", "classified", "pending_approval", "held", "approved", "executing")
STEP_UP_CATEGORIES = {"money", "purchase", "external_commitment", "offer"}

# HOLD presets shown in the UI (06 round-two gap item 2). Every preset re-notifies
# daily; none can execute. `hours=None` means "no time wake".
HOLD_PRESETS = {
    "tomorrow_8am": {"label": "Until tomorrow 8am", "wake_on": ["time", "new_info", "price_change"]},
    "24h": {"label": "24 hours", "hours": 24, "wake_on": ["time", "new_info", "price_change"]},
    "3d": {"label": "3 days", "hours": 72, "wake_on": ["time", "new_info", "price_change"]},
    "new_info": {
        "label": "Until new info / price change",
        "hours": None,
        "wake_on": ["new_info", "price_change", "auction_ending"],
        "escalate_after": "PT72H",
    },
}
DEFAULT_RENOTIFY = "PT24H"


class DecisionError(ValueError):
    """The decision cannot be recorded; nothing was written."""


class StaleView(DecisionError):
    """Michael decided on a payload that is no longer the stored one."""


class StepUpRequired(DecisionError):
    pass


def needs_step_up(areq):
    return areq["reversibility"] == "irreversible" or areq["category"] in STEP_UP_CATEGORIES


def payload_diff(old, new):
    keys = sorted(set(old) | set(new))
    return {k: {"from": old.get(k), "to": new.get(k)} for k in keys if old.get(k) != new.get(k)}


class ApprovalService:
    def __init__(self, store, clock, gateway=None, operator_pin=None, channel="web"):
        self.store = store
        self.clock = clock
        self.gateway = gateway
        self.operator_pin = operator_pin
        self.channel = channel

    # ---- helpers ------------------------------------------------------------
    def _human_prov(self, tx, approval_id, now):
        p = {
            "provenance_id": new_id("prov"),
            "created_at": iso(now),
            "actor_type": "human",
            "human_actor": MICHAEL,
            "basis": "FACT",
            "approval_id": approval_id,
        }
        tx.add_provenance(p)
        return p["provenance_id"]

    def _system_prov(self, tx, now, note):
        p = {
            "provenance_id": new_id("prov"),
            "created_at": iso(now),
            "actor_type": "system",
            "agent_name": TOOL_NAME,
            "basis": "FACT",
            "tool_name": f"{TOOL_NAME}.{note}",
            "tool_version": __version__,
        }
        tx.add_provenance(p)
        return p["provenance_id"]

    @staticmethod
    def _action_fields(areq):
        return {
            "item_id": areq["item_id"],
            "action_request_id": areq["action_request_id"],
            "capability": areq["capability"],
            "payload_hash": areq["payload_hash"],
        }

    def set_item_state(self, tx, item_id, state, now, intent, prov_ids, key, actor=None):
        item = self.store.item(item_id)  # same connection: sees this transaction's writes
        before = item["state"]
        if before == state:
            return item
        item = dict(item, state=state, updated_at=iso(now))
        tx.put_item(item)
        tx.add_receipt(
            now,
            type="ITEM_STATE_CHANGED",
            actor=actor or {"type": "system", "id": TOOL_NAME},
            intent=intent,
            item_id=item_id,
            entity_type="item",
            entity_id=item_id,
            effect="update",
            idempotency_key=key,
            before_state={"state": before},
            after_state={"state": state},
            provenance_ids=prov_ids,
            details={"kind": "generic"},
        )
        return item

    def _other_open(self, areq):
        return [
            a for a in self.store.action_requests_for_item(areq["item_id"])
            if a["action_request_id"] != areq["action_request_id"] and a["status"] in OPEN
        ]

    def _load_decidable(self, areq_id, payload_hash_seen, now):
        areq = self.store.action_request(areq_id)
        if areq is None:
            raise DecisionError(f"unknown action request {areq_id}")
        if areq["status"] not in DECIDABLE:
            raise DecisionError(f"{areq_id} is {areq['status']}; only pending/held requests can be decided")
        if not payload_hash_seen or not hmac.compare_digest(payload_hash_seen, areq["payload_hash"]):
            raise StaleView("the payload you saw is not the stored payload; reload the card")
        if sha256_of(areq["payload"]) != areq["payload_hash"]:
            raise StaleView("stored payload does not match its frozen hash; refusing")
        if parse_iso(areq["expires_at"]) <= now:
            raise DecisionError(f"{areq_id} expired at {areq['expires_at']}")
        return areq

    def _approval(self, areq, decision, now, auth, **extra):
        a = {
            "approval_id": new_id("appr"),
            "action_request_id": areq["action_request_id"],
            "decision": decision,
            "decider": MICHAEL,
            "decided_at": iso(now),
            "channel": self.channel,
            "auth_context": auth,
            "payload_hash_seen": areq["payload_hash"],
            "scope": "once",
        }
        a.update({k: v for k, v in extra.items() if v is not None})
        return a

    def _record_decision(self, tx, areq, approval, new_status, now, intent, prov):
        tx.add_approval(approval)
        before = areq["status"]
        areq = dict(areq, status=new_status)
        tx.put_action_request(areq)
        tx.add_receipt(
            now,
            type="APPROVAL_DECIDED",
            actor={"type": "human", "id": MICHAEL},
            intent=intent,
            approval_id=approval["approval_id"],
            effect="none",
            idempotency_key=f"{approval['approval_id']}:decided",
            before_state={"status": before},
            after_state={"status": new_status, "decision": approval["decision"]},
            provenance_ids=[prov],
            details={"kind": "generic"},
            **self._action_fields(areq),
        )
        tx.clear_hold_timer(areq["action_request_id"])
        item = self.store.item(areq["item_id"])
        ids = list(item.get("approval_ids", [])) + [approval["approval_id"]]
        tx.put_item(dict(item, approval_ids=ids, updated_at=iso(now)))
        return areq

    def _auth(self, session_id, step_up):
        return {"method": "localhost_csrf_session", "session_id": session_id or "local", "step_up": step_up}

    # ---- decisions -------------------------------------------------------------
    def yes(self, areq_id, payload_hash_seen, pin=None, session_id=None, execute=True):
        now = self.clock.now()
        areq = self._load_decidable(areq_id, payload_hash_seen, now)
        step_up = False
        if needs_step_up(areq):
            if not self.operator_pin:
                raise StepUpRequired("step-up not configured (MBOS_OPERATOR_PIN unset); irreversible/money YES refused")
            if not pin or not hmac.compare_digest(str(pin), str(self.operator_pin)):
                raise StepUpRequired("this action is irreversible or moves money: step-up PIN required")
            step_up = True
        with self.store.tx() as tx:
            appr = self._approval(areq, "YES", now, self._auth(session_id, step_up))
            prov = self._human_prov(tx, appr["approval_id"], now)
            self._record_decision(tx, areq, appr, "approved", now, "Michael approved the frozen payload as shown", prov)
            self.set_item_state(tx, areq["item_id"], "APPROVED", now, "action approved by Michael", [prov],
                                f"{appr['approval_id']}:item:APPROVED", {"type": "human", "id": MICHAEL})
        result = {"approval": appr}
        if execute and self.gateway is not None:
            result["execution"] = self.gateway.execute(areq_id, appr["approval_id"])
        return result

    def no(self, areq_id, payload_hash_seen, reason, archive=True, session_id=None):
        reason = (reason or "").strip()
        if not reason:
            raise DecisionError("NO requires a reason (it feeds LEARN)")
        now = self.clock.now()
        areq = self._load_decidable(areq_id, payload_hash_seen, now)
        with self.store.tx() as tx:
            appr = self._approval(areq, "NO", now, self._auth(session_id, False), reason=reason)
            prov = self._human_prov(tx, appr["approval_id"], now)
            self._record_decision(tx, areq, appr, "rejected", now, f"Michael said NO: {reason}", prov)
            if not self._other_open(areq):
                state = "ARCHIVED" if archive else "REJECTED"
                self.set_item_state(tx, areq["item_id"], state, now, f"closed after NO: {reason}", [prov],
                                    f"{appr['approval_id']}:item:{state}", {"type": "human", "id": MICHAEL})
        return {"approval": appr}

    def modify(self, areq_id, payload_hash_seen, new_payload, note=None, session_id=None):
        if not isinstance(new_payload, dict):
            raise DecisionError("modified payload must be a JSON object")
        now = self.clock.now()
        areq = self._load_decidable(areq_id, payload_hash_seen, now)
        diff = payload_diff(areq["payload"], new_payload)
        if not diff:
            raise DecisionError("payload unchanged; use YES, NO or HOLD instead")
        new_hash = sha256_of(new_payload)
        new_areq_id = new_id("areq")
        with self.store.tx() as tx:
            appr = self._approval(
                areq, "MODIFY", now, self._auth(session_id, False), reason=note or None,
                modifications={"diff": diff, "new_action_request_id": new_areq_id, "new_payload_hash": new_hash},
            )
            prov = self._human_prov(tx, appr["approval_id"], now)
            # The original is closed; `rejected` is the only terminal non-executed status
            # in the frozen enum. The receipt + approval record that it was superseded.
            self._record_decision(tx, areq, appr, "rejected", now,
                                  f"Michael modified the payload; superseded by {new_areq_id}", prov)
            new = {k: v for k, v in areq.items() if k not in ("policy_decision_ref",)}
            new.update(
                action_request_id=new_areq_id,
                derived_from=areq["action_request_id"],
                created_at=iso(now),
                proposed_by=MICHAEL,
                payload=new_payload,
                payload_hash=new_hash,
                idempotency_key=f"{new_areq_id}:exec",
                status="pending_approval",
                tier=0,
                provenance_ids=list(areq["provenance_ids"]) + [prov],
            )
            tx.put_action_request(new)
            for rtype, intent in (("ACTION_PROPOSED", f"MODIFY of {areq_id} by Michael"),
                                  ("APPROVAL_REQUESTED", "modified request awaits its own YES")):
                tx.add_receipt(
                    now, type=rtype, actor={"type": "human", "id": MICHAEL}, intent=intent, effect="none",
                    idempotency_key=f"{new_areq_id}:{rtype}", provenance_ids=[prov],
                    after_state={"status": "pending_approval", "derived_from": areq_id},
                    details={"kind": "generic"}, **self._action_fields(new),
                )
            item = self.store.item(areq["item_id"])
            tx.put_item(dict(item, action_request_ids=list(item.get("action_request_ids", [])) + [new_areq_id]))
            self.set_item_state(tx, areq["item_id"], "AWAITING_APPROVAL", now, "modified request awaits approval",
                                [prov], f"{appr['approval_id']}:item:AWAITING_APPROVAL")
        return {"approval": appr, "new_action_request_id": new_areq_id}

    def hold(self, areq_id, payload_hash_seen, preset="24h", hold_until=None, reason=None, session_id=None):
        now = self.clock.now()
        areq = self._load_decidable(areq_id, payload_hash_seen, now)
        p = HOLD_PRESETS.get(preset)
        if p is None:
            raise DecisionError(f"unknown HOLD preset {preset!r}")
        wake_on = list(p["wake_on"])
        if hold_until:
            until = parse_iso(hold_until)
            if until.tzinfo is None:
                until = until.replace(tzinfo=LOCAL_TZ)
            if "time" not in wake_on:
                wake_on.insert(0, "time")
        elif preset == "tomorrow_8am":
            local = now.astimezone(LOCAL_TZ) + timedelta(days=1)
            until = local.replace(hour=8, minute=0, second=0, microsecond=0)
        elif p.get("hours"):
            until = now + timedelta(hours=p["hours"])
        else:
            until = None
        if until is not None and until <= now:
            raise DecisionError("hold_until must be in the future")
        escalate = p.get("escalate_after")
        hold = {"wake_on": wake_on, "renotify_after": DEFAULT_RENOTIFY}
        if until is not None:
            hold["hold_until"] = iso(until)
        if escalate:
            hold["escalate_after"] = escalate
        with self.store.tx() as tx:
            appr = self._approval(areq, "HOLD", now, self._auth(session_id, False), hold=hold, reason=reason or None)
            prov = self._human_prov(tx, appr["approval_id"], now)
            self._record_decision(tx, areq, appr, "held", now,
                                  f"Michael parked the request ({p['label'] if not hold_until else 'custom time'})", prov)
            tx.set_hold_timer(
                areq_id, appr["approval_id"], hold.get("hold_until"), wake_on,
                iso(now + parse_duration(DEFAULT_RENOTIFY)), DEFAULT_RENOTIFY,
                iso(now + parse_duration(escalate)) if escalate else None,
            )
            self.set_item_state(tx, areq["item_id"], "HELD", now, "parked by Michael (HOLD)", [prov],
                                f"{appr['approval_id']}:item:HELD", {"type": "human", "id": MICHAEL})
        return {"approval": appr}

    # ---- durable timers (no execution path) -----------------------------------------
    def _represent(self, tx, areq, now, why, prov):
        areq = dict(areq, status="pending_approval")
        tx.put_action_request(areq)
        tx.clear_hold_timer(areq["action_request_id"])
        tx.add_receipt(
            now, type="APPROVAL_REQUESTED", actor={"type": "system", "id": TOOL_NAME},
            intent=f"re-presented to Michael after HOLD: {why}", effect="none",
            idempotency_key=f"{areq['action_request_id']}:represent:{iso(now)}:{why}", provenance_ids=[prov],
            before_state={"status": "held"}, after_state={"status": "pending_approval", "reason": why},
            details={"kind": "generic"}, **self._action_fields(areq),
        )
        self.set_item_state(tx, areq["item_id"], "AWAITING_APPROVAL", now, f"HOLD ended ({why})", [prov],
                            f"{areq['action_request_id']}:item:AWAITING_APPROVAL:{iso(now)}")

    def wake(self, areq_id, condition):
        """Wake a held request on an external condition (new_info, price_change ...). Never executes."""
        now = self.clock.now()
        timer = self.store.hold_timer(areq_id)
        if timer is None or condition not in json.loads(timer["wake_on"]):
            return False
        with self.store.tx() as tx:
            prov = self._system_prov(tx, now, "hold_wake")
            self._represent(tx, self.store.action_request(areq_id), now, f"wake_on:{condition}", prov)
        return True

    def tick(self):
        """Process expiries, HOLD wakes, re-notifies and escalations. Returns event list.

        Deliberately has no reference to the gateway: a held request can only be
        re-presented for a NEW decision, never executed.
        """
        now = self.clock.now()
        events = []
        for areq in self.store.action_requests(DECIDABLE):
            if parse_iso(areq["expires_at"]) <= now:
                with self.store.tx() as tx:
                    prov = self._system_prov(tx, now, "expiry")
                    tx.put_action_request(dict(areq, status="expired"))
                    tx.clear_hold_timer(areq["action_request_id"])
                    tx.add_receipt(
                        now, type="ITEM_STATE_CHANGED", actor={"type": "system", "id": TOOL_NAME},
                        intent="action request expired without a YES; nothing executed",
                        entity_type="action_request", entity_id=areq["action_request_id"], effect="update",
                        item_id=areq["item_id"], action_request_id=areq["action_request_id"],
                        idempotency_key=f"{areq['action_request_id']}:expired",
                        before_state={"status": areq["status"]}, after_state={"status": "expired"},
                        provenance_ids=[prov], details={"kind": "generic"},
                    )
                    if not self._other_open(areq):
                        self.set_item_state(tx, areq["item_id"], "ARCHIVED", now, "request expired", [prov],
                                            f"{areq['action_request_id']}:item:ARCHIVED:expired")
                events.append(("expired", areq["action_request_id"]))
        for t in self.store.hold_timers():
            areq = self.store.action_request(t["action_request_id"])
            if areq is None or areq["status"] != "held":
                continue
            wake_on = json.loads(t["wake_on"])
            why = None
            if t["hold_until"] and "time" in wake_on and parse_iso(t["hold_until"]) <= now:
                why = "hold_until reached"
            elif t["escalate_at"] and parse_iso(t["escalate_at"]) <= now:
                why = "escalated"
            if why:
                with self.store.tx() as tx:
                    prov = self._system_prov(tx, now, "hold_timer")
                    self._represent(tx, areq, now, why, prov)
                events.append((why, areq["action_request_id"]))
            elif t["next_renotify_at"] and parse_iso(t["next_renotify_at"]) <= now:
                with self.store.tx() as tx:
                    prov = self._system_prov(tx, now, "hold_renotify")
                    tx.add_receipt(
                        now, type="APPROVAL_REQUESTED", actor={"type": "system", "id": TOOL_NAME},
                        intent="reminder: request is still on HOLD (no action taken)", effect="none",
                        idempotency_key=f"{areq['action_request_id']}:renotify:{t['next_renotify_at']}",
                        provenance_ids=[prov], after_state={"status": "held", "reminder": True},
                        details={"kind": "generic"}, **self._action_fields(areq),
                    )
                    tx.bump_renotify(areq["action_request_id"],
                                     iso(now + parse_duration(t["renotify_after"] or DEFAULT_RENOTIFY)))
                events.append(("renotified", areq["action_request_id"]))
        return events
