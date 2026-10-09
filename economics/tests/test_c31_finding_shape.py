"""C-31 / F-127 (D-32): readers accept the value and author from `finding` (JSON string) as well as the old extra fields."""

import json
import unittest

from test_c27_scope_override import with_scope
from test_c28_service_quote import lead, run
from test_coverage import AS_OF, SOLD, item, P
from mbos_economics.estimate import estimate_item
from mbos_economics.inputs import quote_override, scope_overrides


def new_entry(field, value, by="michael", basis="FACT", pid=41):
    return {"finding": json.dumps({"value": value, "entered_by": by}, sort_keys=True), "field": field, "basis": basis,
            "provenance_id": P(pid), "source_uri": f"human:{by}"}


def new_lead(q):
    it = lead(None)
    it["research"].append(new_entry("quote:amount_usd", q))
    return it


class TestNewShape(unittest.TestCase):
    def test_quote_700_yes_500_maybe(self):
        self.assertEqual(run(new_lead(700))[1]["decision"], "YES")
        self.assertEqual(run(new_lead(500))[1]["decision"], "MAYBE")

    def test_quote_human_attested_and_same_as_old(self):
        o = quote_override(new_lead(700))["job.quoted_revenue"]
        self.assertEqual((o["value"], o["human_attested"], o["note"]), (700, True, "quote set by michael"))
        self.assertEqual(o, quote_override(lead(700))["job.quoted_revenue"])

    def test_old_shape_still_read(self):
        self.assertEqual(run(lead(700))[1]["decision"], "YES")
        self.assertEqual(run(lead(500))[1]["decision"], "MAYBE")

    def test_author_from_source_uri_when_missing_in_finding(self):
        e = new_entry("quote:amount_usd", 700)
        e["finding"] = json.dumps({"value": 700})
        it = lead(None)
        it["research"].append(e)
        self.assertEqual(quote_override(it)["job.quoted_revenue"]["note"], "quote set by michael")

    def test_bad_new_shape_skipped(self):
        for f in ("not json", json.dumps({"entered_by": "m"}), json.dumps({"value": True, "entered_by": "m"}),
                  json.dumps({"value": 0, "entered_by": "m"})):
            e = new_entry("quote:amount_usd", 1)
            e["finding"] = f
            e.pop("source_uri")
            it = lead(None)
            it["research"].append(e)
            self.assertEqual(quote_override(it), {})

    def test_scope_override_new_shape_matches_old(self):
        old = with_scope(item("flip", "other_asset"))
        new = item("flip", "other_asset")
        new["research"] = [new_entry(f"scope_override:{r['field'].split(':')[1]}", r["value"], basis="INFER", pid=40)
                           for r in old["research"]]
        self.assertEqual(scope_overrides(new), scope_overrides(old))
        self.assertEqual(len(scope_overrides(new)), 3)
