"""Governance store on Agent 04's canonical Postgres schema (E-02; rulings R1/R2/R4/R5, ADR-0010).

Production path. There is no SQLite here: every write goes through lane D's `mbos.*` API, so lane D owns
the ledger. That gives:
  * insert-only tables, hash-chained receipts (MBOS-RH-1), and the same-transaction "no state change
    without a receipt" constraint triggers;
  * the action-request status edges with a role allow-list per edge;
  * PANIC (panic_set / panic_read), execution claims (effector_claim / effector_finish), and multi-cap
    budget reservations (budget_reserve_caps).

Connections are per ROLE and per thread. Each role maps to a login that is a member of that group role,
so the database checks privileges for real:
  agent_write  -> proposals (agents)            approver     -> Michael's decisions, PANIC release
  gateway      -> classify / execute / budget   policy_admin -> (reserved)
A single DSN may be given for every role (e.g. the DBOS app login `mbos_dbos`, a member of
agent_write+approver+gateway); then the separation is by code path only.
"""
from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .panic import FROZEN, PanicState

ROLES = ("agent_write", "gateway", "approver", "policy_admin")


def J(v: Any) -> Jsonb:
    return Jsonb(v)


class PgGovernanceStore:
    def __init__(self, dsns: str | dict[str, str]):
        self.dsns = {r: dsns for r in ROLES} if isinstance(dsns, str) else dict(dsns)
        self._local = threading.local()

    # ---------------------------------------------------------------- connections
    def conn(self, role: str) -> psycopg.Connection:
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = self._local.conns = {}
        c = conns.get(role)
        if c is None or c.closed or c.broken:
            c = psycopg.connect(self.dsns[role], autocommit=True, row_factory=dict_row)
            conns[role] = c
        return c

    @contextmanager
    def tx(self, role: str = "gateway") -> Iterator[psycopg.Cursor]:
        """One transaction on `role`'s connection. Deferred receipt checks run at COMMIT."""
        c = self.conn(role)
        with c.transaction():
            with c.cursor() as cur:
                yield cur

    def close(self) -> None:
        for c in (getattr(self._local, "conns", None) or {}).values():
            c.close()
        self._local.conns = {}

    # ---------------------------------------------------------------- provenance / receipts
    @staticmethod
    def record_provenance(cur, prov: dict) -> str:
        return cur.execute("SELECT mbos.record_provenance(%s) AS id", (J(prov),)).fetchone()["id"]

    @staticmethod
    def missing_provenance(cur, ids: list[str]) -> list[str]:
        rows = cur.execute("SELECT p FROM unnest(%s::text[]) p WHERE NOT EXISTS "
                           "(SELECT 1 FROM mbos.provenance v WHERE v.provenance_id = p)", (ids,)).fetchall()
        return [r["p"] for r in rows]

    @staticmethod
    def append_receipt(cur, partial: dict) -> dict:
        r = cur.execute("SELECT mbos.receipt_document(mbos.append_receipt(%s)) AS doc", (J(partial),)).fetchone()
        return r["doc"]

    def receipts(self, action_request_id: str | None = None) -> list[dict]:
        q = "SELECT d.doc FROM mbos.v_receipt_documents d"
        args: tuple = ()
        if action_request_id:
            q += " JOIN mbos.receipts r USING (receipt_id) WHERE r.action_request_id = %s"
            args = (action_request_id,)
        return [r["doc"] for r in self.conn("gateway").execute(q + " ORDER BY d.seq", args)]

    def verify_chain(self) -> tuple[bool, str]:
        r = self.conn("gateway").execute("SELECT * FROM mbos.verify_chain()").fetchone()
        return bool(r["ok"]), (f"ok ({r['receipts_checked']} receipts)" if r["ok"]
                               else f"broken at seq {r['first_bad_seq']}: {r['reason']}")

    # ---------------------------------------------------------------- action requests
    @staticmethod
    def get_action_request(cur, action_request_id: str, lock: bool = False) -> dict | None:
        if lock:
            cur.execute("SELECT 1 FROM mbos.action_requests WHERE action_request_id=%s FOR UPDATE", (action_request_id,))
        r = cur.execute("SELECT doc FROM mbos.v_action_request_documents WHERE action_request_id=%s",
                        (action_request_id,)).fetchone()
        return r["doc"] if r else None

    def action_request(self, action_request_id: str) -> dict | None:
        with self.conn("gateway").cursor() as cur:
            return self.get_action_request(cur, action_request_id)

    @staticmethod
    def find_by_idempotency_key(cur, key: str) -> dict | None:
        r = cur.execute("SELECT d.doc FROM mbos.v_action_request_documents d JOIN mbos.action_requests a "
                        "USING (action_request_id) WHERE a.idempotency_key=%s", (key,)).fetchone()
        return r["doc"] if r else None

    @staticmethod
    def propose_action(cur, ar: dict, actor: dict, intent: str, key: str) -> str:
        return cur.execute("SELECT mbos.propose_action(%s,%s,%s,%s) AS id",
                           (J(ar), J(actor), intent, key)).fetchone()["id"]

    @staticmethod
    def set_status(cur, areq: str, to: str, rtype: str, actor: dict, intent: str, prov: list[str], key: str,
                   extra: dict | None = None, tier: int | None = None) -> str:
        return cur.execute("SELECT mbos.set_action_status(%s,%s,%s,%s,%s,%s,%s,%s,%s) AS id",
                           (areq, to, rtype, J(actor), intent, prov, key, J(extra or {}), tier)).fetchone()["id"]

    # ---------------------------------------------------------------- approvals
    @staticmethod
    def latest_approval(cur, action_request_id: str) -> dict | None:
        r = cur.execute("SELECT d.doc FROM mbos.v_approval_documents d JOIN mbos.approvals a USING (approval_id) "
                        "WHERE a.action_request_id=%s ORDER BY a.seq DESC LIMIT 1", (action_request_id,)).fetchone()
        return r["doc"] if r else None

    @staticmethod
    def record_approval(cur, approval: dict, actor: dict, intent: str, key: str) -> str:
        return cur.execute("SELECT mbos.record_approval(%s,%s,%s,%s) AS id",
                           (J(approval), J(actor), intent, key)).fetchone()["id"]

    # ---------------------------------------------------------------- execution claims
    @staticmethod
    def claim_state(cur, action_request_id: str) -> dict | None:
        return cur.execute("SELECT state, response FROM mbos.effector_calls WHERE action_request_id=%s",
                           (action_request_id,)).fetchone()

    @staticmethod
    def effector_claim(cur, action_request_id: str, request: dict) -> dict:
        return cur.execute("SELECT * FROM mbos.effector_claim(%s,%s)", (action_request_id, J(request))).fetchone()

    @staticmethod
    def stuck_claims(cur, older_than_seconds: int) -> list[str]:
        """Execution claims still `executing` longer than the TTL (DB clock: claimed_at is DB time)."""
        # A request still `executing` whose claim is `executing` (crash before/at the send) OR `executed`
        # (crash after the send, before the outcome receipts) is stuck.
        return [r["action_request_id"] for r in cur.execute(
            "SELECT c.action_request_id FROM mbos.effector_calls c JOIN mbos.action_requests a USING (action_request_id) "
            "WHERE a.status = 'executing' AND c.claimed_at < now() - make_interval(secs => %s) ORDER BY c.claimed_at",
            (older_than_seconds,))]

    @staticmethod
    def effector_finish(cur, action_request_id: str, state: str, provider: str | None, msg_id: str | None,
                        response: dict) -> None:
        cur.execute("SELECT mbos.effector_finish(%s,%s,%s,%s,%s)", (action_request_id, state, provider, msg_id, J(response)))

    # ---------------------------------------------------------------- budget
    @staticmethod
    def open_reservation(cur, action_request_id: str) -> dict | None:
        """The request's reservation that has not been committed or released (zero-amount included)."""
        return cur.execute("SELECT r.entry_id AS reservation_id, r.amount AS reserved, r.mode, r.category "
                           "FROM mbos.budget_ledger r WHERE r.kind='reserve' AND r.action_request_id=%s AND NOT EXISTS "
                           "(SELECT 1 FROM mbos.budget_ledger s WHERE s.reservation_id=r.entry_id) "
                           "ORDER BY r.ts DESC LIMIT 1", (action_request_id,)).fetchone()

    @staticmethod
    def budget_lock(cur, currency: str) -> None:
        cur.execute("SELECT mbos.budget_lock(%s)", (currency,))

    @staticmethod
    def cash_at_risk(cur, item_id: str, categories: list[str], currency: str, mode: str):
        """(this item's, all items') outstanding binding cash: reserved minus released over offer/purchase."""
        r = cur.execute(
            "SELECT coalesce(sum(CASE b.kind WHEN 'reserve' THEN b.amount WHEN 'release' THEN -b.amount ELSE 0 END) "
            "FILTER (WHERE a.item_id = %s), 0) AS item_amt, "
            "coalesce(sum(CASE b.kind WHEN 'reserve' THEN b.amount WHEN 'release' THEN -b.amount ELSE 0 END), 0) AS total_amt "
            "FROM mbos.budget_ledger b JOIN mbos.action_requests a USING (action_request_id) "
            "WHERE b.category = ANY(%s) AND b.currency = %s AND b.mode = %s", (item_id, categories, currency, mode)).fetchone()
        return r["item_amt"], r["total_amt"]

    @staticmethod
    def reserve_caps(cur, areq: str, amount, currency: str, caps: dict, mode: str, actor: dict, intent: str,
                     prov: list[str], key: str) -> str:
        return cur.execute("SELECT mbos.budget_reserve_caps(%s,%s,%s,%s,%s,%s,%s,%s,%s) AS id",
                           (areq, amount, currency, J(caps), mode, J(actor), intent, prov, key)).fetchone()["id"]

    @staticmethod
    def settle(cur, reservation_id: str, kind: str, amount, actor: dict, intent: str, prov: list[str], key: str) -> str:
        return cur.execute("SELECT mbos.budget_settle(%s,%s,%s,%s,%s,%s,%s) AS id",
                           (reservation_id, kind, amount, J(actor), intent, prov, key)).fetchone()["id"]

    # ---------------------------------------------------------------- PANIC
    @staticmethod
    def panic_set(cur, level: str, target: str | None, engage: bool, actor: dict, reason: str, prov: list[str],
                  key: str) -> str:
        return cur.execute("SELECT mbos.panic_set(%s,%s,%s,%s,%s,%s,%s) AS id",
                           (level, target, engage, J(actor), reason, prov, key)).fetchone()["id"]


class DurableProviderLedger:
    """The simulated provider's delivery log = lane D's mbos.effector_calls (R22). `record_sent` is the
    provider's own durable write (its own committed transaction, before success is reported); `lookup`
    answers "did the call land?" from that row. Only a row in state `executed` is proof of a send."""

    def __init__(self, store: "PgGovernanceStore"):
        self.store = store

    def record_sent(self, action_request_id: str, response: dict) -> None:
        with self.store.tx("gateway") as cur:
            self.store.effector_finish(cur, action_request_id, "executed", response.get("provider"),
                                       response.get("provider_msg_id"), response)

    def lookup(self, action_request_id: str) -> dict | None:
        with self.store.tx("gateway") as cur:
            row = self.store.claim_state(cur, action_request_id)
        return row["response"] if row and row["state"] == "executed" and row["response"] else None


class PgPanicStore:
    """PANIC state reader on lane D's sealed `panic_state` (05 semantics, ruling R5).

    FAIL CLOSED: any failure (no connection, missing function, permission, timeout, an empty or
    tampered state) yields an unreadable PanicState, which blocks everything. Writes are not done here;
    they go through ActionGateway.engage_panic / release_panic, which receipt them via mbos.panic_set."""

    def __init__(self, dsn: str, connect_timeout: int = 5):
        self.dsn = dsn
        self.connect_timeout = connect_timeout
        self._local = threading.local()

    def _conn(self) -> psycopg.Connection:
        c = getattr(self._local, "conn", None)
        if c is None or c.closed or c.broken:
            c = psycopg.connect(self.dsn, autocommit=True, row_factory=dict_row, connect_timeout=self.connect_timeout)
            self._local.conn = c
        return c

    def read(self) -> PanicState:
        try:
            r = self._conn().execute("SELECT * FROM mbos.panic_read()").fetchone()
        except Exception as exc:  # noqa: BLE001 - every failure is FROZEN
            c = getattr(self._local, "conn", None)
            if c is not None:
                try:
                    c.close()
                except Exception:  # noqa: BLE001
                    pass
                self._local.conn = None
            return PanicState(global_state=FROZEN, readable=False, error=f"{type(exc).__name__}: {exc}")
        if not r or not r["readable"]:
            return PanicState(global_state=FROZEN, readable=False, error=(r or {}).get("error") or "no row")
        return PanicState(global_state=r["global_state"], frozen_agents=r["agents"] or {},
                          frozen_capabilities=r["capabilities"] or {}, revision=int(r["revision"]))
