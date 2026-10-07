"""C-12: produce a REAL lane-D export for the replay audit.

Writes 03's scored Items through Agent 04's receipted write API (``mbos_state.StateStore``) into a
THROWAWAY PostgreSQL 16 cluster, reads them back through 04's read views (``mbos.v_item_documents``,
``mbos.v_receipt_documents``), writes the export JSON and destroys the cluster. This exercises the
JSONB round trip (key order, number rendering) that a replay audit must survive.

Requires (scratch venv): psycopg[binary], pgserver, and Agent 04's ``mbos_state`` installed from a
read-only ``git archive`` of research/agent-04-state:

    python economics/scripts/lane_d_export.py --state-dir <archive>/state --out economics/tests/fixtures/lane_d_export/export.json
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests"))

import psycopg  # noqa: E402
from psycopg.types.json import Jsonb  # noqa: E402

from mbos_economics.comps_feed import load_fixture_comps, research_step  # noqa: E402
from mbos_economics.config import load_config  # noqa: E402
from mbos_economics.engine import score_item  # noqa: E402
from mbos_economics.estimate import apply_estimate, estimate_item  # noqa: E402
from mbos_economics.replay_audit import load_scored_items  # noqa: E402

AS_OF = "2026-10-07T18:00:00Z"


def corpus() -> list[tuple[dict, dict, list]]:
    """(item with scores+recommendation, score provenance, receipt drafts) for goldens + 02 fixtures."""
    out = []
    for p in sorted((ROOT / "examples").glob("*.scored.json")):
        d = json.loads(p.read_text())
        out.append((d["item"], d["provenance"], d["receipt_drafts"]))
    cfg = load_config()
    items = json.loads((ROOT / "tests" / "fixtures" / "agent02" / "items.json").read_text())
    for it in items:
        if it["type"] == "service":
            est = apply_estimate(it, estimate_item(it, None, AS_OF))
            o = score_item(est, cfg, AS_OF)
            est["scores"], est["recommendation"] = o["scores"], o["recommendation"]
            out.append((est, o["provenance"], o["receipt_drafts"]))
    tr = copy.deepcopy([i for i in items if i["category"] == "trailer" and i["normalized"]["title"].startswith("6x12")][0])
    tr["state"] = "RESEARCHING"
    comps, prov = load_fixture_comps(ROOT / "tests" / "fixtures" / "comps" / "sold_comps.json")
    r = research_step(tr, comps, prov, AS_OF)
    o = score_item(r["item"], cfg, AS_OF)          # same scored_at -> same ids as research_step's scoring
    out.append((r["item"], o["provenance"], o["receipt_drafts"]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--state-commit", default="unknown")
    args = ap.parse_args()
    import lane_d

    with lane_d.cluster(args.state_dir) as dsn:
        rows = corpus()
        lane_d.write_scored(dsn, rows)
        with psycopg.connect(dsn) as conn:
            items, receipts = load_scored_items(conn)
            server = conn.execute("SHOW server_version").fetchone()[0]
            chain = conn.execute("SELECT ok, receipts_checked FROM mbos.verify_chain(1, NULL, NULL)").fetchone()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({
            "_note": "Real lane-D export for C-12: written via Agent 04's StateStore into a throwaway PostgreSQL "
                     "cluster, read back via mbos.v_item_documents / v_receipt_documents. Fixture data only.",
            "exported_from": {"agent_04_state_commit": args.state_commit, "postgres": server,
                              "verify_chain": {"ok": chain[0], "receipts_checked": chain[1]}, "as_of": AS_OF},
            "items": items, "receipts": receipts}, indent=1, sort_keys=True) + "\n")
        print(f"exported {len(items)} scored items, {len(receipts)} SCORE_RECORDED receipts; chain ok={chain[0]}")


if __name__ == "__main__":
    main()
