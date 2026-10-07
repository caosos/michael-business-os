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


def pg_bin() -> Path:
    import pgserver
    return Path(pgserver.__file__).parent / "pginstall" / "bin"


def write_through_state_api(dsn: str, rows) -> None:
    from mbos_state.store import Actor, StateStore
    actor = Actor("agent", "agent-03-economics")
    with psycopg.connect(dsn, autocommit=False) as conn:
        st = StateStore(conn)
        for item, prov, drafts in rows:
            iid = item["item_id"]
            with st.transaction():
                p = {k: v for k, v in prov.items() if k != "derived_from"}   # upstream ids are not all in this DB
                pid = st.record_provenance(**p)
                base = {k: v for k, v in item.items() if k not in ("scores", "recommendation", "state")}
                base["state"] = "NORMALIZED"
                st.create_item(base, actor, "C-12 export: create", [pid], f"c12:create:{iid}")
                st.transition_item(iid, "RESEARCHING", actor, "C-12 export", [pid], f"c12:researching:{iid}")
                sd = next(d for d in drafts if d["type"] == "SCORE_RECORDED")
                st.update_item_doc(iid, {"scores": item["scores"]}, "SCORE_RECORDED", actor, "C-12 export: score",
                                   [pid], sd["idempotency_key"],
                                   extra={"inputs_hash": sd["inputs_hash"], "payload_hash": sd["payload_hash"],
                                          "tool_name": sd["tool_name"]})
                rd = next(d for d in drafts if d["type"] == "RECOMMENDATION_RECORDED")
                st.update_item_doc(iid, {"recommendation": item["recommendation"]}, "RECOMMENDATION_RECORDED", actor,
                                   "C-12 export: recommend", [pid], rd["idempotency_key"])
                st.transition_item(iid, "SCORED", actor, "C-12 export", [pid], f"c12:scored:{iid}")
                st.transition_item(iid, "RECOMMENDED", actor, "C-12 export", [pid], f"c12:recommended:{iid}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--state-commit", default="unknown")
    args = ap.parse_args()
    from mbos_state import migrate

    root = Path(tempfile.mkdtemp(prefix="c12-"))
    sock = Path(tempfile.mkdtemp(prefix="c12-", dir=os.environ.get("XDG_RUNTIME_DIR") or "/tmp"))
    data, port, b = root / "data", int(os.environ.get("C12_PORT", "55471")), pg_bin()
    subprocess.run([b / "initdb", "-D", data, "--auth=trust", "--encoding=UTF8", "--locale=C.UTF-8", "-U", "postgres"],
                   check=True, capture_output=True)
    subprocess.run([b / "pg_ctl", "-D", data, "-l", root / "pg.log", "-w", "start", "-o",
                    f"-p {port} -k {sock} -c listen_addresses='' -c timezone=UTC"], check=True, capture_output=True)
    base = f"host={sock} port={port}"
    try:
        with psycopg.connect(f"{base} dbname=postgres user=postgres", autocommit=True) as c:
            c.execute((args.state_dir / "bootstrap" / "roles.sql").read_text())
            c.execute("CREATE DATABASE mbos OWNER mbos_owner")
        with psycopg.connect(f"{base} dbname=mbos user=postgres", autocommit=True) as c:
            c.execute("CREATE SCHEMA dbos AUTHORIZATION mbos_dbos")
            c.execute("CREATE SCHEMA mbos_ext; CREATE EXTENSION vector WITH SCHEMA mbos_ext; "
                      "GRANT USAGE ON SCHEMA mbos_ext TO agent_read, agent_write, gateway, approver, policy_admin, mbos_owner")
        migrate.migrate(f"{base} dbname=mbos user=postgres", args.state_dir / "migrations", log=lambda *_: None)
        rows = corpus()
        write_through_state_api(f"{base} dbname=mbos user=postgres", rows)
        with psycopg.connect(f"{base} dbname=mbos user=postgres") as conn:
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
    finally:
        subprocess.run([b / "pg_ctl", "-D", data, "-m", "immediate", "-w", "stop"], capture_output=True)
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(sock, ignore_errors=True)


if __name__ == "__main__":
    main()
