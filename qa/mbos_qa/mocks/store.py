"""MOCK — lane D (State/Receipts, Agent 04). Conforms to frozen contracts v1.0.0.

Reference implementation of the ledger invariants so the acceptance suite can run before
Agent 04's Postgres DDL lands. SQLite stands in for Postgres; the invariants are the same:
  * state change + receipt(s) + outbox row commit in ONE transaction (A1)
  * receipts / approvals / provenance / outcomes are insert-only via triggers (A2)
  * receipts are hash-chained by `seq` (A3)
  * every receipt's provenance_ids must already exist and resolve (A4)
  * every stored document is validated against the contracts before insert (A10)
REPLACE WITH: Agent 04's Postgres store behind the same `StateStore` protocol (interfaces.py).
Known mock limitation: SQLite has no roles, so A2 cannot prove the `agent_write` role is denied —
only that the trigger fires for every connection.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field

from ..contracts import ContractViolation, Contracts
from ..core import Clock, IdGen, iso, iso_receipt, receipt_row_hash
from ..statemachine import check_item_transition

IMPLEMENTATION = "MOCK reference store (SQLite) — stands in for Agent 04 Postgres"

APPEND_ONLY = ("receipts", "approvals", "provenance", "outcomes")

DDL = """
CREATE TABLE IF NOT EXISTS items (item_id TEXT PRIMARY KEY, state TEXT NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS action_requests (action_request_id TEXT PRIMARY KEY, item_id TEXT NOT NULL,
    status TEXT NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals (approval_id TEXT PRIMARY KEY, action_request_id TEXT NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provenance (provenance_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outcomes (outcome_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS receipts (seq INTEGER PRIMARY KEY, receipt_id TEXT UNIQUE NOT NULL,
    idempotency_key TEXT UNIQUE NOT NULL, type TEXT NOT NULL, item_id TEXT, action_request_id TEXT,
    doc TEXT NOT NULL, prev_hash TEXT, row_hash TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outbox (id INTEGER PRIMARY KEY AUTOINCREMENT, receipt_seq INTEGER NOT NULL,
    topic TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL);
""" + "\n".join(
    f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
    f"BEGIN SELECT RAISE(ABORT, 'append-only: {op} on {t} rejected'); END;"
    for t in APPEND_ONLY for op in ("UPDATE", "DELETE")
)


class InvariantViolation(Exception):
    pass


class InjectedFault(Exception):
    """Raised by a fault hook to simulate a crash inside a transaction."""


@dataclass
class ChainResult:
    ok: bool
    checked: int
    errors: list[str] = field(default_factory=list)


class Tx:
    """One unit of work. Everything written through a Tx commits or rolls back together."""

    def __init__(self, store: "ReferenceStore", cur: sqlite3.Cursor):
        self.store = store
        self.cur = cur
        self.c = store.contracts
        self.receipts: list[dict] = []

    def checkpoint(self, name: str) -> None:
        hook = self.store.faults.get(name)
        if hook:
            hook()

    # ---- documents -------------------------------------------------------------
    def put_provenance(self, prov: dict) -> str:
        self.c.check("provenance", prov)
        self.cur.execute("INSERT INTO provenance VALUES (?,?)", (prov["provenance_id"], json.dumps(prov)))
        return prov["provenance_id"]

    def put_item(self, item: dict) -> None:
        self.c.check("item", item)
        self.cur.execute("INSERT INTO items VALUES (?,?,?)", (item["item_id"], item["state"], json.dumps(item)))

    def replace_item(self, item: dict) -> None:
        self.c.check("item", item)
        self.cur.execute("UPDATE items SET state=?, doc=? WHERE item_id=?",
                         (item["state"], json.dumps(item), item["item_id"]))

    def put_action_request(self, areq: dict) -> None:
        self.c.check("action-request", areq)
        self._require_provenance(areq["provenance_ids"])
        self.cur.execute("INSERT INTO action_requests VALUES (?,?,?,?)",
                         (areq["action_request_id"], areq["item_id"], areq["status"], json.dumps(areq)))

    def replace_action_request(self, areq: dict) -> None:
        self.c.check("action-request", areq)
        self.cur.execute("UPDATE action_requests SET status=?, doc=? WHERE action_request_id=?",
                         (areq["status"], json.dumps(areq), areq["action_request_id"]))

    def put_approval(self, appr: dict) -> None:
        self.c.check("approval", appr)
        self.cur.execute("INSERT INTO approvals VALUES (?,?,?)",
                         (appr["approval_id"], appr["action_request_id"], json.dumps(appr)))

    def put_outcome(self, outc: dict) -> None:
        self.c.check("outcome", outc)
        self._require_provenance(outc["provenance_ids"])
        self.cur.execute("INSERT INTO outcomes VALUES (?,?)", (outc["outcome_id"], json.dumps(outc)))

    # ---- receipts --------------------------------------------------------------
    def receipt(self, *, type: str, actor: dict, intent: str, provenance_ids: list[str],
                idempotency_key: str, outbox_topic: str | None = None, **fields) -> dict:
        self._require_provenance(provenance_ids)
        row = self.cur.execute("SELECT seq, row_hash FROM receipts ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev_hash = (row[0] + 1, row[1]) if row else (1, None)
        doc = {
            "receipt_id": self.store.ids.new("rcpt"), "seq": seq, "ts": iso_receipt(self.store.clock.now()),
            "schema_version": "1.0.0", "type": type, "actor": actor, "intent": intent,
            "provenance_ids": list(provenance_ids), "idempotency_key": idempotency_key,
            **fields, "prev_hash": prev_hash,
        }
        doc["row_hash"] = receipt_row_hash(doc)
        self.c.check("receipt", doc)
        self.cur.execute(
            "INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?,?)",
            (seq, doc["receipt_id"], idempotency_key, type, doc.get("item_id"), doc.get("action_request_id"),
             json.dumps(doc), prev_hash, doc["row_hash"]),
        )
        self.cur.execute("INSERT INTO outbox (receipt_seq, topic, payload) VALUES (?,?,?)",
                         (seq, outbox_topic or type, json.dumps({"receipt_id": doc["receipt_id"]})))
        self.receipts.append(doc)
        return doc

    def _require_provenance(self, ids: list[str]) -> None:
        if not ids:
            raise InvariantViolation("no receipt/action without provenance")
        for pid in ids:
            r = self.cur.execute("SELECT doc FROM provenance WHERE provenance_id=?", (pid,)).fetchone()
            if r is None:
                raise InvariantViolation(f"provenance {pid} does not resolve")

    # ---- item state machine (A1) ----------------------------------------------
    def transition_item(self, item_id: str, new_state: str, *, actor: dict, intent: str,
                        provenance_ids: list[str], patch: dict | None = None, key: str | None = None) -> dict:
        item = self.store._load(self.cur, "items", "item_id", item_id)
        old = item["state"]
        check_item_transition(old, new_state)
        item.update(patch or {})
        item["state"] = new_state
        item["updated_at"] = iso(self.store.clock.now())
        self.replace_item(item)
        self.checkpoint("after_state_before_receipt")
        r = self.receipt(type="ITEM_STATE_CHANGED", actor=actor, intent=intent, provenance_ids=provenance_ids,
                         idempotency_key=key or f"item:{item_id}:{old}->{new_state}:{self.store.ids.new('rcpt')[5:]}",
                         item_id=item_id, entity_type="item", entity_id=item_id, effect="update",
                         before_state={"state": old}, after_state={"state": new_state})
        self.checkpoint("after_receipt_before_commit")
        item.setdefault("receipt_ids", []).append(r["receipt_id"])
        self.replace_item(item)
        return item


class ReferenceStore:
    implementation = IMPLEMENTATION

    def __init__(self, path: str | pathlib.Path = ":memory:", *, contracts: Contracts, clock: Clock, ids: IdGen):
        self.path = str(path)
        self.contracts, self.clock, self.ids = contracts, clock, ids
        self.faults: dict[str, callable] = {}
        self._lock = threading.RLock()
        self.conn = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL" if self.path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self.conn.execute("PRAGMA synchronous=FULL")
        # REPLACE conflict resolution deletes rows internally; without this, DELETE triggers do not fire
        self.conn.execute("PRAGMA recursive_triggers=ON")
        self.conn.executescript(DDL)

    @contextmanager
    def tx(self):
        with self._lock:
            cur = self.conn.cursor()
            cur.execute("BEGIN IMMEDIATE")
            try:
                t = Tx(self, cur)
                yield t
                cur.execute("COMMIT")
            except BaseException:
                cur.execute("ROLLBACK")
                raise

    # ---- reads -----------------------------------------------------------------
    @staticmethod
    def _load(cur, table, pk, key) -> dict:
        r = cur.execute(f"SELECT doc FROM {table} WHERE {pk}=?", (key,)).fetchone()
        if r is None:
            raise KeyError(f"{table}:{key}")
        return json.loads(r[0])

    def get(self, kind: str, key: str) -> dict:
        table, pk = {"item": ("items", "item_id"), "action-request": ("action_requests", "action_request_id"),
                     "approval": ("approvals", "approval_id"), "provenance": ("provenance", "provenance_id"),
                     "outcome": ("outcomes", "outcome_id")}[kind]
        with self._lock:
            return self._load(self.conn.cursor(), table, pk, key)

    def find_provenance(self, pid: str) -> dict | None:
        try:
            return self.get("provenance", pid)
        except KeyError:
            return None

    def receipts(self, **where) -> list[dict]:
        sql, args = "SELECT doc FROM receipts", []
        if where:
            sql += " WHERE " + " AND ".join(f"{k}=?" for k in where)
            args = list(where.values())
        with self._lock:
            return [json.loads(r[0]) for r in self.conn.execute(sql + " ORDER BY seq", args)]

    def receipt_by_key(self, key: str) -> dict | None:
        with self._lock:
            r = self.conn.execute("SELECT doc FROM receipts WHERE idempotency_key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else None

    def approvals_for(self, areq_id: str) -> list[dict]:
        with self._lock:
            rows = self.conn.execute("SELECT doc FROM approvals WHERE action_request_id=? ORDER BY rowid", (areq_id,))
            return [json.loads(r[0]) for r in rows]

    def action_requests(self, **where) -> list[dict]:
        sql, args = "SELECT doc FROM action_requests", []
        if where:
            sql += " WHERE " + " AND ".join(f"{k}=?" for k in where)
            args = list(where.values())
        with self._lock:
            return [json.loads(r[0]) for r in self.conn.execute(sql + " ORDER BY rowid", args)]

    def all_documents(self):
        """(contract kind, doc) for every stored row — used by A10."""
        tables = [("items", "item"), ("action_requests", "action-request"), ("approvals", "approval"),
                  ("receipts", "receipt"), ("provenance", "provenance"), ("outcomes", "outcome")]
        with self._lock:
            for table, kind in tables:
                for (doc,) in self.conn.execute(f"SELECT doc FROM {table}"):
                    yield kind, json.loads(doc)

    def count(self, table: str) -> int:
        with self._lock:
            return self.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def kv_get(self, k: str) -> str | None:
        with self._lock:
            r = self.conn.execute("SELECT v FROM kv WHERE k=?", (k,)).fetchone()
        return r[0] if r else None

    # ---- A3 --------------------------------------------------------------------
    def verify_chain(self) -> ChainResult:
        errors: list[str] = []
        prev = None
        n = 0
        with self._lock:
            rows = list(self.conn.execute("SELECT seq, doc, prev_hash, row_hash FROM receipts ORDER BY seq"))
        for i, (seq, raw, prev_col, hash_col) in enumerate(rows, start=1):
            n += 1
            if seq != i:
                errors.append(f"seq gap: expected {i}, found {seq}")
            try:
                doc = json.loads(raw)
            except json.JSONDecodeError:
                errors.append(f"seq {seq}: undecodable row")
                prev = hash_col
                continue
            if doc.get("seq") != seq:
                errors.append(f"seq {seq}: doc.seq={doc.get('seq')}")
            if doc.get("prev_hash") != prev or prev_col != prev:
                errors.append(f"seq {seq}: prev_hash does not link to seq {seq - 1}")
            if prev is not None and not str(doc.get("prev_hash", "")).startswith("sha256:"):
                errors.append(f"seq {seq}: prev_hash is not a sha256 ref")
            recomputed = receipt_row_hash(doc)
            if recomputed != doc.get("row_hash") or recomputed != hash_col:
                errors.append(f"seq {seq}: row_hash mismatch (tampered)")
            try:
                self.contracts.check("receipt", doc)
            except ContractViolation as e:
                errors.append(f"seq {seq}: {e}")
            prev = hash_col
        return ChainResult(ok=not errors, checked=n, errors=errors)

    # ---- QA hooks (test-only; simulate a superuser / on-disk tamper) ------------
    def qa_tamper_receipt(self, seq: int, mutate) -> None:
        with self._lock:
            self.conn.execute("DROP TRIGGER receipts_no_update")
            try:
                (raw,) = self.conn.execute("SELECT doc FROM receipts WHERE seq=?", (seq,)).fetchone()
                doc = json.loads(raw)
                mutate(doc)
                # a realistic attacker keeps the row self-consistent (columns mirror the doc)
                self.conn.execute("UPDATE receipts SET doc=?, prev_hash=?, row_hash=? WHERE seq=?",
                                  (json.dumps(doc), doc.get("prev_hash"), doc.get("row_hash"), seq))
            finally:
                self.conn.executescript(DDL)

    def close(self) -> None:
        self.conn.close()
