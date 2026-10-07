"""Thin Python facade over the mbos.* SQL write API.

The atomicity lives in SQL (each mbos.* function writes state + receipt, and the receipt trigger writes the
outbox row), so this facade never needs its own transaction logic. Callers compose several calls into one
transaction with ``with store.transaction():`` — or call the same SQL functions from a DBOS
``@DBOS.transaction`` / SQLAlchemy session; the guarantees are identical.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class Actor:
    type: str  # agent | human | system | external
    id: str

    def as_json(self) -> Jsonb:
        return Jsonb({"type": self.type, "id": self.id})


@dataclass(frozen=True)
class ChainStatus:
    ok: bool
    receipts_checked: int
    first_bad_seq: int | None
    reason: str | None


class StateStore:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    @contextmanager
    def transaction(self) -> Iterator[None]:
        with self.conn.transaction():
            yield

    def _one(self, sql: str, params: Sequence[Any]) -> Any:
        return self.conn.execute(sql, params).fetchone()[0]

    # -- provenance / receipts ------------------------------------------------
    def record_provenance(self, **fields: Any) -> str:
        return self._one("SELECT mbos.record_provenance(%s)", (Jsonb(fields),))

    def append_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT mbos.receipt_document(r) FROM mbos.append_receipt(%s) r", (Jsonb(receipt),)
        ).fetchone()
        return row[0]

    # -- items ----------------------------------------------------------------
    def create_item(self, doc: dict, actor: Actor, intent: str, provenance_ids: list[str], idempotency_key: str) -> str:
        return self._one(
            "SELECT mbos.create_item(%s, %s, %s, %s, %s)",
            (Jsonb(doc), actor.as_json(), intent, provenance_ids, idempotency_key),
        )

    def transition_item(self, item_id: str, to_state: str, actor: Actor, intent: str, provenance_ids: list[str],
                        idempotency_key: str, expected_version: int | None = None,
                        extra: dict | None = None) -> str:
        return self._one(
            "SELECT mbos.transition_item(%s, %s, %s, %s, %s, %s, %s, %s)",
            (item_id, to_state, actor.as_json(), intent, provenance_ids, idempotency_key, expected_version,
             Jsonb(extra or {})),
        )

    def update_item_doc(self, item_id: str, patch: dict, receipt_type: str, actor: Actor, intent: str,
                        provenance_ids: list[str], idempotency_key: str, expected_version: int | None = None,
                        extra: dict | None = None) -> str:
        return self._one(
            "SELECT mbos.update_item_doc(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (item_id, Jsonb(patch), receipt_type, actor.as_json(), intent, provenance_ids, idempotency_key,
             expected_version, Jsonb(extra or {})),
        )

    def item_document(self, item_id: str) -> dict:
        return self._one("SELECT doc FROM mbos.v_item_documents WHERE item_id = %s", (item_id,))

    # -- action requests / approvals -------------------------------------------
    def propose_action(self, areq: dict, actor: Actor, intent: str, idempotency_key: str) -> str:
        return self._one(
            "SELECT mbos.propose_action(%s, %s, %s, %s)", (Jsonb(areq), actor.as_json(), intent, idempotency_key)
        )

    def set_action_status(self, areq_id: str, to_status: str, receipt_type: str, actor: Actor, intent: str,
                          provenance_ids: list[str], idempotency_key: str, extra: dict | None = None,
                          tier: int | None = None) -> str:
        return self._one(
            "SELECT mbos.set_action_status(%s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (areq_id, to_status, receipt_type, actor.as_json(), intent, provenance_ids, idempotency_key,
             Jsonb(extra or {}), tier),
        )

    def record_approval(self, approval: dict, actor: Actor, intent: str, idempotency_key: str,
                        extra_provenance_ids: list[str] | None = None) -> str:
        return self._one(
            "SELECT mbos.record_approval(%s, %s, %s, %s, %s)",
            (Jsonb(approval), actor.as_json(), intent, idempotency_key, extra_provenance_ids or []),
        )

    # -- outcomes / lessons / policy / budget ------------------------------------
    def record_outcome(self, outcome: dict, actor: Actor, intent: str, idempotency_key: str) -> str:
        return self._one("SELECT mbos.record_outcome(%s, %s, %s, %s)",
                         (Jsonb(outcome), actor.as_json(), intent, idempotency_key))

    def record_lesson(self, lesson: dict, actor: Actor, intent: str, idempotency_key: str) -> str:
        return self._one("SELECT mbos.record_lesson(%s, %s, %s, %s)",
                         (Jsonb(lesson), actor.as_json(), intent, idempotency_key))

    def publish_policy(self, policy: dict, actor: Actor, intent: str, idempotency_key: str) -> str:
        return self._one("SELECT mbos.publish_policy(%s, %s, %s, %s)",
                         (Jsonb(policy), actor.as_json(), intent, idempotency_key))

    def budget_reserve(self, areq_id: str, amount: float, currency: str, cap: float | None, actor: Actor,
                       intent: str, provenance_ids: list[str], idempotency_key: str) -> str:
        return self._one("SELECT mbos.budget_reserve(%s, %s, %s, %s, %s, %s, %s, %s)",
                         (areq_id, amount, currency, cap, actor.as_json(), intent, provenance_ids, idempotency_key))

    def budget_settle(self, reservation_id: str, kind: str, amount: float | None, actor: Actor, intent: str,
                      provenance_ids: list[str], idempotency_key: str) -> str:
        return self._one("SELECT mbos.budget_settle(%s, %s, %s, %s, %s, %s, %s)",
                         (reservation_id, kind, amount, actor.as_json(), intent, provenance_ids, idempotency_key))

    # -- operator notes (D-17) -------------------------------------------------
    def record_operator_note(self, bundle: dict) -> str:
        """bundle = mbos_economics.new_manual_note(...) output {"note", "provenance"}. Human channel (approver) only."""
        return self._one("SELECT mbos.record_operator_note(%s)", (Jsonb(bundle),))

    def retract_operator_note(self, note_id: str, entered_by: str, entered_at: str, reason: str) -> str:
        return self._one("SELECT mbos.retract_operator_note(%s, %s, %s::timestamptz, %s)",
                         (note_id, entered_by, entered_at, reason))

    def operator_notes_document(self, include_retracted: bool = True) -> dict:
        """The flat {"notes_format": 1, "notes": [...]} document that valueadd.load_manual_notes reads."""
        return self._one("SELECT mbos.operator_notes_document(%s)", (include_retracted,))

    # -- chain ----------------------------------------------------------------
    def verify_chain(self, from_seq: int = 1, anchor: dict | None = None) -> ChainStatus:
        row = self.conn.execute(
            "SELECT ok, receipts_checked, first_bad_seq, reason FROM mbos.verify_chain(%s, %s, %s)",
            (from_seq, (anchor or {}).get("seq"), (anchor or {}).get("row_hash")),
        ).fetchone()
        return ChainStatus(*row)

    def chain_head(self) -> dict | None:
        row = self.conn.execute("SELECT seq, receipt_id, row_hash, ts FROM mbos.chain_head()").fetchone()
        if row is None:
            return None
        return {"seq": row[0], "receipt_id": row[1], "row_hash": row[2], "ts": row[3].isoformat()}
