"""C-14: LEARN end to end on a real lane-D database.

Acceptance (READY_QUEUE @ agent-01 ca6d056): "Test on a lane-D DB: outcomes -> calibration report ->
proposal draft; nothing applied."

Flow, all in a THROWAWAY PostgreSQL 16 cluster using Agent 04's real schema:
  scored Items (04 StateStore) -> outcomes recorded by Agent 01's spine_d.record_outcome ->
  learn.load_outcomes (SELECT-only views) -> calibrate -> propose_learn_bump -> StateStore.propose_action
  REFUSED (ADR-0009 item 9 pending) -> nothing applied.

Runs only when the environment provides Agent 04's state/ directory, Agent 01's `mbos` package, psycopg,
pgserver and sqlalchemy (see lane_d.available()); otherwise it is skipped, never failed.
"""

import hashlib
import json
import unittest
from pathlib import Path

import lane_d
from helpers import HERE

from mbos_economics.config import CONFIG_DIR
from mbos_economics.estimate import load_priors
from mbos_economics.learn import load_outcomes, propose_learn_bump, verify_proposal
from mbos_economics.replay_audit import audit, load_scored_items

AS_OF = "2026-11-01T12:00:00Z"
GOLD = {p.name.replace(".scored.json", ""): json.loads(p.read_text())
        for p in sorted((HERE.parent / "examples").glob("*.scored.json"))}

_why = lane_d.available()
if _why is None:
    try:
        import sqlalchemy  # noqa: F401
        import mbos.spine_d  # noqa: F401
    except ImportError as e:  # pragma: no cover
        _why = f"{e.name} not installed"


def sa_url(dsn: str) -> str:
    kv = dict(p.split("=", 1) for p in dsn.split())
    return f"postgresql+psycopg://{kv['user']}@/{kv['dbname']}?host={kv['host']}&port={kv['port']}"


def fp() -> dict:
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(CONFIG_DIR.rglob("*.json"))}


@unittest.skipIf(_why is not None, f"lane-D environment unavailable: {_why}")
class TestLearnOnLaneD(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = lane_d.cluster()
        cls.dsn = cls._ctx.__enter__()
        names = ("trailer_utility", "trailer_utility_at_walkaway")
        lane_d.write_scored(cls.dsn, [(GOLD[n]["item"], GOLD[n]["provenance"], GOLD[n]["receipt_drafts"]) for n in names])
        cls.ids = [GOLD[n]["item"]["item_id"] for n in names]
        import sqlalchemy as sa
        from mbos import spine_d
        cls.engine = sa.create_engine(sa_url(cls.dsn))
        with cls.engine.begin() as c:
            for iid, repaired, labor in ((cls.ids[0], 0, 6.0), (cls.ids[1], 1, 5.0)):
                spine_d.record_outcome(
                    c, iid, "flip_repair_failed" if not repaired else "flip_sold",
                    predicted_vs_actual=[{"field": "rehab.repair_success_prob", "predicted": 0.95, "actual": repaired},
                                         {"field": "rehab.labor_hours", "predicted": 4, "actual": labor}],
                    realized={"revenue": 0 if not repaired else 1050, "total_cost": 520, "net_profit": -520 if not repaired else 530,
                              "hours": 8, "days_to_cash": 12},
                    notes="C-14 test outcome (fixture)", recorded_by="michael", channel="test")

    @classmethod
    def tearDownClass(cls):
        cls.engine.dispose()
        cls._ctx.__exit__(None, None, None)

    def connect(self):
        import psycopg
        return psycopg.connect(self.dsn)

    def test_end_to_end_proposal_refused_nothing_applied(self):
        import psycopg
        from mbos_state.store import Actor, StateStore

        before = fp()
        with self.connect() as conn:
            outcomes, meta = load_outcomes(conn)                     # SELECT-only views
        self.assertEqual(len(outcomes), 2)
        self.assertEqual({o["item_id"] for o in outcomes}, set(self.ids))
        self.assertTrue(all(o["provenance_ids"] and o["scorecard_id"] for o in outcomes))   # spine linked the scorecard

        priors = load_priors()
        out = propose_learn_bump(outcomes, meta, priors, AS_OF)
        rep = out["report"]["fields"]
        self.assertEqual(rep["rehab.repair_success_prob"]["n"], 2)
        self.assertEqual(out["report"]["fields"]["rehab.labor_hours"]["groups"]["flip/trailer/used"]["n"], 2)
        prop = out["proposal"]
        self.assertIsNotNone(prop, "two outcomes must produce a proposal")
        diff = {d["path"]: (d["from"], d["to"]) for d in prop["diff"]}
        self.assertEqual(diff["flip.trailer.repair_success_prob.used"], (0.95, 0.875))
        self.assertEqual(diff["flip.trailer.labor_hours.used"], (4, 4.25))
        areq = prop["action_request"]
        self.assertEqual((areq["capability"], areq["tier"]), ("config.scoring.bump", 0))
        self.assertTrue(verify_proposal(areq))
        self.assertEqual(set(out["provenance"]["derived_from"]), {p for o in outcomes for p in o["provenance_ids"]})

        # The writer persists the LEARN provenance first (a proposal must cite provenance that exists)...
        with self.connect() as conn:
            st = StateStore(conn)
            with st.transaction():
                st.record_provenance(**out["provenance"])
        with self.connect() as conn:
            n_areq = conn.execute("SELECT count(*) FROM mbos.action_requests").fetchone()[0]
            n_prop = conn.execute("SELECT count(*) FROM mbos.receipts WHERE type = 'ACTION_PROPOSED'").fetchone()[0]
        # ...and only then does the lane-D store REFUSE the draft (no item_id, no config category)
        # until ADR-0009 item 9 lands.
        with self.connect() as conn:
            st = StateStore(conn)
            with self.assertRaises(psycopg.Error) as cm:
                with st.transaction():
                    st.propose_action(areq, Actor("agent", "agent-03-economics"), "LEARN: scoring config bump",
                                      areq["idempotency_key"])
        reason = str(cm.exception)
        self.assertIn('null value in column "item_id"', reason)    # the exact gap ADR-0009 item 9 closes
        self.assertNotIn("unknown provenance", reason)       # the provenance is fine; the CONTRACT is what refuses
        with self.connect() as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM mbos.action_requests").fetchone()[0], n_areq)
            self.assertEqual(conn.execute(
                "SELECT count(*) FROM mbos.receipts WHERE type = 'ACTION_PROPOSED'").fetchone()[0], n_prop)
            self.assertEqual(conn.execute("SELECT count(*) FROM mbos.action_requests "
                                          "WHERE capability = 'config.scoring.bump'").fetchone()[0], 0)
            ok, checked = conn.execute("SELECT ok, receipts_checked FROM mbos.verify_chain()").fetchone()[:2]
        self.assertTrue(ok)
        self.assertGreater(checked, 0)

        # nothing applied: config and priors files are byte-identical, version unchanged
        self.assertEqual(fp(), before)
        self.assertEqual(load_priors().version, priors.version)

    def test_release_gate_audit_strict_clean_on_same_database(self):
        with self.connect() as conn:
            items, receipts = load_scored_items(conn)
        rep = audit(items, receipts=receipts, strict=True)
        self.assertTrue(rep["ok"], [r for r in rep["rows"] if r["findings"]])
        self.assertEqual((rep["scorecards_audited"], rep["receipts_matched"], rep["weak_receipt_count"]), (2, 2, 0))


if __name__ == "__main__":
    unittest.main()
