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


class FollowupRefused(Exception):
    """The follow-up was not created. `.reasons` are shown to Michael verbatim."""

    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


class AlreadyRecorded(Exception):
    """F-84: a concurrent submit with the same idempotency key won; the caller reports the winner's receipt."""


class AlreadyClosed(Exception):
    """F-33: the store refused a second closing outcome for an item whose capital already came back."""


class NumbersRefused(Exception):
    """F-22: the store refused a mission or capital change; `reasons` are shown verbatim."""

    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


class ItemNotFound(Exception):
    """Unknown item id. Deliberately NOT a LookupError: a KeyError from the card builder must surface as a failure."""


class SpineBackend:
    def __init__(self, engine: sa.Engine, components: Optional[Components] = None, notify=None, lane: str = "reference"):
        if lane not in ("reference", "lane_d"):
            raise ValueError(f"unknown state backend {lane!r}")
        self.engine = engine
        self.lane = lane
        self.owner_login = None  # F-88: set by make_backend; False = owner-channel writes would run on the worker login
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

    # ---- F-11: follow-up / offer / quote as their OWN step-up ActionRequests (public API A-15) -----------------
    def asked_question_ids(self, item_id: str) -> list[str]:
        """Q&A ids already put to the counterparty in earlier requests on this item (so a follow-up asks new ones)."""
        out: list[str] = []
        for a in self.action_requests_for_item(item_id):
            out += ((a.get("payload") or {}).get("comms") or {}).get("question_ids") or []
        return out

    def propose_followup(self, item_id: str, pa: dict) -> dict:
        """Create the request via `mbos.workflows.propose_followup` (policy path: PDP, proposer_for, step-up) and start its
        approval gate. It only PROPOSES: Michael's YES (with PIN for binding actions) is a separate human decision."""
        if self.lane != "lane_d":
            raise FollowupRefused(["follow-ups need the lane D store (MBOS_STATE_BACKEND=lane_d)"])
        from mbos import workflows

        try:
            return workflows.propose_followup(item_id, pa)
        except self._spine.DecisionRefused as ex:
            raise FollowupRefused([str(ex)]) from None

    # ---- F-22: "My numbers" (mission + capital ledger). Lane D only; HUMAN CHANNEL ONLY (R14) ---------------------
    def my_numbers(self) -> dict:
        """{'mission': current mission doc or None, 'ledger': capital position document or None, 'impaired': bool}. Read-only."""
        if self.lane != "lane_d":
            return {"mission": None, "ledger": None, "available": False}
        with self.engine.connect() as c:
            m = c.execute(sa.text("SELECT doc FROM mbos.v_mission_current")).scalar()
            l = c.execute(sa.text("SELECT mbos.capital_position_document('dry_run')")).scalar()
        return {"mission": m, "ledger": l, "available": True}

    def _owner_write(self, sql: str, params: dict, entered_by: str, basis_text: str) -> str:
        """One transaction: a HUMAN provenance record, then the owner-channel function (which appends the receipt). The database
        refuses any role but the approver; the code path (CSRF + PIN, server-set author) is the only caller (R14)."""
        import json

        from mbos.clock import iso, utcnow

        if self.lane != "lane_d":
            raise NumbersRefused(["My numbers needs the lane D store (MBOS_STATE_BACKEND=lane_d)"])
        prov = {"actor_type": "human", "human_actor": entered_by, "basis": "FACT", "created_at": iso(utcnow()),
                "tool_name": "operator_ui.my_numbers", "tool_version": "F-22",
                "inputs_used": [{"ref": "owner:" + basis_text[:80]}]}
        try:
            with self.engine.begin() as c:
                pid = c.execute(sa.text("SELECT mbos.record_provenance(CAST(:p AS jsonb))"), {"p": json.dumps(prov)}).scalar_one()
                actor = json.dumps({"type": "human", "id": entered_by})
                return c.execute(sa.text(sql), {**params, "a": actor, "p": [pid]}).scalar_one()
        except sa.exc.DBAPIError as ex:
            # F-27: a double-submit loser can fail as a unique violation OR as "no receipt for ..." (the replay appended none). Either
            # way, if the winner's receipt exists under this key the answer is "already recorded", never the raw database text.
            if self._receipt_for(params.get("k")):
                raise AlreadyRecorded() from None
            msg = str(getattr(ex, "orig", ex)).strip().splitlines()[0]
            raise NumbersRefused([f"the store refused it: {msg}"]) from None

    def _receipt_for(self, key):
        """The receipt id recorded under an idempotency key (a fresh connection, so the winner's commit is visible), else None."""
        if not key:
            return None
        with self.engine.connect() as c:
            return c.execute(sa.text("SELECT receipt_id FROM mbos.receipts WHERE idempotency_key = :k"), {"k": key}).scalar()

    def set_mission(self, mission: dict, entered_by: str, key: str) -> str:
        import json

        return self._owner_write(
            "SELECT mbos.set_mission(CAST(:m AS jsonb), CAST(:a AS jsonb), :i, :p, :k)",
            {"m": json.dumps(mission), "i": "Michael set the weekly mission (My numbers)", "k": key}, entered_by, "mission")

    # ---- F-25: Wanted campaigns on the spine (migration 0019). Reads are open; writes are the owner channel only ------
    def campaigns_supported(self) -> bool:
        """True on lane D with migration 0019 (mbos.v_campaigns_current exists); else /wanted keeps its local-file fallback."""
        if self.lane != "lane_d":
            return False
        with self.engine.connect() as c:
            return c.execute(sa.text("SELECT to_regclass('mbos.v_campaigns_current') IS NOT NULL")).scalar_one()

    def campaign_records(self) -> list[dict]:
        """[{'doc', 'history'}] for every campaign: the current revision's body plus one history row per revision (who, when, what)."""
        out: dict[str, dict] = {}
        with self.engine.connect() as c:
            for cid, rev, status, level, body, at, by in c.execute(sa.text(
                    "SELECT campaign_id, revision, status, autonomy_level, body, created_at, created_by "
                    "FROM mbos.campaigns ORDER BY campaign_id, revision")):
                rec = out.setdefault(cid, {"doc": body, "history": []})
                rec["doc"] = body
                rec["history"].append({"at": at.isoformat(), "by": by, "what": f"revision {rev}: {status} ({level})"})
        return list(out.values())

    def set_campaign(self, doc: dict, entered_by: str, intent: str, key: str) -> str:
        import json

        return self._owner_write(
            "SELECT mbos.set_campaign(CAST(:c AS jsonb), CAST(:a AS jsonb), :i, :p, :k)",
            {"c": json.dumps(doc), "i": intent, "k": key}, entered_by, "campaign:" + doc["campaign_id"])

    def cancel_campaign(self, cid: str, entered_by: str, intent: str, key: str) -> str:
        return self._owner_write(
            "SELECT mbos.cancel_campaign(:cid, CAST(:a AS jsonb), :i, :p, :k)",
            {"cid": cid, "i": intent, "k": key}, entered_by, "campaign:" + cid)

    def campaign_receipt(self, key: str):
        """The receipt id recorded under an idempotency key, else None."""
        with self.engine.connect() as c:
            return c.execute(sa.text("SELECT receipt_id FROM mbos.receipts WHERE idempotency_key = :k"), {"k": key}).scalar()

    def capital_move(self, kind: str, amount: str, entered_by: str, key: str) -> str:
        fn = {"fund": "capital_fund", "withdraw": "capital_withdraw"}[kind]
        return self._owner_write(
            f"SELECT mbos.{fn}(CAST(:amt AS numeric), CAST(:a AS jsonb), :i, :p, :k)",
            {"amt": amount, "i": f"Michael {kind} capital {amount} USD (My numbers, dry-run)", "k": key}, entered_by, kind)

    def capital_seen(self, kind: str, key: str):
        """F-72: the receipt id already recorded under this idempotency key, else None (a replay is a no-op)."""
        if self.lane != "lane_d":
            return None
        with self.engine.connect() as c:
            return c.execute(sa.text("SELECT receipt_id FROM mbos.receipts WHERE idempotency_key = :k"), {"k": key}).scalar()

    def capital_recorded(self, receipt_id: str):
        """F-72: the ledger entry's own amount for a receipt (what was really recorded), or None."""
        with self.engine.connect() as c:
            return c.execute(sa.text("SELECT amount FROM mbos.capital_ledger WHERE source_receipt_id = :r"), {"r": receipt_id}).scalar()

    def record_attestation(self, item_id: str, evidence_key: str, note: str, entered_by: str) -> dict:
        """F-90: Michael's confirmation of a requested evidence key (D-29 `mbos.record_attestation`: owner channel, human actor,
        receipted). HUMAN CHANNEL ONLY (R14): the single UI caller is `App.add_attestation` (CSRF + PIN, server-set author)."""
        if self.lane != "lane_d":
            raise NumbersRefused(["confirming evidence needs the lane D store (MBOS_STATE_BACKEND=lane_d)"])
        try:
            with self.engine.begin() as c:
                return self._spine.record_attestation(c, item_id, evidence_key, note, entered_by)
        except sa.exc.DBAPIError as ex:
            msg = str(getattr(ex, "orig", ex)).strip().splitlines()[0]
            raise NumbersRefused([f"the store refused it: {msg}"]) from None

    def record_human_inputs(self, item_id: str, inputs: list, note: str, entered_by: str) -> list:
        """F-32: Michael's typed inputs (A-43 `spine_d.record_human_input` over D-30: owner channel, human actor, receipted), all in one
        transaction. HUMAN CHANNEL ONLY (R14): the callers are `App.set_quote` / `App.set_scope` (CSRF + PIN, server-set author)."""
        if self.lane != "lane_d":
            raise NumbersRefused(["saving this needs the lane D store (MBOS_STATE_BACKEND=lane_d)"])
        try:
            with self.engine.begin() as c:
                return [self._spine.record_human_input(c, item_id, kind, key, value, note, entered_by) for kind, key, value in inputs]
        except (sa.exc.DBAPIError, ValueError) as ex:
            msg = str(getattr(ex, "orig", ex)).strip().splitlines()[0]
            raise NumbersRefused([f"the store refused it: {msg}"]) from None

    # ---- F-33: "I bought it" (D-31 `mbos.record_acquisition`) and the capital an item holds. HUMAN CHANNEL ONLY (R14) ------
    def capital_for(self, item_id: str) -> dict:
        """{'deployed': $ recorded as bought, 'closed': bool, 'net': realized net or None} from the capital ledger (read-only)."""
        if self.lane != "lane_d":
            return {"deployed": 0.0, "closed": False, "net": None}
        with self.engine.connect() as c:
            rows = c.execute(sa.text("SELECT kind, amount, net FROM mbos.capital_ledger WHERE item_id = :i AND mode = 'dry_run'"), {"i": item_id}).all()
        close = next((r for r in rows if r[0] == "close"), None)
        return {"deployed": float(sum(r[1] for r in rows if r[0] == "deploy")), "closed": close is not None,
                "net": None if close is None else float(close[2])}

    def open_acquisitions(self) -> list[dict]:
        """Items with capital deployed and not yet closed (a flip in flight): [{'item_id','title','amount'}]. Read-only."""
        if self.lane != "lane_d":
            return []
        with self.engine.connect() as c:
            rows = c.execute(sa.text(
                "SELECT l.item_id, sum(l.amount) FROM mbos.capital_ledger l WHERE l.kind = 'deploy' AND l.mode = 'dry_run' AND NOT EXISTS "
                "(SELECT 1 FROM mbos.capital_ledger x WHERE x.kind = 'close' AND x.item_id = l.item_id AND x.mode = 'dry_run') "
                "GROUP BY l.item_id ORDER BY min(l.seq)")).all()
        out = []
        for iid, amt in rows:
            it = self.item(iid) or {}
            out.append({"item_id": iid, "title": ((it.get("normalized") or {}).get("title")) or iid, "amount": float(amt)})
        return out

    def record_acquisition(self, item_id: str, amount: Any, note: str, entered_by: str, idem: str) -> str:
        """Michael bought it off-system: D-31 `mbos.record_acquisition` (owner channel, human actor, dry-run BUDGET_COMMITTED -> capital
        deploy; refused above available or when unfunded). No 01 wrapper exists yet, so this mirrors `spine_d.record_human_input`
        (human provenance first). HUMAN CHANNEL ONLY (R14): the single caller is `App.record_bought` (CSRF + PIN, server-set author)."""
        import json

        from mbos.clock import iso, utcnow

        if self.lane != "lane_d":
            raise NumbersRefused(["recording a purchase needs the lane D store (MBOS_STATE_BACKEND=lane_d)"])
        prov = {"actor_type": "human", "human_actor": entered_by, "basis": "FACT", "created_at": iso(utcnow()),
                "tool_name": "operator_ui.bought_it", "tool_version": "F-33", "inputs_used": [{"ref": item_id}]}
        try:
            with self.engine.begin() as c:
                pid = c.execute(sa.text("SELECT mbos.record_provenance(CAST(:d AS jsonb))"), {"d": json.dumps(prov)}).scalar_one()
                return c.execute(sa.text("SELECT mbos.record_acquisition(:i, CAST(:n AS numeric), :t, CAST(:a AS jsonb), ARRAY[CAST(:p AS text)], :k)"),
                                 {"i": item_id, "n": str(amount), "t": note, "a": json.dumps({"type": "human", "id": entered_by}),
                                  "p": pid, "k": idem}).scalar_one()
        except sa.exc.DBAPIError as ex:
            msg = str(getattr(ex, "orig", ex)).strip().splitlines()[0]
            raise NumbersRefused([f"the store refused it: {msg}"]) from None

    # ---- F-14: Michael's own model knowledge (operator notes). Lane D only; HUMAN CHANNEL ONLY (R14) -----------
    def operator_notes(self, include_retracted: bool = False) -> list[dict]:
        """Current head of every note chain, from lane D's folded document (read-only SQL function)."""
        if self.lane != "lane_d":
            return []
        with self.engine.connect() as c:
            if include_retracted:
                return c.execute(sa.text("SELECT mbos.operator_notes_document(true)")).scalar_one()["notes"]
            return self._spine.operator_notes_document(c)["notes"]

    def retract_operator_note(self, note_id: str, entered_by: str, entered_at: str, reason: str) -> str:
        """Retract the head of a note chain (a new row; history is never edited). HUMAN CHANNEL ONLY (R14): the single
        UI caller is `App.retract_note` (CSRF + PIN, server-set author). Database refusals come back as NoteRefused."""
        if self.lane != "lane_d":
            raise NoteRefused(["operator notes need the lane D store (MBOS_STATE_BACKEND=lane_d)"])
        try:
            with self.engine.begin() as c:
                return self._spine.retract_operator_note(c, note_id, entered_by, entered_at, reason)
        except sa.exc.DBAPIError as ex:
            msg = str(getattr(ex, "orig", ex)).strip().splitlines()[0]
            raise NoteRefused([f"the store refused the retraction: {msg}"]) from None

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
        try:
            with self.engine.begin() as c:
                return self._spine.record_outcome(c, item_id, kind, recorded_by="michael", channel="web", **kw)  # → mbos.web.outcome
        except sa.exc.DBAPIError as ex:
            msg = str(getattr(ex, "orig", ex)).strip().splitlines()[0]
            if "already closed" in msg:  # F-115 / D-31: a closing outcome already returned this item's capital
                raise AlreadyClosed(f"This item is already closed: its capital was returned when the first closing outcome was recorded, "
                                    f"so a second '{kind}' is refused and nothing moved. ({msg})") from None
            raise

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
