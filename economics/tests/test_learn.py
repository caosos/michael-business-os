"""C-07: LEARN on Agent 04's outcome store (READY_QUEUE @ agent-01 aa88e7a).

Acceptance: "Two outcomes -> a bump proposal with provenance; nothing applied."
"""

import copy
import hashlib
import json
import unittest
from decimal import Decimal

from helpers import HERE

from mbos_economics.config import CONFIG_DIR
from mbos_economics.estimate import load_priors
from mbos_economics.learn import (calibrate, item_meta_from_docs, load_outcomes, propose_learn_bump,
                                  verify_proposal)

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    Draft202012Validator = None

AS_OF = "2026-11-01T12:00:00Z"
ITEMS = json.loads((HERE / "fixtures" / "agent02" / "items.json").read_text())
TRAILERS = sorted([i for i in ITEMS if i["category"] == "trailer" and i["normalized"]["condition"] == "used"
                   and i["normalized"]["price"]["type"] == "fixed"], key=lambda i: i["item_id"])
META = item_meta_from_docs(ITEMS)


def outcome(n: int, item: dict, repaired: int, labor_actual: float, kind: str) -> dict:
    return {
        "outcome_id": f"outc_01JG{n:022d}", "item_id": item["item_id"], "observed_at": f"2026-10-2{n}T18:00:00Z",
        "kind": kind,
        "predicted_vs_actual": [
            {"field": "rehab.repair_success_prob", "predicted": 0.95, "actual": repaired},
            {"field": "rehab.labor_hours", "predicted": 4, "actual": labor_actual},
            {"field": "resale.target_sell_price", "predicted": 2100, "actual": 1950},
        ],
        "realized": {"revenue": 1950, "total_cost": 1490, "net_profit": 460, "hours": 13, "days_to_cash": 19},
        "provenance_ids": [f"prov_01JG{n:022d}"],
    }


TWO = [outcome(1, TRAILERS[0], 0, 6, "flip_repair_failed"), outcome(2, TRAILERS[1], 1, 5, "flip_sold")]


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class TestAcceptanceC07(unittest.TestCase):
    def setUp(self):
        self.priors_file = CONFIG_DIR / "estimation-priors.json"
        self.before = _sha(self.priors_file)
        self.priors = load_priors()
        self.out = propose_learn_bump(TWO, META, self.priors, AS_OF)

    def test_two_outcomes_produce_a_proposal(self):
        p = self.out["proposal"]
        self.assertIsNotNone(p)
        y, m, n = self.priors.version.split(".")
        self.assertEqual((p["from_version"], p["to_version"]), (self.priors.version, f"{y}.{m}.{int(n) + 1}"))
        diff = {d["path"]: (d["from"], d["to"]) for d in p["diff"]}
        # repair: (10 x 0.95 + 1 success) / (10 + 2) = 0.875
        self.assertEqual(diff["flip.trailer.repair_success_prob.used"], (0.95, 0.875))
        # labor: bias = mean(6/4, 5/4) - 1 = 0.375; ratio = (10 + 2 x 1.375) / 12 = 1.0625; 4 x 1.0625 = 4.25
        self.assertEqual(diff["flip.trailer.labor_hours.used"], (4, 4.25))
        self.assertEqual(len(diff), 2)

    def test_tier0_action_request_with_provenance(self):
        a = self.out["proposal"]["action_request"]
        self.assertEqual((a["capability"], a["tier"], a["status"], a["reversibility"]),
                         ("config.scoring.bump", 0, "drafted", "reversible"))
        self.assertEqual(a["provenance_ids"], [self.out["provenance"]["provenance_id"]])
        self.assertEqual(sorted(self.out["provenance"]["derived_from"]), ["prov_01JG" + f"{n:022d}" for n in (1, 2)])
        self.assertEqual(a["payload"]["evidence_refs"], [o["outcome_id"] for o in TWO])
        self.assertTrue(verify_proposal(a))
        self.assertEqual(a["payload"]["document"]["priors_version"], self.out["proposal"]["to_version"])
        self.assertEqual(a["payload"]["document"]["flip"]["trailer"]["repair_success_prob"]["used"], 0.875)

    def test_nothing_applied(self):
        self.assertEqual(_sha(self.priors_file), self.before)
        self.assertEqual(load_priors().version, self.priors.version)
        self.assertFalse((CONFIG_DIR / "history" / f"estimation-priors-{self.priors.version}.json").exists())
        self.assertEqual(self.priors.get("flip")["trailer"]["repair_success_prob"]["used"], Decimal("0.95"))

    def test_tampered_payload_fails_verification(self):
        a = copy.deepcopy(self.out["proposal"]["action_request"])
        a["payload"]["document"]["flip"]["trailer"]["repair_success_prob"]["used"] = 0.99
        self.assertFalse(verify_proposal(a))

    def test_deterministic(self):
        again = propose_learn_bump(copy.deepcopy(list(reversed(TWO))), META, load_priors(), AS_OF)
        self.assertEqual(again["proposal"]["action_request"], self.out["proposal"]["action_request"])

    @unittest.skipIf(Draft202012Validator is None, "jsonschema not installed")
    def test_contract_conformance_except_documented_gaps(self):
        schemas = {n: json.loads((HERE / "contracts" / f"{n}.schema.json").read_text())
                   for n in ("action-request", "provenance", "outcome")}
        for o in TWO:
            self.assertEqual(list(Draft202012Validator(schemas["outcome"]).iter_errors(o)), [])
        self.assertEqual(list(Draft202012Validator(schemas["provenance"]).iter_errors(self.out["provenance"])), [])
        a = self.out["proposal"]["action_request"]
        errs = sorted(e.message for e in Draft202012Validator(schemas["action-request"]).iter_errors(a))
        self.assertEqual(len(errs), 2, errs)
        self.assertTrue(any("'item_id' is a required property" in e for e in errs))
        self.assertTrue(any("'config_change' is not one of" in e for e in errs))
        self.assertEqual(len(self.out["proposal"]["contract_gaps"]), 2)


class TestCalibration(unittest.TestCase):
    def test_metrics(self):
        r = calibrate(TWO, META)["fields"]
        self.assertEqual(r["rehab.repair_success_prob"]["brier"], Decimal("0.4525"))   # (.95^2 + .05^2) / 2
        self.assertEqual(r["rehab.labor_hours"]["mape"], Decimal("0.2667"))            # (2/6 + 1/5) / 2
        self.assertEqual(r["rehab.labor_hours"]["bias"], Decimal("0.3750"))
        self.assertEqual(r["resale.target_sell_price"]["bias"], Decimal("-0.0714"))    # 1950/2100 - 1

    def test_one_outcome_is_report_only(self):
        out = propose_learn_bump(TWO[:1], META, load_priors(), AS_OF)
        self.assertIsNone(out["proposal"])
        self.assertEqual(out["report"]["fields"]["rehab.labor_hours"]["n"], 1)

    def test_unknown_items_and_bad_actuals_skipped(self):
        stray = copy.deepcopy(TWO[0]); stray["item_id"] = "itm_01JG0000000000000000000099"
        weird = copy.deepcopy(TWO[1]); weird["predicted_vs_actual"][0]["actual"] = 0.5
        r = calibrate([stray, weird], META)
        self.assertEqual(r["outcomes_used"], [weird["outcome_id"]])
        self.assertNotIn("rehab.repair_success_prob", r["fields"])


class _FakeCursor:
    def __init__(self, outcomes, items):
        self.o, self.i, self.rows, self.sql = outcomes, items, [], []

    def execute(self, sql, params=None):
        assert sql.lstrip().upper().startswith("SELECT"), "LEARN must only read"
        self.sql.append(sql)
        if "v_outcome_documents" in sql:
            self.rows = [(json.dumps(o),) for o in self.o]
        else:
            self.rows = [(i,) for i in self.i if i["item_id"] in params[0]]

    def fetchall(self):
        return self.rows


class _FakeConn:
    def __init__(self, *a):
        self.cur = _FakeCursor(*a)

    def cursor(self):
        return self.cur


class TestStoreReader(unittest.TestCase):
    def test_reads_04_views_select_only(self):
        conn = _FakeConn(TWO, ITEMS)
        outs, meta = load_outcomes(conn)
        self.assertEqual([o["outcome_id"] for o in outs], [o["outcome_id"] for o in TWO])
        self.assertEqual(set(meta), {o["item_id"] for o in TWO})
        self.assertTrue(all("mbos.v_" in s for s in conn.cur.sql))
        self.assertIsNotNone(propose_learn_bump(outs, meta, load_priors(), AS_OF)["proposal"])


if __name__ == "__main__":
    unittest.main()
