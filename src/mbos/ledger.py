"""The receipt/provenance ledger and the same-transaction state-change primitive.

Core law: no action without a receipt; no receipt without provenance.

Every function takes the caller's open `sa.Connection` and never commits. The caller's
transaction (a DBOS datasource transaction inside workflows, `engine.begin()` elsewhere)
makes the state change, its receipt and its outbox row commit together or not at all (A1).
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

import sqlalchemy as sa

from mbos import __version__
from mbos.clock import now_iso, receipt_ts
from mbos.contracts import schemas
from mbos.contracts.models import Receipt
from mbos.ids import new_id
from mbos.state_machine import check_item_transition

SYSTEM_ACTOR = {"type": "system", "id": "mbos-spine"}
_PLACEHOLDER_HASH = "sha256:" + "0" * 64


def _j(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), default=str)


# ---------------------------------------------------------------- provenance
def record_provenance(conn: sa.Connection, **fields: Any) -> str:
    """Insert a Provenance v1 record and return its id. Validated against the frozen contract."""
    doc = {"provenance_id": new_id("prov"), "created_at": now_iso(), **{k: v for k, v in fields.items() if v is not None}}
    schemas.validate("provenance", doc)
    conn.execute(sa.text("INSERT INTO mbos.provenance (body) VALUES (CAST(:b AS jsonb))"), {"b": _j(doc)})
    return doc["provenance_id"]


def tool_provenance(conn: sa.Connection, tool_name: str, *, basis: str = "FACT", inputs: Iterable[str] = (),
                    config_version: Optional[str] = None, agent_name: str = "agent-01-spine",
                    derived_from: Optional[list[str]] = None) -> str:
    """Provenance for a deterministic computation by spine code (contract anyOf branch: tool + version)."""
    return record_provenance(
        conn, actor_type="system", agent_name=agent_name, basis=basis, tool_name=tool_name,
        tool_version=__version__, config_version=config_version,
        inputs_used=[{"ref": r} for r in inputs] or None, derived_from=derived_from or None,
    )


# ---------------------------------------------------------------- receipts
def _next_key(conn: sa.Connection, subject: str, rtype: str) -> str:
    n = conn.execute(
        sa.text("SELECT count(*) FROM mbos.receipts WHERE idempotency_key LIKE :p"),
        {"p": f"{subject}:{rtype}:%"},
    ).scalar_one()
    return f"{subject}:{rtype}:{n + 1}"


def append_receipt(conn: sa.Connection, *, type: str, intent: str, provenance_ids: list[str],
                   actor: Optional[dict] = None, idempotency_key: Optional[str] = None, **fields: Any) -> dict:
    """Append one Receipt v1 event. Returns the stored receipt (with seq / prev_hash / row_hash).

    The draft is validated against the frozen schema BEFORE insert (chain fields stubbed), and the
    DB trigger then enforces provenance existence, the hash chain and the MVP dry-run constraint.
    """
    if not provenance_ids:
        raise ValueError("no receipt without provenance: provenance_ids is empty")
    subject = fields.get("action_request_id") or fields.get("item_id") or fields.get("entity_id") or "system"
    body = {
        "receipt_id": new_id("rcpt"),
        "ts": receipt_ts(),
        "schema_version": "1.0.0",
        "type": type,
        "actor": actor or SYSTEM_ACTOR,
        "intent": intent,
        "provenance_ids": list(dict.fromkeys(provenance_ids)),
        "idempotency_key": idempotency_key or _next_key(conn, subject, type),
        **{k: v for k, v in fields.items() if v is not None},
    }
    schemas.validate("receipt", {**body, "seq": 1, "prev_hash": None, "row_hash": _PLACEHOLDER_HASH})
    row = conn.execute(
        sa.text("INSERT INTO mbos.receipts (seq, body, row_hash) VALUES (0, CAST(:b AS jsonb), '') "
                "RETURNING seq, prev_hash, row_hash"),
        {"b": _j(body)},
    ).one()
    return {**body, "seq": row.seq, "prev_hash": row.prev_hash, "row_hash": row.row_hash}


def load_receipts(conn: sa.Connection, where: str = "true", params: Optional[dict] = None) -> list[dict]:
    rows = conn.execute(sa.text(f"SELECT seq, body, prev_hash, row_hash FROM mbos.receipts WHERE {where} ORDER BY seq"),
                        params or {}).all()
    return [{**r.body, "seq": r.seq, "prev_hash": r.prev_hash, "row_hash": r.row_hash} for r in rows]


def verify_exported_chain(receipts: list[dict]) -> tuple[bool, str]:
    """Verify receipts (full Receipt v1 documents, seq order) with ONLY the ADR-0010 reference code —
    the check any lane, or an auditor, can run on an export without trusting this database."""
    from mbos.hashing import reference

    return reference().verify_chain(receipts)


def verify_chain(conn: sa.Connection) -> dict:
    r = conn.execute(sa.text("SELECT * FROM mbos.verify_chain()")).one()
    return {"ok": r.ok, "checked": r.checked, "first_bad_seq": r.first_bad_seq, "reason": r.reason}


def outbox(conn: sa.Connection, topic: str, entity_id: str, payload: dict) -> None:
    conn.execute(sa.text("INSERT INTO mbos.outbox (topic, entity_id, payload) VALUES (:t, :e, CAST(:p AS jsonb))"),
                 {"t": topic, "e": entity_id, "p": _j(payload)})


# ---------------------------------------------------------------- items
def load_item(conn: sa.Connection, item_id: str, *, for_update: bool = False) -> dict:
    q = "SELECT body FROM mbos.items WHERE item_id = :i" + (" FOR UPDATE" if for_update else "")
    row = conn.execute(sa.text(q), {"i": item_id}).one_or_none()
    if row is None:
        raise KeyError(item_id)
    return row.body


def create_item(conn: sa.Connection, item: dict, *, intent: str, provenance_ids: list[str],
                actor: Optional[dict] = None) -> dict:
    """Insert a new Item in DISCOVERED with its ITEM_STATE_CHANGED (create) receipt."""
    item = {**item, "state": "DISCOVERED", "updated_at": item.get("created_at")}
    schemas.validate("item", item)
    conn.execute(sa.text("INSERT INTO mbos.items (body) VALUES (CAST(:b AS jsonb))"), {"b": _j(item)})
    append_receipt(
        conn, type="ITEM_STATE_CHANGED", intent=intent, provenance_ids=provenance_ids, actor=actor,
        item_id=item["item_id"], entity_type="item", entity_id=item["item_id"], effect="create",
        idempotency_key=f"{item['item_id']}:state:1", before_state=None, after_state={"state": "DISCOVERED"},
    )
    outbox(conn, "item.state", item["item_id"], {"from": None, "to": "DISCOVERED"})
    return item


def update_item(conn: sa.Connection, item_id: str, *, to_state: Optional[str] = None, patch: Optional[dict] = None,
                intent: str, provenance_ids: list[str], actor: Optional[dict] = None,
                receipt_fields: Optional[dict] = None) -> dict:
    """Change an Item (state and/or body) and append its ITEM_STATE_CHANGED receipt in the SAME transaction.

    `patch` is a shallow merge of top-level Item fields. The resulting Item is validated against
    the frozen contract before it is written.
    """
    row = conn.execute(sa.text("SELECT body, version FROM mbos.items WHERE item_id = :i FOR UPDATE"),
                       {"i": item_id}).one()
    before = row.body
    from_state = before["state"]
    target = to_state or from_state
    if to_state is not None and to_state != from_state:
        check_item_transition(from_state, to_state)
    after = {**before, **(patch or {}), "state": target, "updated_at": now_iso()}
    after["provenance_ids"] = list(dict.fromkeys((before.get("provenance_ids") or []) + provenance_ids))
    schemas.validate("item", after)
    conn.execute(sa.text("UPDATE mbos.items SET body = CAST(:b AS jsonb) WHERE item_id = :i"),
                 {"b": _j(after), "i": item_id})
    before_state = {"state": from_state}
    after_state = {"state": target}
    if patch:
        after_state["changed"] = sorted(patch)
    append_receipt(
        conn, type="ITEM_STATE_CHANGED", intent=intent, provenance_ids=provenance_ids, actor=actor,
        item_id=item_id, entity_type="item", entity_id=item_id,
        effect="update", idempotency_key=f"{item_id}:state:{row.version + 1}",
        before_state=before_state, after_state=after_state, **(receipt_fields or {}),
    )
    if target != from_state:
        outbox(conn, "item.state", item_id, {"from": from_state, "to": target})
    return after


def transition_item(conn: sa.Connection, item_id: str, to_state: str, *, intent: str, provenance_ids: list[str],
                    actor: Optional[dict] = None, patch: Optional[dict] = None) -> dict:
    return update_item(conn, item_id, to_state=to_state, patch=patch, intent=intent,
                       provenance_ids=provenance_ids, actor=actor)


def stored_receipt_model(doc: dict) -> Receipt:
    return Receipt.from_doc(doc)
