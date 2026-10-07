"""Operator UI → spine adapter (coordinator ruling R10).

Reads come straight from the spine's Postgres tables (read-only). The write paths are
`decide()` and `record_outcome()`: `mbos.spine.decide` in ONE transaction (approval + provenance + receipt + status),
then `mbos.workflows.notify_decision` to wake the item workflow, the same path as `mbos decide` (CLI).
The UI owns no gateway, no timers and no ledger. Execution happens only in the item
workflow → lane E gateway → dry-run effector.
"""

from __future__ import annotations

from typing import Any, Optional

import sqlalchemy as sa

from mbos import spine
from mbos.ledger import load_receipts, verify_chain
from mbos.runtime import Components, client, item_workflow_id
from mbos.workflows import DECISION_TOPIC, notify_decision

from . import mbos_canonical


class SpineBackend:
    def __init__(self, engine: sa.Engine, components: Optional[Components] = None, notify=None):
        self.engine = engine
        # Must match the worker's lanes: spine.decide classifies a MODIFY successor with the PDP.
        self.components = components or Components().with_defaults()
        self._notify = notify or notify_decision  # spine's wake helper (A-07)

    # ---- reads ---------------------------------------------------------------------------
    def _bodies(self, sql: str, **params: Any) -> list[dict]:
        with self.engine.connect() as c:
            return [r[0] for r in c.execute(sa.text(sql), params)]

    def _body(self, sql: str, **params: Any) -> Optional[dict]:
        rows = self._bodies(sql, **params)
        return rows[0] if rows else None

    def item(self, item_id: str) -> Optional[dict]:
        return self._body("SELECT body FROM mbos.items WHERE item_id = :i", i=item_id)

    def action_request(self, areq_id: str) -> Optional[dict]:
        return self._body("SELECT body FROM mbos.action_requests WHERE action_request_id = :a", a=areq_id)

    def action_requests(self, limit: int = 200) -> list[dict]:
        return self._bodies("SELECT body FROM mbos.action_requests ORDER BY body->>'created_at' DESC LIMIT :n", n=limit)

    def action_requests_for_item(self, item_id: str) -> list[dict]:
        return self._bodies("SELECT body FROM mbos.action_requests WHERE item_id = :i ORDER BY body->>'created_at'", i=item_id)

    def pending(self) -> list[dict]:
        with self.engine.connect() as c:
            return spine.pending_decisions(c)

    def approvals_for(self, areq_id: str) -> list[dict]:
        return self._bodies("SELECT body FROM mbos.approvals WHERE action_request_id = :a ORDER BY seq", a=areq_id)

    def provenance(self, prov_id: str) -> Optional[dict]:
        return self._body("SELECT body FROM mbos.provenance WHERE provenance_id = :p", p=prov_id)

    def receipts(self, item_id: Optional[str] = None, areq_id: Optional[str] = None, limit: int = 500) -> list[dict]:
        where, params = ["true"], {"n": limit}
        if item_id:
            where.append("item_id = :i")
            params["i"] = item_id
        if areq_id:
            where.append("action_request_id = :a")
            params["a"] = areq_id
        sql = f"seq IN (SELECT seq FROM mbos.receipts WHERE {' AND '.join(where)} ORDER BY seq DESC LIMIT :n)"
        with self.engine.connect() as c:
            return load_receipts(c, sql, params)  # adds seq / prev_hash / row_hash (columns, not body)

    def active_hold(self, areq: dict) -> Optional[dict]:
        """The HOLD in force, as recorded on the latest approval (the workflow owns the timer)."""
        if areq["status"] != "held":
            return None
        last = (self.approvals_for(areq["action_request_id"]) or [None])[-1]
        return last.get("hold") if last and last["decision"] == "HOLD" else None

    def system_state(self) -> str:
        try:
            with self.engine.connect() as c:
                v = c.execute(sa.text("SELECT value FROM mbos.governance_flags WHERE key = 'global_freeze'")).scalar_one_or_none()
        except Exception:  # noqa: BLE001
            return "UNREADABLE (fail-closed)"
        if not isinstance(v, dict) or v.get("frozen") is not False:
            return "FROZEN"
        return "RUNNING"

    def verify_chain(self) -> dict:
        with self.engine.connect() as c:
            return verify_chain(c)

    def verify_chain_independent(self) -> tuple[bool, str]:
        """Re-verify the exported chain with the vendored ADR-0010 reference (MBOS-RH-1), in Python,
        independent of the database's own verify_chain. Read-only."""
        with self.engine.connect() as c:
            chain = load_receipts(c)
        try:
            return mbos_canonical.verify_chain(chain)
        except Exception as e:  # noqa: BLE001 — a value the reference rejects is a failed verification
            return False, f"reference rejected the chain: {type(e).__name__}: {e}"

    def held(self) -> list[dict]:
        """HOLD backlog: held requests with their item and the HOLD in force (approval row)."""
        rows = []
        for areq in self._bodies("SELECT body FROM mbos.action_requests WHERE status = 'held' ORDER BY body->>'created_at'"):
            last = (self.approvals_for(areq["action_request_id"]) or [None])[-1]
            rows.append({"action_request": areq, "item": self.item(areq["item_id"]),
                         "hold": (last or {}).get("hold") or {}, "held_at": (last or {}).get("decided_at"),
                         "reason": (last or {}).get("reason")})
        return rows

    def outcomes(self, item_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        if item_id:
            return self._bodies("SELECT body FROM mbos.outcomes WHERE body->>'item_id' = :i ORDER BY body->>'observed_at'", i=item_id)
        return self._bodies("SELECT body FROM mbos.outcomes ORDER BY body->>'observed_at' DESC LIMIT :n", n=limit)

    def record_outcome(self, item_id: str, kind: str, **kw: Any) -> dict:
        """Second (and last) write path: Michael records what actually happened (feeds LEARN, lane C)."""
        with self.engine.begin() as c:
            return spine.record_outcome(c, item_id, kind, recorded_by="michael", **kw)

    # ---- the one write path -----------------------------------------------------------------
    def decide(self, areq_id: str, decision: str, payload_hash_seen: str, **kw: Any) -> dict:
        with self.engine.begin() as c:
            out = spine.decide(c, areq_id, decision, payload_hash_seen, self.components, channel="web", **kw)
        # Wake-up only: if this message is lost, the workflow still finds the row on its next poll.
        self._notify(out["item_id"], out["approval"]["approval_id"])
        return out

    def ping(self, item_id: str) -> None:
        """'Wake now' for a HOLD whose wake_on includes michael_ping (re-presents; never executes)."""
        _client_send(item_id, {"kind": "ping"})


def _client_send(item_id: str, message: dict) -> None:
    """The spine's `workflows.ping` needs a launched DBOS runtime; the UI process uses a DBOSClient."""
    c = client()
    try:
        c.send(item_workflow_id(item_id), message, topic=DECISION_TOPIC)
    finally:
        c.destroy()
