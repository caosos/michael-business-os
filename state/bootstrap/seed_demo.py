"""Seed a realistic DRY-RUN history for drills (restore, crash, reporting). Never contacts anything.

usage: MBOS_DSN=... python bootstrap/seed_demo.py [N_ITEMS]
Every write goes through the mbos.* API, so the seeded chain is a normal MBOS-RH-1 chain.
"""

from __future__ import annotations

import os
import sys
import uuid

import psycopg

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mbos_state.store import Actor, StateStore  # noqa: E402

AGENT, GW, MICHAEL = Actor("agent", "agent-02-opportunity"), Actor("system", "action-gateway"), Actor("human", "michael")


def k(label: str) -> str:
    return f"seed:{label}:{uuid.uuid4().hex}"


def main(n: int) -> None:
    with psycopg.connect(os.environ["MBOS_DSN"], autocommit=True) as conn:
        s = StateStore(conn)
        pid = s.record_provenance(actor_type="system", basis="FACT", tool_name="seed_demo", tool_version="1")
        if not conn.execute("SELECT count(*) FROM mbos.panic_state").fetchone()[0]:
            conn.execute("SELECT mbos.panic_init(%s,'drill seed',%s,%s,'RUNNING')", (MICHAEL.as_json(), [pid], k("panic")))
        for i in range(n):
            lane = ("flip", "trailer") if i % 2 == 0 else ("service", "drywall_repair")
            item = s.create_item({"type": lane[0], "category": lane[1], "dedup_key": f"seed|{lane[1]}|{i % 5}",
                                  "sources": [], "normalized": {"title": f"seed {i}"}}, AGENT, "seed ingest", [pid], k("i"))
            for st in ("NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL"):
                s.transition_item(item, st, AGENT, f"seed -> {st}", [pid], k("t"))
            payload = {"to_ref": f"party_{i}", "body": f"Is it still available? offer {850.0 + i}", "offer": 850.0 + i}
            areq = s.propose_action({"item_id": item, "proposed_by": "agent-01-coordinator", "capability": "comms.email.send",
                                     "category": "email", "payload": payload, "idempotency_key": k("eff"),
                                     "reversibility": "irreversible", "tier": 0, "expires_at": "2099-01-01T00:00:00Z",
                                     "provenance_ids": [pid]}, AGENT, "draft seller question", k("p"))
            s.set_action_status(areq, "classified", "POLICY_DECIDED", GW, "tier 0", [pid], k("c"))
            s.set_action_status(areq, "pending_approval", "APPROVAL_REQUESTED", GW, "ask Michael", [pid], k("r"))
            h = conn.execute("SELECT payload_hash FROM mbos.action_requests WHERE action_request_id=%s", (areq,)).fetchone()[0]
            base = {"action_request_id": areq, "decider": "michael", "channel": "cli", "payload_hash_seen": h,
                    "scope": "once", "auth_context": {"method": "cli", "step_up": True}}
            if i % 3 == 2:
                s.record_approval({**base, "decision": "HOLD", "hold": {"hold_until": "2026-10-10T00:00:00Z",
                                   "wake_on": ["time"]}}, MICHAEL, "SIMULATED drill HOLD", k("a"))
                s.transition_item(item, "HELD", MICHAEL, "held", [pid], k("t"))
                continue
            appr = s.record_approval({**base, "decision": "YES"}, MICHAEL, "SIMULATED drill YES", k("a"))
            s.transition_item(item, "APPROVED", MICHAEL, "approved", [pid], k("t"))
            s.transition_item(item, "ACTING", GW, "acting", [pid], k("t"))
            s.set_action_status(areq, "executing", "ACTION_EXECUTING", GW, "guard ok", [pid], k("x"), extra={"approval_id": appr})
            resp = {"provider": "dry-run:comms.email.send", "provider_msg_id": f"dry_{i}", "status": "simulated", "dry_run": True}
            conn.execute("SELECT * FROM mbos.record_effector_call(%s,'dry-run',%s,%s,%s)",
                         (areq, f"dry_{i}", psycopg.types.json.Jsonb(payload), psycopg.types.json.Jsonb(resp)))
            s.set_action_status(areq, "executed", "ACTION_EXECUTED", GW, "dry-run sent", [pid], k("e"),
                                extra={"approval_id": appr, "effect": "send", "effector_response": resp,
                                       "details": {"kind": "comms"}})
            s.transition_item(item, "ACTED", GW, "acted", [pid], k("t"))
            s.record_outcome({"item_id": item, "action_request_id": areq, "kind": "message_replied", "provenance_ids": [pid],
                              "realized": {"revenue": 0, "total_cost": 0.0, "net_profit": 0}}, AGENT, "reply", k("o"))
        conn.execute("INSERT INTO mbos.llm_spend (agent_id, usd) VALUES ('agent-03-economics', 0.0)")
        conn.execute("SELECT mbos.put_artifact(%s, 'text/plain')", (b"seed artifact",))
        print("seeded; head:", s.chain_head())


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 12)
