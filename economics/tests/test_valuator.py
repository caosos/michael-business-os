"""C-22: Valuator interface + FlipComparablesValuator (A-26 valuation)."""

import copy
import json
import unittest

from helpers import CFG, HERE

from mbos_economics.valuator import FlipComparablesValuator, HomeValuator, VehicleValuator, valuator_for

try:
    from mbos import valuation as A26
except ImportError:  # pragma: no cover - needs agent-01 src on PYTHONPATH
    A26 = None

AS_OF = "2026-10-07T18:00:00Z"
ITEMS = json.loads((HERE / "fixtures" / "agent02" / "items.json").read_text())


def item(category, prefix=""):
    return copy.deepcopy(next(i for i in ITEMS if i["category"] == category and i["normalized"]["title"].startswith(prefix)))


def comps(prices, kind="sold", start=100):
    return [{"kind": kind, "price": p, "sold_date": f"2026-09-{10 + i:02d}", "provenance_id": f"prov_01JC{start + i:022d}",
             "url": f"https://example.invalid/comp/{start + i}"} for i, p in enumerate(prices)]


def check(case, doc):
    if A26 is not None:
        case.assertEqual(A26.errors(doc), [])


MOWER = {"item_id": "itm_mower", "type": "flip", "category": "mower"}


class TestValuator(unittest.TestCase):
    V = FlipComparablesValuator(CFG)

    def test_trailer_sold_comps(self):
        d = self.V.value(item("trailer", "6x12"), {"comps": comps([2000, 2100, 2200, 2300])}, AS_OF)
        self.assertIs(d["not_an_appraisal"], True)
        self.assertEqual(d["subject"]["kind"], "trailer")
        self.assertEqual(d["ranges"]["likely_sale"], {"low": 2075, "high": 2225})
        self.assertEqual(len(d["evidence"]), 4)
        self.assertEqual(d["confidence"], "medium")
        check(self, d)

    def test_confidence_by_sold_count(self):
        it = item("trailer", "6x12")
        self.assertEqual(self.V.value(it, {"comps": comps([2000, 2100, 2200])}, AS_OF)["confidence"], "medium")
        self.assertEqual(self.V.value(it, {"comps": comps([2000, 2100, 2200, 2300, 2400])}, AS_OF)["confidence"], "high")
        self.assertEqual(self.V.value(it, {"comps": comps([2000])}, AS_OF)["confidence"], "low")

    def test_mower_asking_only_is_low_with_list_range(self):
        d = self.V.value(MOWER, {"comps": comps([450, 600, 550], kind="asking")}, AS_OF)
        self.assertEqual(d["subject"]["kind"], "mower")
        self.assertEqual(d["confidence"], "low")
        self.assertEqual(d["ranges"]["suggested_list"], {"low": 450, "high": 600})
        self.assertIsNone(d["ranges"]["likely_sale"])
        check(self, d)

    def test_as_is_and_after_repair(self):
        b = {"comps": comps([900, 1000, 1100]), "as_is_comps": comps([400, 500, 600], start=200),
             "overrides": {"rehab.repair_scope_known": {"value": True, "basis": "FACT", "provenance_id": "prov_x"}}}
        d = self.V.value(MOWER, b, AS_OF)
        self.assertEqual(d["ranges"]["as_is"], {"low": 450, "high": 550})
        self.assertEqual(d["ranges"]["after_repair"], d["ranges"]["likely_sale"])
        check(self, d)

    def test_as_is_above_working_is_dropped(self):
        d = self.V.value(item("trailer", "6x12"), {"comps": comps([1000, 1100, 1200]), "as_is_comps": comps([3000, 3100], start=200)}, AS_OF)
        self.assertIsNone(d["ranges"]["as_is"])
        check(self, d)

    def test_no_comps_is_unknown_with_reason(self):
        d = self.V.value(item("trailer", "6x12"), None, AS_OF)
        self.assertEqual(d["confidence"], "UNKNOWN")
        self.assertTrue(d["reason_unknown"])
        self.assertTrue(all(v is None for v in d["ranges"].values()))
        check(self, d)

    def test_home_and_vehicle_never_a_number(self):
        for cat, V in (("home", HomeValuator()), ("vehicle", VehicleValuator())):
            it = {"item_id": "itm_x", "type": "flip", "category": cat}
            self.assertIsInstance(valuator_for(it), type(V))
            d = V.value(it, {"comps": comps([200000, 210000])}, AS_OF)     # comps are ignored
            self.assertEqual(d["confidence"], "UNKNOWN")
            self.assertTrue(all(v is None for v in d["ranges"].values()))
            self.assertTrue(d["reason_unknown"])
            self.assertIs(d["not_an_appraisal"], True)
            check(self, d)

    def test_unsupported_category_is_unknown(self):
        d = self.V.value(item("assembly"), {"comps": comps([100, 120])}, AS_OF)
        self.assertEqual(d["confidence"], "UNKNOWN")

    def test_deterministic_and_input_untouched(self):
        b = {"comps": comps([2000, 2100, 2200])}
        snap = copy.deepcopy(b)
        it = item("trailer", "6x12")
        self.assertEqual(self.V.value(it, b, AS_OF), self.V.value(it, b, AS_OF))
        self.assertEqual(b, snap)


if __name__ == "__main__":
    unittest.main()
