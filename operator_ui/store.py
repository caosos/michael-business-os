"""Local ledger store for the Operator UI.

STAND-IN, NOT THE SPINE. ADR-0001 makes Postgres the system of record and lane D
(Agent 04) owns the DDL and the State MCP write path. This SQLite store exists
so the approval UX can be built and tested now, with the same guarantees
lane D must provide:

* state change + receipt in ONE transaction (A1): `with store.tx() as tx:`
* receipts / approvals / provenance are insert-only, enforced by triggers (A2)
* receipts are hash-chained: row_hash = sha256(canonical(row - row_hash) || prev_hash) (A3)
* every row is validated against the frozen contracts before commit (A10)

Swapping to Postgres means re-implementing `Store`/`Tx` with the same methods.
"""

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager

from .contracts import ContractValidator
from .util import canonical_json, iso, new_id

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS items (
  item_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS action_requests (
  action_request_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, status TEXT NOT NULL,
  created_at TEXT NOT NULL, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS approvals (
  approval_id TEXT PRIMARY KEY, action_request_id TEXT NOT NULL, decided_at TEXT NOT NULL,
  doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provenance (
  provenance_id TEXT PRIMARY KEY, doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS receipts (
  seq INTEGER PRIMARY KEY, receipt_id TEXT NOT NULL UNIQUE, idempotency_key TEXT NOT NULL UNIQUE,
  item_id TEXT, action_request_id TEXT, type TEXT NOT NULL, row_hash TEXT NOT NULL,
  doc TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS hold_timers (
  action_request_id TEXT PRIMARY KEY, approval_id TEXT NOT NULL, hold_until TEXT,
  wake_on TEXT NOT NULL, next_renotify_at TEXT, renotify_after TEXT, escalate_at TEXT);
CREATE TABLE IF NOT EXISTS system (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dryrun_outbox (
  idempotency_key TEXT PRIMARY KEY, action_request_id TEXT NOT NULL, response TEXT NOT NULL);
"""

_INSERT_ONLY = ("receipts", "approvals", "provenance", "dryrun_outbox")


def _triggers():
    out = []
    for t in _INSERT_ONLY:
        for op in ("UPDATE", "DELETE"):
            out.append(
                f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                f"BEGIN SELECT RAISE(ABORT, '{t} is insert-only'); END;"
            )
    return "\n".join(out)


def row_hash_of(row, prev_hash):
    body = {k: v for k, v in row.items() if k != "row_hash"}
    data = canonical_json(body).encode("utf-8") + (prev_hash or "").encode("utf-8")
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, path=":memory:", validator=None):
        self.validator = validator or ContractValidator()
        self._lock = threading.RLock()
        self.db = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL" if path != ":memory:" else "PRAGMA journal_mode=MEMORY")
        self.db.executescript(SCHEMA_SQL + _triggers())
        self.db.execute("INSERT OR IGNORE INTO system VALUES ('system_state','RUNNING')")
        self.db.execute("INSERT OR IGNORE INTO system VALUES ('system_mode','mvp')")

    # ---- transactions -------------------------------------------------
    @contextmanager
    def tx(self):
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield Tx(self)
            except BaseException:
                self.db.execute("ROLLBACK")
                raise
            else:
                self.db.execute("COMMIT")

    # ---- reads ----------------------------------------------------------
    def _one(self, sql, args=()):
        with self._lock:
            r = self.db.execute(sql, args).fetchone()
        return json.loads(r[0]) if r else None

    def _many(self, sql, args=()):
        with self._lock:
            return [json.loads(r[0]) for r in self.db.execute(sql, args).fetchall()]

    def item(self, item_id):
        return self._one("SELECT doc FROM items WHERE item_id=?", (item_id,))

    def action_request(self, areq_id):
        return self._one("SELECT doc FROM action_requests WHERE action_request_id=?", (areq_id,))

    def action_requests(self, statuses=None):
        if statuses:
            q = ",".join("?" * len(statuses))
            return self._many(
                f"SELECT doc FROM action_requests WHERE status IN ({q}) ORDER BY created_at", tuple(statuses)
            )
        return self._many("SELECT doc FROM action_requests ORDER BY created_at")

    def action_requests_for_item(self, item_id):
        return self._many("SELECT doc FROM action_requests WHERE item_id=? ORDER BY created_at", (item_id,))

    def approvals_for(self, areq_id):
        return self._many(
            "SELECT doc FROM approvals WHERE action_request_id=? ORDER BY decided_at, rowid", (areq_id,)
        )

    def approval(self, approval_id):
        return self._one("SELECT doc FROM approvals WHERE approval_id=?", (approval_id,))

    def provenance(self, prov_id):
        return self._one("SELECT doc FROM provenance WHERE provenance_id=?", (prov_id,))

    def receipts(self, item_id=None, areq_id=None, rtype=None):
        sql, args = "SELECT doc FROM receipts WHERE 1=1", []
        if item_id:
            sql += " AND item_id=?"
            args.append(item_id)
        if areq_id:
            sql += " AND action_request_id=?"
            args.append(areq_id)
        if rtype:
            sql += " AND type=?"
            args.append(rtype)
        return self._many(sql + " ORDER BY seq", tuple(args))

    def receipt_by_key(self, idempotency_key):
        return self._one("SELECT doc FROM receipts WHERE idempotency_key=?", (idempotency_key,))

    def hold_timers(self):
        with self._lock:
            cur = self.db.execute("SELECT * FROM hold_timers")
            cols = [c[0] for c in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def hold_timer(self, areq_id):
        return next((h for h in self.hold_timers() if h["action_request_id"] == areq_id), None)

    def system(self, key):
        """Raises if unreadable; callers treat any exception as FROZEN (fail-closed, A9)."""
        with self._lock:
            r = self.db.execute("SELECT value FROM system WHERE key=?", (key,)).fetchone()
        if r is None:
            raise LookupError(f"system key {key!r} unreadable")
        return r[0]

    def dryrun_sent(self, idempotency_key):
        return self._one("SELECT response FROM dryrun_outbox WHERE idempotency_key=?", (idempotency_key,))

    def verify_chain(self):
        """Recompute every row_hash in seq order. Returns (ok, first_bad_seq_or_None, count)."""
        with self._lock:
            rows = self.db.execute("SELECT seq, doc, row_hash FROM receipts ORDER BY seq").fetchall()
        prev = None
        for seq, doc, stored in rows:
            r = json.loads(doc)
            if r.get("prev_hash") != prev or r.get("row_hash") != stored or row_hash_of(r, prev) != stored:
                return False, seq, len(rows)
            prev = stored
        return True, None, len(rows)


class Tx:
    """Write handle valid only inside `Store.tx()`."""

    def __init__(self, store):
        self.s = store
        self.db = store.db
        self.v = store.validator

    def put_item(self, doc):
        self.v.check("item", doc)
        self.db.execute("INSERT OR REPLACE INTO items VALUES (?,?)", (doc["item_id"], canonical_json(doc)))

    def put_action_request(self, doc):
        self.v.check("action_request", doc)
        self.db.execute(
            "INSERT INTO action_requests VALUES (?,?,?,?,?) ON CONFLICT(action_request_id) "
            "DO UPDATE SET status=excluded.status, doc=excluded.doc",
            (doc["action_request_id"], doc["item_id"], doc["status"], doc["created_at"], canonical_json(doc)),
        )

    def add_approval(self, doc):
        self.v.check("approval", doc)
        self.db.execute(
            "INSERT INTO approvals VALUES (?,?,?,?)",
            (doc["approval_id"], doc["action_request_id"], doc["decided_at"], canonical_json(doc)),
        )

    def add_provenance(self, doc):
        self.v.check("provenance", doc)
        self.db.execute("INSERT INTO provenance VALUES (?,?)", (doc["provenance_id"], canonical_json(doc)))

    def add_receipt(self, now, **fields):
        """Append one hash-chained receipt. Fills receipt_id, seq, ts, schema_version, hashes."""
        last = self.db.execute("SELECT seq, row_hash FROM receipts ORDER BY seq DESC LIMIT 1").fetchone()
        seq, prev = (last[0] + 1, last[1]) if last else (1, None)
        r = {"receipt_id": new_id("rcpt"), "seq": seq, "ts": iso(now), "schema_version": "1.0.0"}
        r.update(fields)
        r["prev_hash"] = prev
        r["row_hash"] = row_hash_of(r, prev)
        self.v.check("receipt", r)
        self.db.execute(
            "INSERT INTO receipts VALUES (?,?,?,?,?,?,?,?)",
            (seq, r["receipt_id"], r["idempotency_key"], r.get("item_id"), r.get("action_request_id"),
             r["type"], r["row_hash"], canonical_json(r)),
        )
        return r

    def set_hold_timer(self, areq_id, approval_id, hold_until, wake_on, next_renotify_at, renotify_after, escalate_at):
        self.db.execute(
            "INSERT OR REPLACE INTO hold_timers VALUES (?,?,?,?,?,?,?)",
            (areq_id, approval_id, hold_until, json.dumps(wake_on), next_renotify_at, renotify_after, escalate_at),
        )

    def bump_renotify(self, areq_id, next_at):
        self.db.execute("UPDATE hold_timers SET next_renotify_at=? WHERE action_request_id=?", (next_at, areq_id))

    def clear_hold_timer(self, areq_id):
        self.db.execute("DELETE FROM hold_timers WHERE action_request_id=?", (areq_id,))

    def set_system(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO system VALUES (?,?)", (key, value))

    def record_dryrun(self, idempotency_key, areq_id, response):
        self.db.execute(
            "INSERT INTO dryrun_outbox VALUES (?,?,?)", (idempotency_key, areq_id, canonical_json(response))
        )
