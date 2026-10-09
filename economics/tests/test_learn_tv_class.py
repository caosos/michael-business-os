"""C-29 / F-117: a TV (other_asset by category) calibrates against consumer_electronics priors, not the zero
other_asset priors, so a different handling time yields a (still blocked, tier-0) LEARN proposal."""

import hashlib
import unittest

from class_cases import tv_65_inch
from helpers import HERE  # noqa: F401

from mbos_economics.config import CONFIG_DIR
from mbos_economics.estimate import load_priors
from mbos_economics.learn import item_meta_from_docs, propose_learn_bump

AS_OF = "2026-11-01T12:00:00Z"
TV = tv_65_inch()
TV["normalized"]["condition"] = "used"


def outcome(n: int, labor_actual: float) -> dict:
    return {
        "outcome_id": f"outc_01JG{n:022d}", "item_id": TV["item_id"], "observed_at": f"2026-10-2{n}T18:00:00Z",
        "kind": "flip_sold",
        "predicted_vs_actual": [{"field": "rehab.labor_hours", "predicted": 0.25, "actual": labor_actual}],
        "realized": {"revenue": 90, "total_cost": 40, "net_profit": 50, "hours": 1, "days_to_cash": 2},
        "provenance_ids": [f"prov_01JG{n:022d}"],
    }


class TestTvClassLearn(unittest.TestCase):
    def test_tv_groups_as_consumer_electronics(self):
        self.assertEqual(item_meta_from_docs([TV])[TV["item_id"]]["category"], "consumer_electronics")

    def test_longer_handling_time_proposes_bump_without_applying(self):
        f = CONFIG_DIR / "estimation-priors.json"
        before = hashlib.sha256(f.read_bytes()).hexdigest()
        priors = load_priors()
        out = propose_learn_bump([outcome(1, 0.75), outcome(2, 0.75)], item_meta_from_docs([TV], priors), priors, AS_OF)
        diff = {d["path"]: (d["from"], d["to"]) for d in out["proposal"]["diff"]}
        self.assertIn("flip.consumer_electronics.labor_hours.used", diff)
        old, new = diff["flip.consumer_electronics.labor_hours.used"]
        self.assertEqual(old, 0.25)
        self.assertGreater(new, old)
        a = out["proposal"]["action_request"]
        self.assertEqual((a["tier"], a["status"]), (0, "drafted"))
        self.assertEqual(hashlib.sha256(f.read_bytes()).hexdigest(), before)
