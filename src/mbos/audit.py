"""Audit queries behind A3/A4/A7/A10 and `mbos audit`. Read-only."""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa

from mbos.contracts import schemas
from mbos.ledger import load_receipts, verify_chain

_TABLES = {
    "item": ("mbos.items", "item_id"),
    "action-request": ("mbos.action_requests", "action_request_id"),
    "approval": ("mbos.approvals", "approval_id"),
    "provenance": ("mbos.provenance", "provenance_id"),
    "outcome": ("mbos.outcomes", "outcome_id"),
}


_LANE_D_VIEWS = {  # kind -> (view, key column); lane D stores columns, the contract documents come from its views
    "item": ("mbos.v_item_documents", "item_id"),
    "action-request": ("mbos.v_action_request_documents", "action_request_id"),
    "approval": ("mbos.v_approval_documents", "approval_id"),
    "provenance": ("mbos.v_provenance_documents", "provenance_id"),
    "outcome": ("mbos.v_outcome_documents", "outcome_id"),
}


def is_lane_d(conn: sa.Connection) -> bool:
    return bool(conn.execute(sa.text("SELECT to_regclass('mbos.v_item_documents') IS NOT NULL")).scalar_one())


def _lane_d_audit(conn: sa.Connection) -> dict[str, Any]:
    """The same four checks over lane D's schema (04's verify_chain, v_*_documents, v_a7_live_effects)."""
    from mbos.adapters.state04 import Pg04Ledger

    counts: dict[str, int] = {}
    failures: list[str] = []
    for kind, (view, key) in _LANE_D_VIEWS.items():
        rows = conn.execute(sa.text(f"SELECT {key} AS id, doc FROM {view}")).all()
        counts[kind] = len(rows)
        for r in rows:
            failures += [f"{kind} {r.id}: {e}" for e in schemas.errors(kind, r.doc)]
    receipts = [r[0] for r in conn.execute(sa.text("SELECT doc FROM mbos.v_receipt_documents ORDER BY seq"))]
    counts["receipt"] = len(receipts)
    for r in receipts:
        failures += [f"receipt {r['receipt_id']}: {e}" for e in schemas.errors("receipt", r)]
    unresolved = conn.execute(sa.text(
        "SELECT r.receipt_id, p.id FROM mbos.receipts r, unnest(r.provenance_ids) AS p(id) "
        "WHERE NOT EXISTS (SELECT 1 FROM mbos.provenance v WHERE v.provenance_id = p.id)")).all()
    empty = conn.execute(sa.text("SELECT receipt_id FROM mbos.receipts WHERE coalesce(cardinality(provenance_ids), 0) = 0")).scalars().all()
    bad = [pid for pid, doc in conn.execute(sa.text("SELECT provenance_id, doc FROM mbos.v_provenance_documents")).all()
           if schemas.errors("provenance", doc)]
    live = conn.execute(sa.text("SELECT receipt_id FROM mbos.v_a7_live_effects")).scalars().all()
    n = conn.execute(sa.text("SELECT count(*) FROM mbos.receipts WHERE type IN ('ACTION_EXECUTED', 'ACTION_FAILED')")).scalar_one()
    return {"chain": Pg04Ledger().verify_chain(conn),
            "provenance": {"ok": not (unresolved or empty or bad), "receipts": len(receipts), "unresolved": [tuple(u) for u in unresolved],
                           "empty": list(empty), "invalid_provenance": bad},
            "dry_run": {"ok": not live, "effector_receipts": n, "receipt_exceptions": list(live), "call_exceptions": []},
            "conformance": {"ok": not failures, "counts": counts, "failures": failures}}


def conformance(conn: sa.Connection) -> dict[str, Any]:
    """A10: every stored record validates against the frozen contracts."""
    counts: dict[str, int] = {}
    failures: list[str] = []
    for kind, (table, key) in _TABLES.items():
        rows = conn.execute(sa.text(f"SELECT {key} AS id, body FROM {table}")).all()
        counts[kind] = len(rows)
        for r in rows:
            failures += [f"{kind} {r.id}: {e}" for e in schemas.errors(kind, r.body)]
    receipts = load_receipts(conn)
    counts["receipt"] = len(receipts)
    for r in receipts:
        failures += [f"receipt {r['receipt_id']}: {e}" for e in schemas.errors("receipt", r)]
    return {"ok": not failures, "counts": counts, "failures": failures}


def provenance_resolution(conn: sa.Connection) -> dict[str, Any]:
    """A4: every receipt's provenance_ids exist and satisfy provenance.schema.json's anyOf rule."""
    unresolved = conn.execute(sa.text(
        "SELECT r.receipt_id, p.id FROM mbos.receipts r, jsonb_array_elements_text(r.body->'provenance_ids') AS p(id) "
        "WHERE NOT EXISTS (SELECT 1 FROM mbos.provenance v WHERE v.provenance_id = p.id)")).all()
    empty = conn.execute(sa.text(
        "SELECT receipt_id FROM mbos.receipts WHERE jsonb_array_length(coalesce(body->'provenance_ids', '[]')) = 0")).all()
    bad = []
    for r in conn.execute(sa.text(
            "SELECT DISTINCT v.provenance_id, v.body FROM mbos.receipts r, "
            "jsonb_array_elements_text(r.body->'provenance_ids') AS p(id) JOIN mbos.provenance v ON v.provenance_id = p.id")).all():
        if schemas.errors("provenance", r.body):
            bad.append(r.provenance_id)
    total = conn.execute(sa.text("SELECT count(*) FROM mbos.receipts")).scalar_one()
    return {"ok": not (unresolved or empty or bad), "receipts": total, "unresolved": [tuple(u) for u in unresolved],
            "empty": [e[0] for e in empty], "invalid_provenance": bad}


def dry_run_exceptions(conn: sa.Connection) -> dict[str, Any]:
    """A7: effector receipts and effector calls that are not dry_run=true. Must be zero."""
    receipts = conn.execute(sa.text(
        "SELECT receipt_id FROM mbos.receipts WHERE type IN ('ACTION_EXECUTED', 'ACTION_FAILED') "
        "AND (body->'effector_response'->>'dry_run') IS DISTINCT FROM 'true'")).scalars().all()
    calls = conn.execute(sa.text("SELECT idempotency_key FROM mbos.effector_calls WHERE dry_run IS NOT TRUE")).scalars().all()
    n = conn.execute(sa.text(
        "SELECT count(*) FROM mbos.receipts WHERE type IN ('ACTION_EXECUTED', 'ACTION_FAILED')")).scalar_one()
    return {"ok": not receipts and not calls, "effector_receipts": n, "receipt_exceptions": list(receipts),
            "call_exceptions": list(calls)}


def full_audit(conn: sa.Connection) -> dict[str, Any]:
    if is_lane_d(conn):
        return _lane_d_audit(conn)
    return {"chain": verify_chain(conn), "provenance": provenance_resolution(conn),
            "dry_run": dry_run_exceptions(conn), "conformance": conformance(conn)}
