"""Chain export, external anchoring and an offline verifier that does not trust the database.

Export format (JSONL, one Receipt v1 document per line, ordered by seq, row_hash included). Verification
uses ONLY the vendored ADR-0010 reference (`mbos_canonical`, stdlib): every row_hash is recomputed as
MBOS-RH-1 over the document, and seq continuity and prev_hash linkage are checked. Any lane can run the
same check with its own copy of `mbos_canonical.verify_chain`.

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

from . import mbos_canonical


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def export_chain(conn: psycopg.Connection, out: Path, from_seq: int = 1) -> int:
    n = 0
    # server-side cursor streams large chains
    with out.open("w", encoding="utf-8") as fh, conn.transaction(), conn.cursor(name="mbos_chain_export") as cur:
        cur.execute("SELECT doc::text FROM mbos.v_receipt_documents WHERE seq >= %s ORDER BY seq", (from_seq,))
        for (doc,) in cur:
            fh.write(doc + "\n")
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
    docs = [json.loads(line) for line in lines if line.strip()]
    if docs and docs[0]["seq"] == 1:
        ok, msg = mbos_canonical.verify_chain(docs)       # the normative ADR-0010 check, verbatim
        if not ok:
            return False, 0, msg
    prev = docs[0].get("prev_hash") if docs else None     # partial export: trust its first link only
    seen: dict[int, str] = {}
    for i, d in enumerate(docs):
        if i and d["seq"] != docs[i - 1]["seq"] + 1:
            return False, i, f"seq gap before {d['seq']}"
        if d.get("prev_hash") != prev:
            return False, i, f"seq {d['seq']}: prev_hash does not link to the previous row_hash"
        if mbos_canonical.receipt_row_hash(d) != d["row_hash"]:
            return False, i, f"seq {d['seq']}: row_hash mismatch (MBOS-RH-1)"
        seen[d["seq"]] = prev = d["row_hash"]
    for a in anchors:
        if a["seq"] not in seen:
            return False, len(docs), f"anchored seq {a['seq']} missing (truncated?)"
        if seen[a["seq"]] != a["row_hash"]:
            return False, len(docs), f"anchored seq {a['seq']} row_hash differs (rewritten?)"
    return True, len(docs), None


def verify_export(path: Path, anchor_log: Path | None = None) -> tuple[bool, int, str | None]:
    anchors = []
    if anchor_log and anchor_log.exists():
        anchors = [json.loads(x) for x in anchor_log.read_text(encoding="utf-8").splitlines() if x.strip()]
    with path.open(encoding="utf-8") as fh:
        return verify_lines(fh, anchors)
