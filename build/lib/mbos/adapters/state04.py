"""Lane D (Agent 04) canonical state store behind the spine (integration ruling R1). Task A-01, phase 1.

Calls 04's SQL write API (`state/migrations/0003_api.sql`) directly through the spine's SQLAlchemy
connection, so DBOS datasource transactions keep exactly-once semantics and 04's functions keep
"state + receipt (+ outbox by trigger) in one transaction". No dependency on 04's Python package.

Phase 1 (this file): ledger primitives the spine needs, exercised end to end by
`tests/integration/test_state04_adapter.py` against 04's migrations at its pushed head.
Phase 2 (after D-01 migration 0005 + D-02 ADR-0010): `mbos.spine` switches its primitives to this class,
and effector_calls / PANIC / llm_spend / artifacts move to 04's 0005 tables.

Idempotency keys are REQUIRED by 04's API (it returns the original result on a repeat key), so every
call takes one; the spine derives them deterministically (e.g. f"{item_id}:state:{n}", f"act:{areq_id}").
"""

from __future__ import annotations

import json
from typing import Any, Optional

import sqlalchemy as sa


def _j(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)


class Pg04Ledger:
    """Thin, typed mapping of 04's mbos.* functions. Every method runs in the caller's transaction."""

    # -- provenance / receipts -----------------------------------------------------------------------
    def record_provenance(self, conn: sa.Connection, **fields: Any) -> str:
        return conn.execute(sa.text("SELECT mbos.record_provenance(CAST(:p AS jsonb))"),
                            {"p": _j({k: v for k, v in fields.items() if v is not None})}).scalar_one()

    def append_receipt(self, conn: sa.Connection, receipt: dict[str, Any]) -> dict[str, Any]:
        return conn.execute(sa.text("SELECT mbos.receipt_document(r) FROM mbos.append_receipt(CAST(:r AS jsonb)) r"),
                            {"r": _j(receipt)}).scalar_one()

    # -- items -----------------------------------------------------------------------------------------
    def create_item(self, conn: sa.Connection, doc: dict, actor: dict, intent: str, provenance_ids: list[str],
                    idempotency_key: str) -> str:
        return conn.execute(sa.text("SELECT mbos.create_item(CAST(:d AS jsonb), CAST(:a AS jsonb), :i, :p, :k)"),
                            {"d": _j(doc), "a": _j(actor), "i": intent, "p": provenance_ids,
                             "k": idempotency_key}).scalar_one()

    def transition_item(self, conn: sa.Connection, item_id: str, to_state: str, actor: dict, intent: str,
                        provenance_ids: list[str], idempotency_key: str, extra: Optional[dict] = None) -> str:
        return conn.execute(sa.text("SELECT mbos.transition_item(:id, :to, CAST(:a AS jsonb), :i, :p, :k, NULL, "
                                    "CAST(:x AS jsonb))"),
                            {"id": item_id, "to": to_state, "a": _j(actor), "i": intent, "p": provenance_ids,
                             "k": idempotency_key, "x": _j(extra or {})}).scalar_one()

    def patch_item(self, conn: sa.Connection, item_id: str, patch: dict, receipt_type: str, actor: dict, intent: str,
                   provenance_ids: list[str], idempotency_key: str, extra: Optional[dict] = None) -> str:
        """Non-state document change (scores, recommendation, economics, merged sources)."""
        return conn.execute(sa.text("SELECT mbos.update_item_doc(:id, CAST(:d AS jsonb), :t, CAST(:a AS jsonb), :i, "
                                    ":p, :k, NULL, CAST(:x AS jsonb))"),
                            {"id": item_id, "d": _j(patch), "t": receipt_type, "a": _j(actor), "i": intent,
                             "p": provenance_ids, "k": idempotency_key, "x": _j(extra or {})}).scalar_one()

    def load_item(self, conn: sa.Connection, item_id: str) -> dict:
        return conn.execute(sa.text("SELECT doc FROM mbos.v_item_documents WHERE item_id = :i"), {"i": item_id}).scalar_one()

    # -- action requests / approvals ---------------------------------------------------------------------
    def propose_action(self, conn: sa.Connection, areq: dict, actor: dict, intent: str, idempotency_key: str) -> str:
        return conn.execute(sa.text("SELECT mbos.propose_action(CAST(:r AS jsonb), CAST(:a AS jsonb), :i, :k)"),
                            {"r": _j(areq), "a": _j(actor), "i": intent, "k": idempotency_key}).scalar_one()

    def set_action_status(self, conn: sa.Connection, areq_id: str, to_status: str, receipt_type: str, actor: dict,
                          intent: str, provenance_ids: list[str], idempotency_key: str,
                          extra: Optional[dict] = None, tier: Optional[int] = None) -> str:
        return conn.execute(sa.text("SELECT mbos.set_action_status(:id, :to, :t, CAST(:a AS jsonb), :i, :p, :k, "
                                    "CAST(:x AS jsonb), :tier)"),
                            {"id": areq_id, "to": to_status, "t": receipt_type, "a": _j(actor), "i": intent,
                             "p": provenance_ids, "k": idempotency_key, "x": _j(extra or {}), "tier": tier}).scalar_one()

    def load_action_request(self, conn: sa.Connection, areq_id: str) -> dict:
        return conn.execute(sa.text("SELECT doc FROM mbos.v_action_request_documents WHERE action_request_id = :a"),
                            {"a": areq_id}).scalar_one()

    def record_approval(self, conn: sa.Connection, approval: dict, actor: dict, intent: str,
                        idempotency_key: str) -> str:
        return conn.execute(sa.text("SELECT mbos.record_approval(CAST(:ap AS jsonb), CAST(:a AS jsonb), :i, :k)"),
                            {"ap": _j(approval), "a": _j(actor), "i": intent, "k": idempotency_key}).scalar_one()

    def record_outcome(self, conn: sa.Connection, outcome: dict, actor: dict, intent: str, idempotency_key: str) -> str:
        return conn.execute(sa.text("SELECT mbos.record_outcome(CAST(:o AS jsonb), CAST(:a AS jsonb), :i, :k)"),
                            {"o": _j(outcome), "a": _j(actor), "i": intent, "k": idempotency_key}).scalar_one()

    # -- chain -----------------------------------------------------------------------------------------
    def verify_chain(self, conn: sa.Connection) -> dict:
        r = conn.execute(sa.text("SELECT ok, receipts_checked, first_bad_seq, reason FROM mbos.verify_chain()")).one()
        return {"ok": r.ok, "checked": r.receipts_checked, "first_bad_seq": r.first_bad_seq, "reason": r.reason}

    def export_receipts(self, conn: sa.Connection) -> list[dict]:
        """Full Receipt v1 documents in seq order — the input to any lane's ADR-0010 chain verification."""
        return [r[0] for r in conn.execute(sa.text("SELECT mbos.receipt_document(r) FROM mbos.receipts r ORDER BY r.seq"))]
