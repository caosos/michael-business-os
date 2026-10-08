"""C-27 / F-106: a stored human scope override moves an unknown-category item off scope_override_required."""

import copy
import unittest

from test_coverage import AS_OF, SOLD, item, P
from mbos_economics.estimate import estimate_item
from mbos_economics.inputs import scope_overrides


def rec(path, value, **kw):
    r = {"finding": f"Michael: {path}", "field": f"scope_override:{path}", "value": value, "basis": "INFER",
         "provenance_id": P(40), "entered_by": "michael"}
    r.update(kw)
    return r


def with_scope(it, lane="flip"):
    it = copy.deepcopy(it)
    blk = "rehab" if lane == "flip" else "job"
    mat = ("rehab.parts_cost", 120) if lane == "flip" else ("job.materials_cost", 25)
    it["research"] = [rec(mat[0], mat[1]), rec(f"{blk}.labor_hours", 4), rec(f"{blk}.required_skills", ["repair"])]
    return it


def codes(r):
    return [g["code"] for g in r["gaps"] if g["blocking"]]


class TestScopeOverride(unittest.TestCase):
    def test_unknown_flip_blocked_then_moves(self):
        it = item("flip", "other_asset")
        it["normalized"]["title"] = "mystery gizmo"
        self.assertIn("scope_override_required", codes(estimate_item(it, SOLD, AS_OF)))
        r = estimate_item(with_scope(it), SOLD, AS_OF)
        self.assertEqual(r["status"], "estimated")
        notes = {a["field"]: a for a in r["item_patch"]["economics"]["estimates_meta"]["assumptions"]}
        self.assertEqual(r["item_patch"]["economics"]["rehab"]["parts_cost"], 120)
        self.assertIn("human-attested", notes["economics.rehab.parts_cost"]["note"])
        self.assertIn(P(40), r["provenance"]["derived_from"])

    def test_unknown_service_moves(self):
        it = item("service", "other_service")
        self.assertIn("scope_override_required", codes(estimate_item(it, None, AS_OF)))
        r = estimate_item(with_scope(it, "service"), None, AS_OF)
        self.assertEqual(r["status"], "estimated")
        self.assertEqual(r["item_patch"]["economics"]["job"]["materials_cost"], 25)

    def test_invalid_records_ignored(self):
        it = item("flip", "other_asset")
        it["research"] = [rec("rehab.parts_cost", 120, entered_by=None), rec("rehab.parts_cost", -5),
                          rec("rehab.parts_cost", True), rec("rehab.parts_cost", 9, basis="UNKNOWN"),
                          rec("rehab.parts_cost", 9, provenance_id="x"), rec("rehab.sale_prob", 1),
                          rec("rehab.required_skills", [])]
        self.assertEqual(scope_overrides(it), {})
        self.assertIn("scope_override_required", codes(estimate_item(it, SOLD, AS_OF)))

    def test_last_entry_wins_and_deterministic(self):
        it = with_scope(item("flip", "other_asset"))
        it["research"].append(rec("rehab.parts_cost", 200))
        a, b = estimate_item(it, SOLD, AS_OF), estimate_item(copy.deepcopy(it), SOLD, AS_OF)
        self.assertEqual(a["item_patch"]["economics"]["rehab"]["parts_cost"], 200)
        self.assertEqual(a["estimate_hash"], b["estimate_hash"])


if __name__ == "__main__":
    unittest.main()
