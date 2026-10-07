from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mbos_governance import ActionGateway, GovernanceStore, PanicStore, PolicyStore
from mbos_governance.ids import fmt_ts, new_id, payload_hash

REPO = Path(__file__).resolve().parents[1]
# 15:00Z = 10:00 America/Chicago — outside quiet hours.
NOON = datetime(2026, 10, 7, 15, 0, tzinfo=timezone.utc)

CATEGORY_CAPABILITY = {
    "message": ("comms.message.send", "agent-06-communications"),
    "sms": ("comms.sms.send", "agent-06-communications"),
    "phone_call": ("comms.voice.call", "agent-06-communications"),
    "email": ("comms.email.send", "agent-06-communications"),
    "scheduling": ("schedule.appointment.create", "agent-06-communications"),
    "publishing": ("publish.listing.create", "agent-07-marketing"),
    "offer": ("offer.submit", "agent-01-coordinator"),
    "money": ("money.payment.send", "agent-01-coordinator"),
    "purchase": ("purchase.create", "agent-01-coordinator"),
    "price_change": ("price.change", "agent-01-coordinator"),
    "external_commitment": ("commit.external", "agent-01-coordinator"),
}


class Clock:
    def __init__(self, now: datetime):
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kw) -> None:
        self.now = self.now + timedelta(**kw)


class Env:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.policy_path = tmp / "policy" / "policy.v1.json"
        self.policy_path.parent.mkdir()
        shutil.copy(REPO / "policy" / "policy.v1.json", self.policy_path)
        shutil.copy(REPO / "policy" / "policy.schema.json", self.policy_path.parent / "policy.schema.json")
        shutil.copy(REPO / "policy" / "content_rules.v1.json", self.policy_path.parent / "content_rules.v1.json")
        self.clock = Clock(NOON)
        self.panic = PanicStore(tmp / "panic_state.json")
        self.panic.init("michael", "test bootstrap", state="RUNNING")
        self.store = GovernanceStore(tmp / "gov.sqlite3")
        self.gw = ActionGateway(self.store, PolicyStore(self.policy_path), self.panic, clock=self.clock)

    # ---- builders ----
    def provenance(self) -> str:
        return self.gw.record_provenance({
            "provenance_id": new_id("prov"), "created_at": fmt_ts(self.clock()), "actor_type": "agent",
            "agent_name": "test", "basis": "INFERENCE", "model_id": "test-model", "model_version": "1",
            "prompt_hash": "sha256:" + "0" * 64})

    def ar(self, category: str = "email", **over) -> dict:
        cap, agent = CATEGORY_CAPABILITY[category]
        payload = over.pop("payload", {"to_ref": "relay:EXAMPLE-0001", "template_id": "t1", "n": new_id("x")})
        reversibility = over.pop("reversibility", "reversible")
        body = {
            "action_request_id": new_id("areq"),
            "item_id": new_id("itm"),
            "created_at": fmt_ts(self.clock()),
            "proposed_by": agent,
            "on_behalf_of": "michael",
            "capability": cap,
            "category": category,
            "payload": payload,
            "payload_hash": payload_hash(payload),
            "idempotency_key": new_id("idem"),
            "reversibility": reversibility,
            "tier": 0,
            "status": "drafted",
            "expires_at": fmt_ts(self.clock() + timedelta(hours=48)),
            "provenance_ids": [self.provenance()],
        }
        if category in ("offer", "money", "purchase", "external_commitment"):
            body["estimated_cost"] = {"amount": 100, "currency": "USD"}
        body.update(over)
        return body

    def approval(self, ar: dict, decision: str = "YES", **over) -> dict:
        body = {
            "approval_id": new_id("appr"),
            "action_request_id": ar["action_request_id"],
            "decision": decision,
            "decider": "michael",
            "decided_at": fmt_ts(self.clock()),
            "channel": "web",
            "auth_context": {"method": "webauthn", "step_up": True},
            "payload_hash_seen": ar["payload_hash"],
            "scope": "once",
        }
        if decision == "NO":
            body["reason"] = "not interested"
        if decision == "HOLD":
            body["hold"] = {"hold_until": fmt_ts(self.clock() + timedelta(hours=12)), "wake_on": ["time"]}
        if decision == "MODIFY":
            body["modifications"] = {"diff": {"n": "changed"}}
        body.update(over)
        return body

    def propose(self, category: str = "email", **over) -> dict:
        ar = self.ar(category, **over)
        res = self.gw.propose(ar, ar["proposed_by"])
        assert res.outcome == "pending_approval", res
        return ar

    def approved(self, category: str = "email", **over) -> dict:
        ar = self.propose(category, **over)
        res = self.gw.record_approval(self.approval(ar))
        assert res.status == "approved" and not res.reasons, res
        return ar

    def policy_edit(self, fn) -> None:
        data = json.loads(self.policy_path.read_text())
        fn(data)
        self.policy_path.write_text(json.dumps(data))
        st = self.policy_path.stat()  # guarantee the reload stamp changes
        os.utime(self.policy_path, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))


@pytest.fixture
def env(tmp_path) -> Env:
    return Env(tmp_path)
