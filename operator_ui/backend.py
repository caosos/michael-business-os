"""Operator UI → spine adapter (coordinator ruling R10).

Two state backends, selected by `lane`: "reference" (Agent 01's own DDL, `mbos.spine`) and "lane_d"
(Agent 04's canonical store, `mbos.spine_d`; F-04). On lane D, reads use lane D's contract-document views
(`mbos.v_*_documents`, `mbos.receipt_document`, `mbos.panic_read()`) and every write goes through
`mbos.spine_d`, which writes only via lane D's SQL API. The UI never touches lane D's tables directly
for writes.

Reads come straight from the spine's Postgres tables (read-only). The write paths are
`decide()` and `record_outcome()`: `mbos.spine.decide` in ONE transaction (approval + provenance + receipt + status),
then `mbos.workflows.notify_decision` to wake the item workflow, the same path as `mbos decide` (CLI).
The UI owns no gateway, no timers and no ledger. Execution happens only in the item
workflow → lane E gateway → dry-run effector.
"""

from __future__ import annotations

from typing import Any, Optional

import sqlalchemy as sa

from mbos.ledger import load_receipts, verify_chain
from mbos.runtime import Components, client, item_workflow_id
from mbos.workflows import DECISION_TOPIC, notify_decision

from . import mbos_canonical

# (doc view, id column) per entity on lane D; reference reads `body` from the spine's own tables.
_LD = {"item": ("mbos.v_item_documents", "item_id"), "areq": ("mbos.v_action_request_documents", "action_request_id"),
       "prov": ("mbos.v_provenance_documents", "provenance_id"), "outc": ("mbos.v_outcome_documents", "outcome_id")}


class ProfileUnavailable(RuntimeError):
    pass


class NoteRefused(Exception):
    """The note was not stored. `.reasons` are shown to Michael verbatim."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


class ItemNotFound(Exception):
    """Unknown item id. Deliberately NOT a LookupError: a KeyError from the card builder must surface as a failure."""


class SpineBackend:
    def __init__(self, engine: sa.Engine, components: Optional[Components] = None, notify=None, lane: str = "reference"):
        if lane not in ("reference", "lane_d"):
            raise ValueError(f"unknown state backend {lane!r}")
        self.engine = engine
        self.lane = lane
        if lane == "lane_d":
            from mbos import spine_d as _spine
        else:
            from mbos import spine as _spine
        self._spine = _spine
        # Must match the worker's lanes: spine.decide classifies a MODIFY successor with the PDP.
        self.components = components or Components().with_defaults(lane)
        self._notify = notify or notify_decision  # spine's wake helper (A-07)

    # ---- reads ---------------------------------------------------------------------------
    def _bodies(self, sql: str, **params: Any) -> list[dict]:
        with self.engine.connect() as c:
            return [r[0] for r in c.execute(sa.text(sql), params)]

    def _body(self, sql: str, **params: Any) -> Optional[dict]:
        rows = self._bodies(sql, **params)
        return rows[0] if rows else None

    def item(self, item_id: str) -> Optional[dict]:
        if self.lane == "lane_d":
            return self._body("SELECT doc FROM mbos.v_item_documents WHERE item_id = :i", i=item_id)
        return self._body("SELECT body FROM mbos.items WHERE item_id = :i", i=item_id)

    def action_request(self, areq_id: str) -> Optional[dict]:
        if self.lane == "lane_d":
            return self._body("SELECT doc FROM mbos.v_action_request_documents WHERE action_request_id = :a", a=areq_id)
        return self._body("SELECT body FROM mbos.action_requests WHERE action_request_id = :a", a=areq_id)

    def action_requests(self, limit: int = 200) -> list[dict]:
        if self.lane == "lane_d":
            return self._bodies("SELECT doc FROM mbos.v_action_request_documents ORDER BY doc->>'created_at' DESC LIMIT :n", n=limit)
        return self._bodies("SELECT body FROM mbos.action_requests ORDER BY body->>'created_at' DESC LIMIT :n", n=limit)

    def items_in_states(self, states) -> list[dict]:
        if self.lane == "lane_d":
            return self._bodies("SELECT doc FROM mbos.v_item_documents WHERE doc->>'state' = ANY(:s)", s=list(states))
        return self._bodies("SELECT body FROM mbos.items WHERE state = ANY(:s)", s=list(states))

    def action_requests_for_item(self, item_id: str) -> list[dict]:
        if self.lane == "lane_d":
            return self._bodies("SELECT doc FROM mbos.v_action_request_documents WHERE doc->>'item_id' = :i "
                                "ORDER BY doc->>'created_at'", i=item_id)
        return self._bodies("SELECT body FROM mbos.action_requests WHERE item_id = :i ORDER BY body->>'created_at'", i=item_id)

    def pending(self) -> list[dict]:
        with self.engine.connect() as c:
            return self._spine.pending_decisions(c)

    def approvals_for(self, areq_id: str) -> list[dict]:
        if self.lane == "lane_d":
            return self._bodies("SELECT d.doc FROM mbos.v_approval_documents d JOIN mbos.approvals a USING (approval_id) "
                                "WHERE a.action_request_id = :a ORDER BY a.seq", a=areq_id)
        return self._bodies("SELECT body FROM mbos.approvals WHERE action_request_id = :a ORDER BY seq", a=areq_id)

    def provenance(self, prov_id: str) -> Optional[dict]:
        if self.lane == "lane_d":
            return self._body("SELECT doc FROM mbos.v_provenance_documents WHERE provenance_id = :p", p=prov_id)
        return self._body("SELECT body FROM mbos.provenance WHERE provenance_id = :p", p=prov_id)

    def receipts(self, item_id: Optional[str] = None, areq_id: Optional[str] = None, limit: int = 500) -> list[dict]:
        where, params = ["true"], {"n": limit}
        if item_id:
            where.append("item_id = :i")
            params["i"] = item_id
        if areq_id:
            where.append("action_request_id = :a")
            params["a"] = areq_id
        if self.lane == "lane_d":  # contract-shaped documents (seq / prev_hash / row_hash included)
            w = " AND ".join(x.replace("item_id", "doc->>'item_id'").replace("action_request_id", "doc->>'action_request_id'")
                             if "doc->>" not in x else x for x in where)
            rows = self._bodies(f"SELECT doc FROM (SELECT seq, doc FROM mbos.v_receipt_documents WHERE {w} "
                                f"ORDER BY seq DESC LIMIT :n) t ORDER BY seq", **params)
            return rows
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
                if self.lane == "lane_d":  # R5: sealed PANIC state in Postgres; unreadable or FROZEN → FROZEN
                    r = c.execute(sa.text("SELECT global_state, readable FROM mbos.panic_read()")).one()
                    return "RUNNING" if (r.readable and r.global_state == "RUNNING") else "FROZEN"
                v = c.execute(sa.text("SELECT value FROM mbos.governance_flags WHERE key = 'global_freeze'")).scalar_one_or_none()
        except Exception:  # noqa: BLE001
            return "UNREADABLE (fail-closed)"
        if not isinstance(v, dict) or v.get("frozen") is not False:
            return "FROZEN"
        return "RUNNING"

    def verify_chain(self) -> dict:
        with self.engine.connect() as c:
            if self.lane == "lane_d":
                from mbos.adapters.state04 import Pg04Ledger

                return Pg04Ledger().verify_chain(c)
            return verify_chain(c)

    def verify_chain_independent(self) -> tuple[bool, str]:
        """Re-verify the exported chain with the vendored ADR-0010 reference (MBOS-RH-1), in Python,
        independent of the database's own verify_chain. Read-only."""
        with self.engine.connect() as c:
            if self.lane == "lane_d":
                from mbos.adapters.state04 import Pg04Ledger

                chain = Pg04Ledger().export_receipts(c)
            else:
                chain = load_receipts(c)
        try:
            return mbos_canonical.verify_chain(chain)
        except Exception as e:  # noqa: BLE001 — a value the reference rejects is a failed verification
            return False, f"reference rejected the chain: {type(e).__name__}: {e}"

    def opportunity_card(self, item_id: str) -> dict:
        """F-13: the ADR-0011 card for one Item, from Agent 01's API only (works on both backends). Returns
        {'card', 'errors', 'areqs'}; raises ItemNotFound for an unknown item. Nothing here adds data."""
        import os

        from mbos import card as mc

        # Michael's capability profile (trailer owned? ...) is lane A's data. A non-editable mbos install cannot find
        # its default location (repo-relative), so MBOS_OPERATOR_PROFILE may point at it. Missing = a clear error,
        # never a made-up profile.
        profile_path = os.environ.get("MBOS_OPERATOR_PROFILE") or None
        try:
            profile = mc.load_profile(profile_path)
        except OSError as ex:
            raise ProfileUnavailable(f"operator profile not found ({ex.filename or profile_path}); set MBOS_OPERATOR_PROFILE "
                                     "to config/operator_profile.v1.json from the mbos checkout") from ex
        try:
            with self.engine.connect() as c:
                item, receipts, areqs = mc.load_inputs(c, item_id)
                enr = mc.enrichment_from_item(c, item)
        except sa.exc.NoResultFound:
            raise ItemNotFound(item_id) from None
        card = mc.build_card(item, receipts, areqs, enr, profile=profile)
        return {"card": card, "errors": mc.validate_card(card), "areqs": areqs}

    # ---- F-14: Michael's own model knowledge (operator notes). Lane D only; HUMAN CHANNEL ONLY (R14) -----------
    def operator_notes(self) -> list[dict]:
        """Current head of every note chain (retractions included), from lane D's folded document."""
        if self.lane != "lane_d":
            return []
        with self.engine.connect() as c:
            return self._spine.operator_notes_document(c)["notes"]

    def record_operator_note(self, bundle: dict) -> str:
        """The ONLY caller of spine_d.record_operator_note in the system besides the CLI (`mbos_dbos` holds the approver
        role, so the database cannot stop a workflow from calling it; the code path must). `bundle` comes from
        `mbos_economics.new_manual_note` with the AUTHENTICATED author. Database refusals are returned as NoteRefused."""
        if self.lane != "lane_d":
            raise NoteRefused(["operator notes need the lane D store (MBOS_STATE_BACKEND=lane_d)"])
        try:
            with self.engine.begin() as c:
                return self._spine.record_operator_note(c, bundle)
        except sa.exc.DBAPIError as ex:
            msg = str(getattr(ex, "orig", ex)).strip().splitlines()[0]
            raise NoteRefused([f"the store refused the note: {msg}"]) from None

    def held(self) -> list[dict]:
        """HOLD backlog: held requests with their item and the HOLD in force (approval row)."""
        rows = []
        held_sql = ("SELECT doc FROM mbos.v_action_request_documents WHERE doc->>'status' = 'held' ORDER BY doc->>'created_at'"
                    if self.lane == "lane_d" else
                    "SELECT body FROM mbos.action_requests WHERE status = 'held' ORDER BY body->>'created_at'")
        for areq in self._bodies(held_sql):
            last = (self.approvals_for(areq["action_request_id"]) or [None])[-1]
            rows.append({"action_request": areq, "item": self.item(areq["item_id"]),
                         "hold": (last or {}).get("hold") or {}, "held_at": (last or {}).get("decided_at"),
                         "reason": (last or {}).get("reason")})
        return rows

    def outcomes(self, item_id: Optional[str] = None, limit: int = 100) -> list[dict]:
        if self.lane == "lane_d":
            if item_id:
                return self._bodies("SELECT doc FROM mbos.v_outcome_documents WHERE doc->>'item_id' = :i ORDER BY doc->>'observed_at'", i=item_id)
            return self._bodies("SELECT doc FROM mbos.v_outcome_documents ORDER BY doc->>'observed_at' DESC LIMIT :n", n=limit)
        if item_id:
            return self._bodies("SELECT body FROM mbos.outcomes WHERE body->>'item_id' = :i ORDER BY body->>'observed_at'", i=item_id)
        return self._bodies("SELECT body FROM mbos.outcomes ORDER BY body->>'observed_at' DESC LIMIT :n", n=limit)

    def record_outcome(self, item_id: str, kind: str, **kw: Any) -> dict:
        """Second (and last) write path: Michael records what actually happened (feeds LEARN, lane C)."""
        with self.engine.begin() as c:
            return self._spine.record_outcome(c, item_id, kind, recorded_by="michael", channel="web", **kw)  # → mbos.web.outcome

    # ---- the one write path -----------------------------------------------------------------
    def decide(self, areq_id: str, decision: str, payload_hash_seen: str, **kw: Any) -> dict:
        with self.engine.begin() as c:
            out = self._spine.decide(c, areq_id, decision, payload_hash_seen, self.components, channel="web", **kw)
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
