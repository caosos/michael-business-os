"""Chain export, external anchoring and an offline verifier that does not trust the database.

Export format (JSONL, one receipt per line): {"seq", "receipt_id", "canonical", "row_hash"} where
``canonical`` is the exact text whose sha256 is ``row_hash``. The verifier recomputes every hash and
checks seq continuity and prev_hash linkage using only this file and Python's hashlib.

An anchor is the head (seq, row_hash) written somewhere the database host cannot rewrite (off-box
backup target, git, printed). A chain that no longer contains the anchored row_hash at the anchored
seq was truncated or rewritten.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from datetime import datetime, timezone
from pathlib import Path

import psycopg


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def export_chain(conn: psycopg.Connection, out: Path, from_seq: int = 1) -> int:
    n = 0
    # server-side cursor (streams large chains); REPEATABLE READ-like consistency comes from one statement
    with out.open("w", encoding="utf-8") as fh, conn.transaction(), conn.cursor(name="mbos_chain_export") as cur:
        cur.execute(
            "SELECT seq, receipt_id, canonical, row_hash FROM mbos.receipts WHERE seq >= %s ORDER BY seq", (from_seq,)
        )
        for seq, rid, canonical, row_hash in cur:
            fh.write(json.dumps({"seq": seq, "receipt_id": rid, "canonical": canonical, "row_hash": row_hash}) + "\n")
            n += 1
    return n


def write_anchor(conn: psycopg.Connection, out: Path) -> dict:
    row = conn.execute("SELECT seq, receipt_id, row_hash, ts FROM mbos.chain_head()").fetchone()
    if row is None:
        raise RuntimeError("empty receipt chain; nothing to anchor")
    anchor = {
        "seq": row[0], "receipt_id": row[1], "row_hash": row[2], "ts": row[3].isoformat(),
        "anchored_at": datetime.now(timezone.utc).isoformat(),
    }
    with out.open("a", encoding="utf-8") as fh:  # anchor log is append-only by convention
        fh.write(json.dumps(anchor) + "\n")
    return anchor


def verify_lines(lines: Iterable[str], anchors: Iterable[dict] = ()) -> tuple[bool, int, str | None]:
    """Returns (ok, receipts_checked, problem)."""
    expected_seq = None
    prev_hash = None
    seen: dict[int, str] = {}
    n = 0
    for line in lines:
        if not line.strip():
            continue
        rec = json.loads(line)
        seq, canonical, row_hash = rec["seq"], rec["canonical"], rec["row_hash"]
        doc = json.loads(canonical)
        if expected_seq is None:
            expected_seq = seq
            prev_hash = doc.get("prev_hash") if seq > 1 else None
        if seq != expected_seq:
            return False, n, f"seq gap at {expected_seq} (found {seq})"
        if doc.get("seq") != seq or doc.get("receipt_id") != rec["receipt_id"]:
            return False, n, f"seq {seq}: export metadata does not match canonical document"
        if doc.get("prev_hash") != prev_hash:
            return False, n, f"seq {seq}: prev_hash does not link to the previous row_hash"
        if sha256_text(canonical) != row_hash:
            return False, n, f"seq {seq}: row_hash does not match canonical bytes"
        seen[seq] = row_hash
        prev_hash = row_hash
        expected_seq = seq + 1
        n += 1
    for a in anchors:
        if a["seq"] not in seen:
            return False, n, f"anchored seq {a['seq']} missing (truncated?)"
        if seen[a["seq"]] != a["row_hash"]:
            return False, n, f"anchored seq {a['seq']} row_hash differs (rewritten?)"
    return True, n, None


def verify_export(path: Path, anchor_log: Path | None = None) -> tuple[bool, int, str | None]:
    anchors = []
    if anchor_log and anchor_log.exists():
        anchors = [json.loads(x) for x in anchor_log.read_text(encoding="utf-8").splitlines() if x.strip()]
    with path.open(encoding="utf-8") as fh:
        return verify_lines(fh, anchors)
