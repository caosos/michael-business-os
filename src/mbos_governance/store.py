"""Governance store — wave-one SQLite reference implementation.

Agent 04 owns the production ledger (Postgres, ADR-0001/0004). This module gives the
gateway the properties it depends on, so the guard logic is real and testable now:

  * receipts, approvals, provenance are INSERT-ONLY (triggers reject UPDATE/DELETE);
  * receipts are hash-chained: row_hash = sha256(canonical(row - row_hash) || prev_hash);
  * every state change and its receipt commit in ONE transaction (BEGIN IMMEDIATE);
  * every receipt is validated against receipt.schema.json v1.0.0 and every
    provenance_id it cites must already exist ("no receipt without provenance");
  * execution claims are UNIQUE per idempotency_key (exactly-once effect);
  * budget reservations are serialized by the write lock (no TOCTOU overshoot).

Swap path: re-implement GovernanceStore against Agent 04's DDL with the same methods.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from . import contracts
from .ids import canonical_json, fmt_ts, new_id, sha256_tagged, utcnow

DDL = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS provenance (
  provenance_id TEXT PRIMARY KEY,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS action_requests (
  action_request_id TEXT PRIMARY KEY,
  idempotency_key TEXT NOT NULL UNIQUE,
  proposed_by TEXT NOT NULL,
  status TEXT NOT NULL,
  policy_decision_ref TEXT,
  body TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
  ord INTEGER PRIMARY KEY AUTOINCREMENT,
  approval_id TEXT NOT NULL UNIQUE,
  action_request_id TEXT NOT NULL REFERENCES action_requests(action_request_id),
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS receipts (
  seq INTEGER PRIMARY KEY,
  receipt_id TEXT NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  type TEXT NOT NULL,
  action_request_id TEXT,
  body TEXT NOT NULL,
  prev_hash TEXT,
  row_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_claims (
  idempotency_key TEXT PRIMARY KEY,
  action_request_id TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL CHECK (state IN ('executing','executed','failed')),
  result TEXT,
  claimed_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS budget_reservations (
  action_request_id TEXT PRIMARY KEY,
  mode TEXT NOT NULL CHECK (mode IN ('dry_run','live')),
  bucket TEXT NOT NULL,
  amount_micros INTEGER NOT NULL CHECK (amount_micros >= 0),
  state TEXT NOT NULL CHECK (state IN ('reserved','committed','released')),
  day TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""

_IMMUTABLE = ("provenance", "approvals", "receipts")


def _immutability_triggers() -> str:
    out = []
    for t in _IMMUTABLE:
        for op in ("UPDATE", "DELETE"):
            out.append(
                f"CREATE TRIGGER IF NOT EXISTS {t}_no_{op.lower()} BEFORE {op} ON {t} "
                f"BEGIN SELECT RAISE(ABORT, '{t} is insert-only'); END;"
            )
    return "\n".join(out)


def compute_row_hash(row_without_hash: dict, prev_hash: str | None) -> str:
    return sha256_tagged(canonical_json(row_without_hash) + (prev_hash or ""))


class ProvenanceMissing(ValueError):
    pass


class GovernanceStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._local = threading.local()
        self._conn().executescript(DDL + _immutability_triggers())

    def _conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(self.path, timeout=60, isolation_level=None, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=60000")
            self._local.conn = conn
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Cursor]:
        """One write transaction. Anything raised inside rolls everything back."""
        conn = self._conn()
        cur = conn.cursor()
        cur.execute("BEGIN IMMEDIATE")
        try:
            yield cur
        except BaseException:
            cur.execute("ROLLBACK")
            raise
        else:
            cur.execute("COMMIT")

    # ---- provenance --------------------------------------------------------
    def insert_provenance(self, cur: sqlite3.Cursor, prov: dict) -> None:
        contracts.require_valid("provenance", prov)
        cur.execute("INSERT OR IGNORE INTO provenance VALUES (?, ?)", (prov["provenance_id"], canonical_json(prov)))
        existing = cur.execute("SELECT body FROM provenance WHERE provenance_id=?", (prov["provenance_id"],)).fetchone()
        if json.loads(existing["body"]) != prov:
            raise ValueError(f"provenance {prov['provenance_id']} already exists with different content")

    def require_provenance(self, cur: sqlite3.Cursor, ids: list[str]) -> None:
        if not ids:
            raise ProvenanceMissing("no provenance ids")
        for pid in ids:
            if cur.execute("SELECT 1 FROM provenance WHERE provenance_id=?", (pid,)).fetchone() is None:
                raise ProvenanceMissing(f"provenance {pid} not recorded")

    # ---- receipts ----------------------------------------------------------
    def append_receipt(self, cur: sqlite3.Cursor, partial: dict) -> dict:
        last = cur.execute("SELECT seq, row_hash FROM receipts ORDER BY seq DESC LIMIT 1").fetchone()
        seq = (last["seq"] + 1) if last else 1
        prev_hash = last["row_hash"] if last else None
        row = {
            "receipt_id": new_id("rcpt"),
            "seq": seq,
            "ts": fmt_ts(utcnow()),
            "schema_version": "1.0.0",
            **partial,
            "prev_hash": prev_hash,
        }
        row.setdefault("idempotency_key", f"{row['receipt_id']}")
        row["row_hash"] = compute_row_hash(row, prev_hash)
        contracts.require_valid("receipt", row)
        self.require_provenance(cur, row["provenance_ids"])
        cur.execute(
            "INSERT INTO receipts (seq, receipt_id, idempotency_key, type, action_request_id, body, prev_hash, row_hash)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (seq, row["receipt_id"], row["idempotency_key"], row["type"], row.get("action_request_id"),
             canonical_json(row), prev_hash, row["row_hash"]),
        )
        return row

    def receipts(self, action_request_id: str | None = None) -> list[dict]:
        q = "SELECT body FROM receipts" + (" WHERE action_request_id=?" if action_request_id else "") + " ORDER BY seq"
        args = (action_request_id,) if action_request_id else ()
        return [json.loads(r["body"]) for r in self._conn().execute(q, args)]

    def verify_chain(self) -> tuple[bool, str]:
        prev = None
        expected_seq = 1
        for r in self._conn().execute("SELECT seq, body, prev_hash, row_hash FROM receipts ORDER BY seq"):
            body = json.loads(r["body"])
            if r["seq"] != expected_seq or body.get("seq") != r["seq"]:
                return False, f"seq gap/mismatch at {r['seq']}"
            if body.get("prev_hash") != prev or r["prev_hash"] != prev:
                return False, f"prev_hash break at seq {r['seq']}"
            claimed = body.pop("row_hash", None)
            if claimed != r["row_hash"] or compute_row_hash(body, prev) != claimed:
                return False, f"row_hash mismatch at seq {r['seq']}"
            prev = claimed
            expected_seq += 1
        return True, f"ok ({expected_seq - 1} receipts)"

    # ---- action requests ---------------------------------------------------
    def insert_action_request(self, cur: sqlite3.Cursor, ar: dict) -> None:
        cur.execute(
            "INSERT INTO action_requests VALUES (?,?,?,?,?,?,?)",
            (ar["action_request_id"], ar["idempotency_key"], ar["proposed_by"], ar["status"],
             ar.get("policy_decision_ref"), canonical_json(ar), fmt_ts(utcnow())),
        )

    def set_status(self, cur: sqlite3.Cursor, ar: dict, status: str) -> dict:
        new = {**ar, "status": status}
        cur.execute(
            "UPDATE action_requests SET status=?, policy_decision_ref=?, body=?, updated_at=? WHERE action_request_id=?",
            (status, new.get("policy_decision_ref"), canonical_json(new), fmt_ts(utcnow()), ar["action_request_id"]),
        )
        return new

    def get_action_request(self, cur_or_none, action_request_id: str) -> dict | None:
        c = cur_or_none or self._conn()
        r = c.execute("SELECT body FROM action_requests WHERE action_request_id=?", (action_request_id,)).fetchone()
        return json.loads(r["body"]) if r else None

    def find_by_idempotency_key(self, cur: sqlite3.Cursor, key: str) -> dict | None:
        r = cur.execute("SELECT body FROM action_requests WHERE idempotency_key=?", (key,)).fetchone()
        return json.loads(r["body"]) if r else None

    def requests_with_status(self, cur: sqlite3.Cursor, statuses: tuple[str, ...]) -> list[dict]:
        q = f"SELECT body FROM action_requests WHERE status IN ({','.join('?' * len(statuses))})"
        return [json.loads(r["body"]) for r in cur.execute(q, statuses)]

    # ---- approvals ---------------------------------------------------------
    def insert_approval(self, cur: sqlite3.Cursor, approval: dict) -> None:
        cur.execute("INSERT INTO approvals (approval_id, action_request_id, body) VALUES (?,?,?)",
                    (approval["approval_id"], approval["action_request_id"], canonical_json(approval)))

    def latest_approval(self, cur: sqlite3.Cursor, action_request_id: str) -> dict | None:
        r = cur.execute("SELECT body FROM approvals WHERE action_request_id=? ORDER BY ord DESC LIMIT 1",
                        (action_request_id,)).fetchone()
        return json.loads(r["body"]) if r else None

    # ---- execution claims (idempotency) ------------------------------------
    def get_claim(self, cur: sqlite3.Cursor, key: str) -> sqlite3.Row | None:
        return cur.execute("SELECT * FROM execution_claims WHERE idempotency_key=?", (key,)).fetchone()

    def claim(self, cur: sqlite3.Cursor, key: str, action_request_id: str) -> None:
        cur.execute("INSERT INTO execution_claims VALUES (?,?,?,?,?,?)",
                    (key, action_request_id, "executing", None, fmt_ts(utcnow()), None))

    def finish_claim(self, cur: sqlite3.Cursor, key: str, state: str, result: dict) -> None:
        cur.execute("UPDATE execution_claims SET state=?, result=?, finished_at=? WHERE idempotency_key=? AND state='executing'",
                    (state, canonical_json(result), fmt_ts(utcnow()), key))
        if cur.rowcount != 1:
            raise RuntimeError(f"claim {key} not in executing state")

    # ---- budget ------------------------------------------------------------
    def reservation(self, cur: sqlite3.Cursor, action_request_id: str) -> sqlite3.Row | None:
        return cur.execute("SELECT * FROM budget_reservations WHERE action_request_id=?", (action_request_id,)).fetchone()

    def spent_micros(self, cur: sqlite3.Cursor, mode: str, day: str, bucket: str | None = None) -> int:
        q = "SELECT COALESCE(SUM(amount_micros),0) s FROM budget_reservations WHERE mode=? AND day=? AND state IN ('reserved','committed')"
        args: list = [mode, day]
        if bucket is not None:
            q += " AND bucket=?"
            args.append(bucket)
        return int(cur.execute(q, args).fetchone()["s"])

    def bucket_actions_since(self, cur: sqlite3.Cursor, mode: str, bucket: str, since_iso: str) -> int:
        return int(cur.execute(
            "SELECT COUNT(*) c FROM budget_reservations WHERE mode=? AND bucket=? AND created_at>=? AND state IN ('reserved','committed')",
            (mode, bucket, since_iso)).fetchone()["c"])

    def reserve(self, cur: sqlite3.Cursor, action_request_id: str, mode: str, bucket: str, micros: int, day: str) -> None:
        cur.execute("INSERT INTO budget_reservations VALUES (?,?,?,?,?,?,?)",
                    (action_request_id, mode, bucket, micros, "reserved", day, fmt_ts(utcnow())))

    def settle(self, cur: sqlite3.Cursor, action_request_id: str, state: str, micros: int | None = None) -> None:
        if micros is None:
            cur.execute("UPDATE budget_reservations SET state=? WHERE action_request_id=? AND state='reserved'",
                        (state, action_request_id))
        else:
            cur.execute("UPDATE budget_reservations SET state=?, amount_micros=? WHERE action_request_id=? AND state='reserved'",
                        (state, micros, action_request_id))
