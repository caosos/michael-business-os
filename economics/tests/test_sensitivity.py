"""C-09: sensitivity report for MICHAEL_DECISIONS #1/#2 (report only; config untouched)."""

import hashlib
import json
import unittest

from helpers import CFG, HERE, case

from mbos_economics.config import CONFIG_DIR
from mbos_economics.sensitivity import PARAMS, render_markdown, sensitivity_report, variant

NARROW = {
    "cash_cap": (PARAMS["cash_cap"][0], PARAMS["cash_cap"][1], [1000, 1500, 3000], (1300, 1500, 50)),
    "flip_target": (PARAMS["flip_target"][0], PARAMS["flip_target"][1], [60, 65, 70], (60, 66, 1)),
    "service_target": (PARAMS["service_target"][0], PARAMS["service_target"][1], [70, 75], (70, 73, 1)),
}


def fp():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(CONFIG_DIR.rglob("*.json"))}


class TestSensitivity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.before = fp()
        cls.cases = {n: case(n) for n in ("trailer_utility", "trailer_utility_at_walkaway", "project_vehicle_civic",
                                          "project_vehicle_truck_over_cap", "equipment_repair_zero_turn")}
        cls.rep = sensitivity_report(cls.cases, CFG, params=NARROW)

    def test_config_untouched(self):
        self.assertEqual(fp(), self.before)
        self.assertEqual(CFG.get("time_value.w_target_flip_per_hour"), 65)

    def test_variants_are_in_memory_and_labelled(self):
        v = variant(CFG, "time_value.w_min_per_hour", 45)
        self.assertEqual(v.get("time_value.w_min_per_hour"), 45)
        self.assertEqual(CFG.get("time_value.w_min_per_hour"), 40)
        self.assertNotEqual(v.hash, CFG.hash)
        self.assertIn("+time_value.w_min_per_hour=45", v.version)

    def test_known_break_evens(self):
        be = self.rep["break_even"]
        self.assertEqual(be["flip_target"]["trailer_utility"], {"MAYBE": [63, 66], "YES": [60, 62]})
        self.assertEqual(be["flip_target"]["trailer_utility_at_walkaway"], {"MAYBE": [66, 66], "YES": [60, 65]})
        self.assertEqual(be["cash_cap"]["project_vehicle_civic"], {"PASS": [1300, 1350], "YES": [1400, 1500]})
        self.assertEqual(be["service_target"]["equipment_repair_zero_turn"], {"MAYBE": [72, 73], "YES": [70, 71]})

    def test_sweeps_and_counts(self):
        sw = self.rep["sweeps"]["cash_cap"]["verdicts"]
        self.assertEqual(sw[3000]["project_vehicle_truck_over_cap"], "YES")
        self.assertEqual(sw[1000]["project_vehicle_civic"], "PASS")
        self.assertEqual(self.rep["counts"]["flip_target"][60], {"YES": 3, "MAYBE": 1, "PASS": 1})   # truck: cash cap

    def test_markdown_marks_changes(self):
        md = render_markdown(self.rep)
        self.assertIn("| trailer_utility | **YES** | MAYBE | MAYBE |", md)
        self.assertIn("65 (default)", md)

    def test_published_report_matches_current_engine(self):
        """docs report must be regenerated whenever the engine/config changes."""
        doc = (HERE.parents[1] / "docs" / "research" / "agent-03-sensitivity-michael-decisions.md").read_text()
        self.assertIn(f"config `{CFG.version}`", doc)
        self.assertIn(CFG.hash, doc)
        self.assertIn("- `trailer_utility`: MAYBE for 63–150; YES for 20–62", doc)


if __name__ == "__main__":
    unittest.main()
