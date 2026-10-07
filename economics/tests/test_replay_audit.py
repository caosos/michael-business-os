"""C-12: replay audit (READY_QUEUE @ agent-01 8c3e4fd).

Acceptance: "Audit over 03's goldens + a lane-D DB export: zero drift, and a planted drift is detected."
The lane-D export (tests/fixtures/lane_d_export/export.json) was written through Agent 04's receipted
StateStore API into a real PostgreSQL 16 cluster and read back through its views (see its _note).
"""

import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from helpers import HERE

from mbos_economics.config import CONFIG_DIR
from mbos_economics.replay_audit import audit, load_scored_items

EXPORT = HERE / "fixtures" / "lane_d_export" / "export.json"
D = json.loads(EXPORT.read_text())
GOLD = [json.loads(p.read_text()) for p in sorted((HERE.parent / "examples").glob("*.scored.json"))]
GOLD_ITEMS = [g["item"] for g in GOLD]
GOLD_RCPT = [r for g in GOLD for r in g["receipt_drafts"]]


def kinds(rep):
    return sorted({f["kind"] for r in rep["rows"] for f in r["findings"]})


class TestZeroDrift(unittest.TestCase):
    def test_goldens(self):
        r = audit(GOLD_ITEMS, receipts=GOLD_RCPT)
        self.assertTrue(r["ok"])
        self.assertEqual((r["scorecards_audited"], r["receipts_matched"], r["drift_count"]), (14, 14, 0))

    def test_lane_d_export(self):
        self.assertTrue(D["exported_from"]["verify_chain"]["ok"])
        r = audit(D["items"], receipts=D["receipts"])
        self.assertTrue(r["ok"], [x for x in r["rows"] if x["findings"]])
        self.assertEqual((r["scorecards_audited"], r["receipts_matched"], r["drift_count"], r["engine_change_count"]),
                         (19, 19, 0, 0))

    def test_jsonb_round_trip_really_happened(self):
        """Postgres reordered keys (JSONB), yet every hash reproduces: MBOS-CJSON-1 at work."""
        g = {i["item_id"]: i for i in GOLD_ITEMS}
        it = next(i for i in D["items"] if i["item_id"] in g)
        self.assertNotEqual(list(it["scores"]["scorecard"]), list(g[it["item_id"]]["scores"]["scorecard"]))
        self.assertEqual(it["scores"]["inputs_hash"], g[it["item_id"]]["scores"]["inputs_hash"])


class TestPlantedDrift(unittest.TestCase):
    def one(self, mutate, *, receipts=True, config_dir=CONFIG_DIR):
        items = copy.deepcopy(D["items"])
        mutate(items[0])
        return audit(items, receipts=D["receipts"] if receipts else None, config_dir=config_dir)

    def test_tampered_number(self):
        r = self.one(lambda i: i["scores"]["scorecard"]["derived"].__setitem__("ev_net_profit", 99999))
        self.assertFalse(r["ok"])
        self.assertEqual(kinds(r), ["receipt", "scorecard"])        # replay differs AND the ledger disagrees

    def test_tampered_input(self):
        def m(i):
            blk = i["economics"].get("job") or i["economics"]["acquisition"]
            k = "quoted_revenue" if "quoted_revenue" in blk else "expected_buy_price"
            blk[k] = blk[k] + 1
        r = self.one(m, receipts=False)
        self.assertEqual(kinds(r), ["inputs_hash"])

    def test_tampered_decision(self):
        r = self.one(lambda i: i["scores"]["scorecard"].__setitem__(
            "decision", "YES" if i["scores"]["scorecard"]["decision"] != "YES" else "PASS"), receipts=False)
        self.assertIn("decision", kinds(r))

    def test_missing_receipt(self):
        items = copy.deepcopy(D["items"])
        rc = [x for x in D["receipts"] if x["item_id"] != items[0]["item_id"]]
        r = audit(items, receipts=rc)
        self.assertEqual((r["drift_count"], kinds(r)), (1, ["receipt"]))

    def test_unknown_config_version(self):
        r = self.one(lambda i: i["scores"]["scorecard"].__setitem__("scoring_config_version", "2099.01.0"), receipts=False)
        self.assertIn("config_missing", kinds(r))

    def test_config_edited_without_bump(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            shutil.copytree(CONFIG_DIR, tmp / "config")
            p = tmp / "config" / "scoring-config.json"
            p.write_text(p.read_text().replace('"min_profit_flip": { "value": 150', '"min_profit_flip": { "value": 151'))
            r = audit(D["items"], config_dir=tmp / "config")
            self.assertFalse(r["ok"])
            self.assertEqual(r["drift_count"], 19)
            self.assertEqual(kinds(r), ["config_edited"])
        finally:
            shutil.rmtree(tmp)

    def test_older_engine_disagreement_is_reported_not_drift(self):
        def m(i):
            sc = i["scores"]["scorecard"]
            sc["engine_version"] = "0.0.1"
            sc["decision"] = "YES" if sc["decision"] != "YES" else "PASS"
        r = self.one(m, receipts=False)
        self.assertTrue(r["ok"])
        self.assertEqual((r["engine_change_count"], kinds(r)), (1, ["engine_change"]))


class TestReadOnly(unittest.TestCase):
    def test_nothing_written(self):
        fp = lambda: {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in sorted(CONFIG_DIR.rglob("*.json")) + [EXPORT]}
        before = fp()
        audit(D["items"], receipts=D["receipts"], audited_at="2026-10-08T06:00:00Z")
        self.assertEqual(fp(), before)

    def test_loader_is_select_only(self):
        class Cur:
            def __init__(self): self.sql, self.rows = [], []
            def execute(self, sql, params=None):
                assert sql.lstrip().upper().startswith("SELECT"); self.sql.append(sql)
                self.rows = [(json.dumps(x),) for x in (D["items"] if "v_item_documents" in sql else D["receipts"])]
            def fetchall(self): return self.rows
        class Conn:
            def __init__(self): self.c = Cur()
            def cursor(self): return self.c
        conn = Conn()
        items, receipts = load_scored_items(conn)
        self.assertEqual((len(items), len(receipts)), (19, 19))
        self.assertTrue(all("mbos.v_" in s for s in conn.c.sql))

    def test_cli_exit_codes(self):
        src = str(HERE.parent / "src")
        ok = subprocess.run([sys.executable, "-m", "mbos_economics", "audit", str(EXPORT)], capture_output=True, text=True,
                            env={"PYTHONPATH": src})
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["drift_count"], 0)
        bad = copy.deepcopy(D)
        bad["items"][0]["scores"]["scorecard"]["composite"] = 1
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bad, f)
        try:
            r = subprocess.run([sys.executable, "-m", "mbos_economics", "audit", f.name], capture_output=True, text=True,
                               env={"PYTHONPATH": src})
            self.assertEqual(r.returncode, 1)
        finally:
            Path(f.name).unlink()


if __name__ == "__main__":
    unittest.main()


def spine_style(export: dict) -> dict:
    """Shape of Agent 01's spine_d.record_score receipts (@a910ad9): inputs_hash only, no payload_hash."""
    d = copy.deepcopy(export)
    for rc in d["receipts"]:
        rc.pop("payload_hash", None)
        rc["tool_name"] = "mbos_economics.engine@0.8.1"
    return d


class TestSpineReceipts(unittest.TestCase):
    """C-13: the gate runs over Agent 01's e2e exports, whose receipts bind inputs_hash only."""

    def test_weak_binding_reported_not_failed(self):
        d = spine_style(D)
        r = audit(d["items"], receipts=d["receipts"])
        self.assertTrue(r["ok"])
        self.assertEqual((r["drift_count"], r["weak_receipt_count"], r["receipts_matched"]), (0, 19, 19))

    def test_strict_mode_fails_weak_binding(self):
        d = spine_style(D)
        r = audit(d["items"], receipts=d["receipts"], strict=True)
        self.assertFalse(r["ok"])
        self.assertEqual(r["drift_count"], 19)

    def test_weak_receipt_with_wrong_inputs_hash_is_drift(self):
        d = spine_style(D)
        d["receipts"][0]["inputs_hash"] = "sha256:" + "0" * 64
        r = audit(d["items"], receipts=d["receipts"])
        drifted = [x for x in r["rows"] if any(f["drift"] for f in x["findings"])]
        self.assertEqual(len(drifted), 1)
        self.assertEqual([f["kind"] for f in drifted[0]["findings"]], ["receipt"])
        self.assertEqual(drifted[0]["item_id"], d["receipts"][0]["item_id"])

    def test_spine_fallback_card_is_not_replayed(self):
        """01's adapter writes a minimal card when inputs are missing; the engine never produced it."""
        items = copy.deepcopy(D["items"])
        items[0]["scores"]["scorecard"] = {"scoring_config_version": "2026.10.1", "derived": {}, "sub_scores": {},
                                           "composite": 0, "decision": "MAYBE", "gates": {},
                                           "reasons": ["Economics inputs missing or invalid"]}
        r = audit(items)
        self.assertTrue(r["ok"])
        self.assertEqual((r["not_engine_count"], kinds(r)), (1, ["not_engine_scorecard"]))

    def test_cli_dsn_reads_db_select_only(self):
        import types
        from mbos_economics.__main__ import main

        class Cur:
            def execute(self, sql, params=None):
                assert sql.lstrip().upper().startswith("SELECT")
                self.rows = [(x,) for x in (D["items"] if "v_item_documents" in sql else D["receipts"])]
            def fetchall(self): return self.rows

        class Conn:
            def cursor(self): return Cur()
            def __enter__(self): return self
            def __exit__(self, *a): return False

        fake = types.SimpleNamespace(connect=lambda dsn: Conn())
        saved = sys.modules.get("psycopg")
        sys.modules["psycopg"] = fake
        try:
            import contextlib, io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = main(["audit", "--dsn", "host=x dbname=mbos user=agent_read"])
            self.assertEqual(code, 0)
            out = json.loads(buf.getvalue())
            self.assertEqual((out["scorecards_audited"], out["drift_count"]), (19, 0))
        finally:
            if saved is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = saved
