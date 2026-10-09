"""C-28 / F-32: Michael's quote (`quote:amount_usd`, human provenance) replaces the default quote as human-attested revenue."""

import copy
import unittest

from test_coverage import AS_OF, item, P
from mbos_economics.engine import score_item
from mbos_economics.estimate import estimate_item
from mbos_economics.inputs import quote_override
from helpers import CFG


def entry(field, value, **kw):
    r = {"finding": f"Michael: {field}", "field": field, "value": value, "basis": "FACT", "provenance_id": P(41),
         "entered_by": "michael"}
    r.update(kw)
    return r


def lead(quote=None, attested=True):
    it = item("service", "drywall_repair")
    it["research"] = ([{"finding": f"Michael confirms {k}", "field": f"attestation:{k}", "basis": "FACT",
                        "provenance_id": P(50 + i)} for i, k in enumerate(["scope_verified", "customer_screened"])]
                      if attested else [])
    if quote is not None:
        it["research"].append(entry("quote:amount_usd", quote))
    return it


def run(it):
    est = estimate_item(it, None, AS_OF)
    it = copy.deepcopy(it)
    for k, v in est["item_patch"].items():
        it[k] = it.get(k, []) + v if k == "research" else v
    return est, score_item(it, CFG, AS_OF)["scores"]["scorecard"]


class TestServiceQuote(unittest.TestCase):
    def test_700_reaches_yes_500_stays_maybe(self):
        self.assertEqual(run(lead(700))[1]["decision"], "YES")
        self.assertEqual(run(lead(500))[1]["decision"], "MAYBE")

    def test_quote_replaces_default_and_is_human_attested(self):
        est, _ = run(lead(700))
        self.assertEqual(est["item_patch"]["economics"]["job"]["quoted_revenue"], 700)
        a = {x["field"]: x for x in est["item_patch"]["economics"]["estimates_meta"]["assumptions"]}["economics.job.quoted_revenue"]
        self.assertIn("human-attested", a["note"])
        self.assertIn(P(41), est["provenance"]["derived_from"])
        self.assertNotEqual(run(lead())[0]["item_patch"]["economics"]["job"]["quoted_revenue"], 700)

    def test_suggestion_still_offered_below_the_bar(self):
        sc = run(lead(500))[1]
        self.assertIsNotNone(sc.get("min_quote_for_yes"))
        self.assertGreater(sc["min_quote_for_yes"], 500)

    def test_below_cost_accepted_verdict_follows_numbers(self):
        est, sc = run(lead(100))
        self.assertEqual(est["item_patch"]["economics"]["job"]["quoted_revenue"], 100)
        self.assertEqual(sc["decision"], "PASS")

    def test_invalid_quotes_ignored_and_last_wins(self):
        it = item("service", "drywall_repair")
        for bad in (entry("quote:amount_usd", 0), entry("quote:amount_usd", -5), entry("quote:amount_usd", True),
                    entry("quote:amount_usd", "700"), entry("quote:amount_usd", 700, entered_by=None),
                    entry("quote:amount_usd", 700, provenance_id="x"), entry("quote:amount_usd", 700, basis="UNKNOWN")):
            it["research"] = [bad]
            self.assertEqual(quote_override(it), {})
        it["research"] = [entry("quote:amount_usd", 700), entry("quote:amount_usd", 650)]
        self.assertEqual(quote_override(it)["job.quoted_revenue"]["value"], 650)

    def test_flip_ignores_quote_and_deterministic(self):
        f = item("flip", "trailer")
        f["research"] = [entry("quote:amount_usd", 700)]
        self.assertEqual(quote_override(f), {})
        a, b = estimate_item(lead(700), None, AS_OF), estimate_item(lead(700), None, AS_OF)
        self.assertEqual(a["estimate_hash"], b["estimate_hash"])


if __name__ == "__main__":
    unittest.main()
