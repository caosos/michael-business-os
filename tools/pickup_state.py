"""Durable state + chained receipts for automatic GitHub pickup (tools/inbox_pickup.py).

One instruction id moves FETCHED -> DELIVERED -> ACKED -> RUNNING -> COMPLETED, or BLOCKED with a specific reason. Reading a file is FETCHED only;
DELIVERED means the executor was actually started; ACKED means the ack file is on the coordinator branch; COMPLETED needs the executor's receipt.
The state file is the idempotency record: a restart reads it and never re-executes a COMPLETED id. Receipts never carry credentials or message bodies.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from mbos.hashing import sha256_of  # noqa: E402

STATES = ("FETCHED", "DELIVERED", "ACKED", "RUNNING", "COMPLETED", "BLOCKED")
TERMINAL = ("COMPLETED",)
ACTOR = "agent-01-pickup"
_SECRET_HINTS = ("token", "secret", "password", "api_key", "authorization")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Store:
    def __init__(self, directory: Path):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path, self.receipts_path = self.dir / "state.json", self.dir / "receipts.jsonl"

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def _save(self, data: dict[str, Any]) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
        os.replace(tmp, self.state_path)          # atomic: a crash leaves the old file, never half a file

    def all(self) -> dict[str, Any]:
        return self._load()

    def get(self, mid: str) -> dict[str, Any]:
        return self._load().get(mid, {})

    def last_hash(self) -> str:
        try:
            lines = [x for x in self.receipts_path.read_text().splitlines() if x.strip()]
            return json.loads(lines[-1])["row_hash"] if lines else "sha256:" + "0" * 64
        except (OSError, ValueError, KeyError):
            return "sha256:" + "0" * 64

    def receipt(self, task_id: str, operation: str, outcome: str, *, exit_status: Optional[int] = None, evidence: Optional[list[str]] = None,
                branch: Optional[str] = None, sha: Optional[str] = None) -> dict[str, Any]:
        """Append one hash-chained receipt: timestamp, actor, task id, operation, outcome, exit status, evidence links, branch/SHA for code."""
        row = {"at": now(), "actor": ACTOR, "task_id": task_id, "operation": operation, "outcome": outcome, "exit_status": exit_status,
               "evidence": [e for e in (evidence or []) if not any(h in e.lower() for h in _SECRET_HINTS)], "branch": branch, "sha": sha,
               "prev_hash": self.last_hash()}
        row["row_hash"] = sha256_of(row)
        with self.receipts_path.open("a") as f:
            f.write(json.dumps(row, sort_keys=True) + "\n")
        return row

    def move(self, mid: str, state: str, *, operation: str, outcome: str = "ok", **fields: Any) -> dict[str, Any]:
        """Record a transition (state file first, receipt second, so a crash can only under-report, never claim work that did not happen)."""
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        data = self._load()
        cur = data.get(mid, {})
        if cur.get("state") in TERMINAL and state != "COMPLETED":
            return cur                                         # a finished instruction is never reopened
        rec = {**cur, **fields, "state": state, f"{state.lower()}_at": now()}
        if state != "BLOCKED":
            rec.pop("blocked", None)
        data[mid] = rec
        self._save(data)
        self.receipt(mid, operation, outcome, exit_status=fields.get("exit_status"), evidence=fields.get("evidence"),
                     branch=fields.get("branch"), sha=fields.get("sha"))
        return rec

    def correct(self, mid: str, state: str, reason: str, **fields: Any) -> dict[str, Any]:
        """Audited override of a wrong record (the only way to reopen a COMPLETED id): the receipt carries the old state and the reason."""
        data = self._load()
        old = data.get(mid, {}).get("state")
        rec = {**data.get(mid, {}), **fields, "state": state, f"{state.lower()}_at": now(), "corrected_from": old}
        if state != "BLOCKED":
            rec.pop("blocked", None)
        data[mid] = rec
        self._save(data)
        self.receipt(mid, "state corrected", f"{old} -> {state}: {reason}", evidence=fields.get("evidence"))
        return rec

    def block(self, mid: str, reason: str, *, retry_after: Optional[float] = None, **fields: Any) -> dict[str, Any]:
        fields.setdefault("attempts", self.get(mid).get("attempts", 0))
        return self.move(mid, "BLOCKED", operation="blocked", outcome=reason, blocked=reason, retry_after=retry_after, **fields)


def summary(data: dict[str, Any]) -> dict[str, Any]:
    by: dict[str, list[str]] = {s: [] for s in STATES}
    for mid, r in data.items():
        by.setdefault(r.get("state", "FETCHED"), []).append(mid)
    return {s: sorted(v) for s, v in by.items() if v}
