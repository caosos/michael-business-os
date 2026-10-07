"""Dry-run stand-in for Agent 05's Action Gateway (ADR-0005). Lane E owns the real one.

It runs the 8 execution-guard checks against the stored rows, then calls the
dry-run effector. It re-reads the payload from the store and re-hashes it, so
YES can only ever execute the frozen payload Michael saw.
"""

import hmac

from . import TOOL_NAME, __version__
from .util import iso, new_id, parse_iso, sha256_of

DRY_RUN_MODES = {"round_one", "mvp"}


class GuardDenied(RuntimeError):
    def __init__(self, check, msg):
        super().__init__(f"guard check '{check}' denied: {msg}")
        self.check = check


class DryRunGateway:
    def __init__(self, store, clock, effector, approvals=None):
        self.store = store
        self.clock = clock
        self.effector = effector
        self.approvals = approvals  # ApprovalService, for item-state receipts

    def _prov(self, tx, now, approval_id):
        p = {
            "provenance_id": new_id("prov"),
            "created_at": iso(now),
            "actor_type": "system",
            "agent_name": TOOL_NAME,
            "basis": "FACT",
            "tool_name": self.effector.tool_name,
            "tool_version": self.effector.tool_version,
            "approval_id": approval_id,
        }
        tx.add_provenance(p)
        return p["provenance_id"]

    def guard(self, areq, approval):
        """The 7 checks of 05 §13 plus ADR-0005's 8th (forced dry-run). Returns dry_run flag."""
        now = self.clock.now()
        if approval is None or approval["decision"] != "YES" or approval["action_request_id"] != areq["action_request_id"]:
            raise GuardDenied("approval_valid", "no YES approval for this request")
        if areq["status"] not in ("approved", "executing"):
            raise GuardDenied("approval_valid", f"request status is {areq['status']}")
        if parse_iso(areq["expires_at"]) <= now or (approval.get("expires_at") and parse_iso(approval["expires_at"]) <= now):
            raise GuardDenied("not_expired", "approval or request expired")
        if not hmac.compare_digest(approval["payload_hash_seen"], areq["payload_hash"]) or sha256_of(areq["payload"]) != areq["payload_hash"]:
            raise GuardDenied("payload_hash_match", "payload differs from the one Michael approved")
        if self.store.receipt_by_key(f"{areq['action_request_id']}:executed") is not None:
            raise GuardDenied("idempotency_unused", "already executed")
        cost = (areq.get("estimated_cost") or {}).get("amount", 0)
        if cost or areq["category"] in ("money", "purchase"):
            raise GuardDenied("budget_reserved", "real-world spend is deny-all until MICHAEL_DECISIONS #1 and lane E's budget ledger")
        if areq["tier"] != 0:
            raise GuardDenied("grant_ok", "delegation tiers are disabled (MICHAEL_DECISIONS #5)")
        try:
            state = self.store.system("system_state")
            mode = self.store.system("system_mode")
        except Exception as e:  # unreadable kill switch => frozen (A9)
            raise GuardDenied("kill_switch_clear", f"system state unreadable ({e}); failing closed")
        if state != "RUNNING":
            raise GuardDenied("kill_switch_clear", f"system_state={state}")
        if mode not in DRY_RUN_MODES:
            raise GuardDenied("dry_run_forced", f"system_mode={mode!r}: wave one has no live mode")
        return True

    def execute(self, areq_id, approval_id):
        now = self.clock.now()
        areq = self.store.action_request(areq_id)
        approval = self.store.approval(approval_id)
        base = {
            "item_id": areq["item_id"], "action_request_id": areq_id, "capability": areq["capability"],
            "payload_hash": areq["payload_hash"], "approval_id": approval_id,
        }
        try:
            dry_run = self.guard(areq, approval)
        except GuardDenied as e:
            with self.store.tx() as tx:
                prov = self._prov(tx, now, approval_id)
                tx.add_receipt(
                    now, type="POLICY_DECIDED", actor={"type": "system", "id": TOOL_NAME},
                    intent=f"execution guard denied: {e}", effect="none",
                    idempotency_key=f"{areq_id}:guard_denied:{iso(now)}:{e.check}", provenance_ids=[prov],
                    after_state={"decision": "deny", "check": e.check}, details={"kind": "generic"}, **base,
                )
            return {"status": "denied", "check": e.check, "error": str(e)}

        if areq["status"] == "approved":
            with self.store.tx() as tx:
                prov = self._prov(tx, now, approval_id)
                tx.put_action_request(dict(areq, status="executing"))
                tx.add_receipt(
                    now, type="ACTION_EXECUTING", actor={"type": "system", "id": TOOL_NAME},
                    intent="guard passed (8/8); calling dry-run effector", effect="none",
                    idempotency_key=f"{areq_id}:executing", provenance_ids=[prov],
                    before_state={"status": "approved"}, after_state={"status": "executing"},
                    details={"kind": "generic"}, **base,
                )
                if self.approvals:
                    self.approvals.set_item_state(tx, areq["item_id"], "ACTING", now, "executing approved action",
                                                  [prov], f"{areq_id}:item:ACTING")
            areq = self.store.action_request(areq_id)

        # Outside the transaction, as a DBOS step would be. A crash here is recovered by
        # `resume()`: the effector replays by idempotency key instead of sending twice.
        try:
            resp, replayed = self.effector.execute(areq, dry_run=dry_run)
        except Exception as e:  # noqa: BLE001 — every failure gets a receipt
            with self.store.tx() as tx:
                prov = self._prov(tx, now, approval_id)
                tx.put_action_request(dict(areq, status="failed"))
                tx.add_receipt(
                    now, type="ACTION_FAILED", actor={"type": "system", "id": TOOL_NAME},
                    intent=f"effector failed: {e}", effect="none",
                    effector_response={"provider": self.effector.provider, "status": "error", "dry_run": True},
                    idempotency_key=f"{areq_id}:failed", provenance_ids=[prov],
                    details=self.effector.details_for(areq), **base,
                )
                if self.approvals:
                    self.approvals.set_item_state(tx, areq["item_id"], "FAILED", now, "effector failed", [prov],
                                                  f"{areq_id}:item:FAILED")
            return {"status": "failed", "error": str(e)}

        now = self.clock.now()
        with self.store.tx() as tx:
            prov = self._prov(tx, now, approval_id)
            tx.put_action_request(dict(areq, status="executed"))
            tx.add_receipt(
                now, type="ACTION_EXECUTED", actor={"type": "system", "id": TOOL_NAME},
                intent="DRY RUN: recorded what would have been sent; nothing left this machine",
                effect="send" if areq["capability"].startswith("comms.") else "none",
                tool_name=f"{self.effector.tool_name}@{self.effector.tool_version}",
                effector_response=resp, idempotency_key=f"{areq_id}:executed", provenance_ids=[prov],
                before_state={"status": "executing"}, after_state={"status": "executed", "replayed": replayed},
                details=self.effector.details_for(areq), **base,
            )
            if self.approvals:
                self.approvals.set_item_state(tx, areq["item_id"], "ACTED", now, "dry-run action recorded", [prov],
                                              f"{areq_id}:item:ACTED")
        return {"status": "executed", "effector_response": resp, "replayed": replayed}

    def resume(self):
        """Crash recovery: finish any request left in `executing` (A5). No duplicate sends."""
        done = []
        for areq in self.store.action_requests(["approved", "executing"]):
            yes = [a for a in self.store.approvals_for(areq["action_request_id"]) if a["decision"] == "YES"]
            if yes:
                done.append(self.execute(areq["action_request_id"], yes[-1]["approval_id"]))
        return done
