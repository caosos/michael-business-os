"""C-16: value_add block, a plan plus SOURCED model-specific risks (READY_QUEUE @ agent-01 d2ef52f; ADR-0011 R18).

Acceptance: KB entries cite sources; mbos.card.validate_card clean; no entry says "check compression/spark/fuel".
"""

import copy
import json
import os
import re
import unittest
from datetime import datetime, timezone

import deal_cases as dc
from helpers import CFG, HERE

from mbos_economics.comps_feed import research_step
from mbos_economics.engine import compute
from mbos_economics.inputs import build_engine_input
from mbos_economics.valueadd import build_value_add, load_kb, match_entries

KB = load_kb()
PID_RE = re.compile(r"^prov_[0-9A-HJKMNP-TV-Z]{26}$")
KINDS = {"failure_mode", "expensive_part", "parts_availability", "known_weakness", "resale_demand", "economic"}
# the same patterns the card lints (agent-01 mbos.card.ELEMENTARY_ADVICE), plus a stricter local ban
ELEMENTARY = [re.compile(p, re.I) for p in (
    r"\bcheck (the )?(engine )?compression\b", r"\bcheck (for )?(a )?spark\b", r"\binspect (the )?fuel\b",
    r"\bcheck (the )?(engine )?oil\b", r"\bcheck (the )?(air )?filter\b", r"\bcheck (the )?(spark ?plug|plugs)\b",
    r"\binspect (the )?(belts?|hoses?)\b", r"\bverify (it )?(starts|runs)\b(?! after)", r"\bmake sure (it|the engine) (starts|runs)\b",
    r"\bcheck (the )?battery\b", r"\blook for (any )?(leaks|damage)\b")]
STRICT_BAN = re.compile(r"\b(check|inspect|make sure|verify (it )?(starts|runs)|look for)\b", re.I)


def scored(case, **kw):
    it, comps, prov = case(**kw)
    r = research_step(it, comps, prov, dc.AS_OF, profile=dc.PROFILE)
    assert r["proposed_next_state"] == "SCORED", r["estimate"]
    return r["item"]


def va(item, **kw):
    return build_value_add(item, dc.AS_OF, cfg=CFG, kb=KB, **kw)


CUB, GEN, GEN75, COMP = (scored(dc.recalled_cub_cadet), scored(dc.recalled_generac), scored(dc.generac_gp7500e),
                         scored(dc.campbell_compressor))
MOWER, SAW = scored(dc.zero_turn_mower), scored(dc.concrete_saw)


class TestKnowledgeBase(unittest.TestCase):
    def test_every_entry_is_sourced_to_a_primary_page(self):
        ids = [e["id"] for e in KB["entries"]]
        self.assertEqual(len(ids), len(set(ids)))
        for e in KB["entries"]:
            s = e["source"]
            self.assertRegex(s["url"], r"^https://(www\.cpsc\.gov|www\.dhses\.ny\.gov|recalls-rappels\.canada\.ca)/", e["id"])
            self.assertRegex(s["retrieved"], r"^\d{4}-\d{2}-\d{2}$")
            self.assertIn(e["kind"], KINDS, e["id"])
            self.assertRegex(s["title"], r"recall date [A-Z][a-z]{2} \d{1,2}, \d{4}", e["id"])
        self.assertIn("summary", KB["verification_default"])         # honest about how the pages were read

    def test_no_elementary_advice_anywhere(self):
        for e in KB["entries"]:
            for text in (e["risk"], e.get("plan_hint", "")):
                self.assertEqual([m.group(0) for rx in ELEMENTARY for m in [rx.search(text)] if m], [], e["id"])
                self.assertIsNone(STRICT_BAN.search(text), (e["id"], text))        # stricter than the card's lint

    def test_models_in_match_groups_appear_in_the_risk_text(self):
        """Guards copy/paste drift between the matching tokens and the recall facts shown to Michael."""
        for e in KB["entries"]:
            for g in e["match"]:
                self.assertTrue(any(m.lower() in e["risk"].lower() for m in g["models"]), (e["id"], g))

    def test_kb_rejects_an_unsourced_entry(self):
        import tempfile
        from pathlib import Path
        bad = copy.deepcopy(KB)
        bad["entries"][0]["source"] = {"title": "blog", "url": "http://example.com"}
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "kb.json"
            p.write_text(json.dumps({k: v for k, v in bad.items() if k != "_hash"}))
            with self.assertRaises(ValueError):
                load_kb(p)


class TestMatching(unittest.TestCase):
    def ids(self, category, title, **kw):
        it = {"category": category, "normalized": {"title": title}}
        return [e["id"] for e in match_entries(it, KB, **kw)]

    def test_positive_matches(self):
        self.assertEqual(self.ids("mower", "Cub Cadet RZT SX 17RWCBYN210 zero turn"), ["cub_cadet_rzt_sx_efi_fuel_tank_2018"])
        self.assertEqual(self.ids("generator", "generac gp8000e"), ["generac_gp_carburetor_fuel_leak_2026"])
        self.assertEqual(self.ids("mower", "Cub Cadet ZTX 6 54 in"), ["kawasaki_engines_overheat_2024"])      # hyphen-tolerant
        self.assertEqual(self.ids("mower", "Bobcat ZT6000 zero turn"), ["kawasaki_engines_overheat_2024"])
        self.assertEqual(self.ids("mower", "Husqvarna RZ4623 rider"), ["kohler_courage_seat_switch_2011"])
        self.assertEqual(self.ids("mower", "Troy Bilt Mustang RZT50"), ["kohler_courage_seat_switch_2011"])      # make spelling variant
        self.assertEqual(self.ids("compressor", "Campbell Hausfeld HU200099AV"), ["campbell_hausfeld_hu200099av_overload_2009"])

    def test_make_model_block_can_supply_the_model(self):
        self.assertEqual(self.ids("generator", "portable generator, low hours", make_model="Generac GP6500E"),
                         ["generac_gp_carburetor_fuel_leak_2026"])

    def test_negatives_are_exact(self):
        self.assertEqual(self.ids("generator", "Generac GP7500E 7500 watt"), [])               # verified NOT on the recall
        self.assertEqual(self.ids("generator", "Generac GP65000 something"), [])               # token boundary
        self.assertEqual(self.ids("generator", "Honda GP6500E clone"), [])                      # make required
        self.assertEqual(self.ids("mower", "Rebel zero turn mower"), [])                       # generic word without the make
        self.assertEqual(self.ids("mower", "LTX1046 lawn tractor"), [])                        # make required (Cub Cadet group)
        self.assertEqual(self.ids("mower", "Generac GP6500E"), [])                             # wrong category
        self.assertEqual(self.ids("trailer", "Cub Cadet 17AWCBYS010"), [])                      # wrong category

    def test_unknown_model_yields_nothing(self):
        for it in (MOWER, SAW, GEN75):
            v = va(it)
            self.assertNotIn("model_specific_risks", v["block"])
            self.assertEqual(v["matched"], [])
            self.assertTrue(any("UNKNOWN, not guessed" in o for o in v["omitted"]))


class TestRisks(unittest.TestCase):
    def test_recalled_cub_cadet(self):
        v = va(CUB)
        (r,) = v["block"]["model_specific_risks"]
        self.assertEqual((r["kind"], r["basis"]), ("failure_mode", "FACT"))
        self.assertIn("17AWCBYS010", r["risk"])
        self.assertIn("about 4,900 sold in the U.S.", r["risk"])
        self.assertIn("UNKNOWN", r["risk"])                                  # remedy status is not assumed
        self.assertIn("not verified against the unit", r["risk"])           # listing text is seller-stated
        self.assertIn("https://www.cpsc.gov/Recalls/2019/Cub-Cadet-Recalls-ZeroTurn", r["source"])
        self.assertEqual(r["provenance_id"], v["provenance"]["provenance_id"])
        self.assertRegex(r["provenance_id"], PID_RE)

    def test_generac_recall_and_gp7500e_exclusion(self):
        (r,) = va(GEN)["block"]["model_specific_risks"]
        self.assertIn("Apr 16, 2026", r["risk"])
        self.assertIn("The GP7500E is not on the list", r["risk"])
        self.assertIn("dhses.ny.gov/node/32841", r["source"])
        self.assertNotIn("model_specific_risks", va(GEN75)["block"])

    def test_remedy_wording_matches_the_source(self):
        (r,) = va(COMP)["block"]["model_specific_risks"]
        self.assertIn("full refund at Wal-Mart, not a repair", r["risk"])
        self.assertNotIn("untested", r["risk"])

    def test_risks_survive_without_a_score(self):
        raw, _, _ = dc.recalled_cub_cadet()
        v = va(raw)
        self.assertEqual(len(v["block"]["model_specific_risks"]), 1)
        self.assertNotIn("plan", v["block"])
        self.assertIn("plan: needs a scored flip", v["omitted"][0])


class TestPlan(unittest.TestCase):
    def test_parts_ceiling_is_the_real_break_even(self):
        plan = va(MOWER)["block"]["plan"]
        self.assertEqual(plan["basis"], "INFERENCE")
        self.assertIn("Parts can run up to $509", plan["value"])
        for parts, expect in ((509, True), (510, False)):
            trial = copy.deepcopy(MOWER)
            trial["economics"]["rehab"]["parts_cost"] = parts
            r = compute(build_engine_input(trial), CFG)
            self.assertEqual(all(r["gates"].values()) and r["yes_conditions"]["ev_pph_target_ok"]
                             and r["yes_conditions"]["ev_min_profit_ok"], expect, parts)
        self.assertIn("The trailer run is already costed in ($27 and 1 h).", plan["value"])
        self.assertIn("Sell target is $1,950, the median of 5 sold comparables.", plan["value"])

    def test_plan_names_the_limit_that_actually_binds(self):
        cub = va(CUB)["block"]["plan"]["value"]
        self.assertIn("fails your $800 worst-case loss limit and your $1,500 per-deal cash limit", cub)
        self.assertNotIn("does not clear your $65/h", cub)                  # the wrong limit must not be blamed
        self.assertIn("fails your $40/h floor", va(GEN)["block"]["plan"]["value"])

    def test_plan_hints_come_only_from_matched_sourced_entries(self):
        self.assertIn("Do not budget fuel tank parts until a Cub Cadet dealer confirms", va(CUB)["block"]["plan"]["value"])
        self.assertNotIn("recall", va(MOWER)["block"]["plan"]["value"].lower())

    def test_no_boilerplate_in_any_plan(self):
        for it in (CUB, GEN, GEN75, COMP, MOWER, SAW):
            text = va(it)["block"]["plan"]["value"]
            self.assertIsNone(STRICT_BAN.search(text), text)
            self.assertEqual([m.group(0) for rx in ELEMENTARY for m in [rx.search(text)] if m], [])

    def test_unestimated_diagnosis_is_stated(self):
        self.assertIn("a category estimate; the fault is not diagnosed yet", va(MOWER)["block"]["plan"]["value"])
        known = copy.deepcopy(MOWER)
        known["economics"]["rehab"]["repair_scope_known"] = True
        self.assertNotIn("not diagnosed", va(known)["block"]["plan"]["value"])

    def test_services_get_no_value_add(self):
        from worked_cases import fresh
        import helpers
        svc = fresh("drywall_basement")
        svc["scores"] = {"scorecard_id": "scr_x", "inputs_hash": "sha256:" + "0" * 64, "scorecard": helpers.sc_of(svc)}
        self.assertEqual(va(svc)["block"], {})


class TestDeterminism(unittest.TestCase):
    def test_pure_and_sensitive(self):
        a = va(CUB)
        self.assertEqual(a, va(copy.deepcopy(CUB)))
        kb2 = copy.deepcopy(KB)
        kb2["entries"][0]["risk"] += " "
        kb2["_hash"] = "sha256:" + "1" * 64
        self.assertNotEqual(a["value_add_hash"], build_value_add(CUB, dc.AS_OF, cfg=CFG, kb=kb2)["value_add_hash"])
        self.assertNotEqual(a["value_add_hash"], build_value_add(CUB, "2026-10-08T18:00:00Z", cfg=CFG, kb=KB)["value_add_hash"])


class TestGoldens(unittest.TestCase):
    def test_goldens_reproduce(self):
        files = {p.stem: json.loads(p.read_text()) for p in sorted((HERE.parent / "examples" / "deal_sniffer").glob("value_add_*.json"))}
        self.assertEqual(set(files), {f"value_add_{n}" for n in ("recalled_cub_cadet", "recalled_generac", "generac_gp7500e",
                                                                 "campbell_compressor", "zero_turn_mower", "concrete_saw")})
        cases = {**dc.VALUE_ADD_CASES, "zero_turn_mower": dc.zero_turn_mower, "concrete_saw": dc.concrete_saw}
        for name, make in cases.items():
            v = va(scored(make))
            self.assertEqual(files[f"value_add_{name}"]["block"], v["block"], name)
            self.assertEqual(files[f"value_add_{name}"]["value_add_hash"], v["value_add_hash"], name)


try:
    from mbos.card import build_card, validate_card
    _card_ok = bool(os.environ.get("MBOS_CONTRACTS_DIR"))
except ImportError:  # pragma: no cover
    _card_ok = False


@unittest.skipUnless(_card_ok, "needs agent-01 mbos.card installed and MBOS_CONTRACTS_DIR=<archive>/docs/research/contracts")
class TestCardIntegration(unittest.TestCase):
    def card(self, item):
        v = va(item)
        return build_card(item, [], [], {"value_add": v["block"]}, profile=dc.PROFILE,
                          now=datetime(2026, 10, 7, 18, tzinfo=timezone.utc)), v

    def test_validate_card_is_clean_for_every_case(self):
        for name, it in (("cub", CUB), ("generac", GEN), ("gp7500e", GEN75), ("compressor", COMP), ("mower", MOWER), ("saw", SAW)):
            card, _ = self.card(it)
            self.assertEqual(validate_card(card), [], name)

    def test_card_carries_plan_and_sourced_risks(self):
        card, v = self.card(CUB)
        vp = card["value_add_plan"]
        self.assertEqual(vp["plan"]["basis"], "INFERENCE")
        self.assertEqual(len(vp["model_specific_risks"]), 1)
        r = vp["model_specific_risks"][0]
        self.assertTrue(r["source"].startswith("CPSC:") and "https://www.cpsc.gov" in r["source"])
        self.assertEqual(r["basis"], "FACT")

    def test_no_knowledge_means_unknown_not_a_guess(self):
        card, _ = self.card(SAW)
        self.assertEqual(card["value_add_plan"]["model_specific_risks"], [])
        card2, _ = self.card(dc.zero_turn_mower()[0])              # unscored: no plan either
        self.assertEqual(card2["value_add_plan"]["plan"]["value"], "UNKNOWN")
        self.assertIn("value_add_plan.plan", card2["unknowns"])

    def test_the_card_lint_still_bites(self):
        """Sanity: the card rejects elementary advice, so a clean result above is meaningful."""
        card, _ = self.card(CUB)
        bad = copy.deepcopy(card)
        bad["value_add_plan"]["plan"] = {"value": "Check the compression and look for leaks.", "basis": "RECOMMENDATION"}
        self.assertTrue(any("elementary advice" in e for e in validate_card(bad)))


if __name__ == "__main__":
    unittest.main()


class TestMatchTokensFailClosed(unittest.TestCase):
    """Review of Agent 02's B-16 converter (2026-10-07): bare numbers pass its `model_tokens`, so a '6500 watt' listing of a
    NON-recalled model matched a recall entry. The KB loader must refuse such entries whatever their source."""

    def kb_file(self, entry):
        import tempfile
        from pathlib import Path
        base = {k: v for k, v in copy.deepcopy(KB).items() if k != "_hash"}
        base["entries"] = [entry]
        d = tempfile.mkdtemp()
        p = Path(d) / "kb.json"
        p.write_text(json.dumps(base))
        return p

    def entry(self, makes=("northgate", "northgate power"), models=("NG3500i", "NG7500E")):
        return {"id": "cpsc_fixture", "category": "generator", "match": [{"makes": list(makes), "models": list(models)}],
                "kind": "failure_mode", "risk": "Fixture recall.", "plan_hint": "Ask a dealer.",
                "source": {"title": "CPSC: fixture, recall date Jan 1, 2026", "url": "https://www.cpsc.gov/Recalls/FIXTURE/x",
                           "retrieved": "2026-10-07"}}

    def test_alphanumeric_models_load(self):
        self.assertEqual(len(load_kb(self.kb_file(self.entry()))["entries"]), 1)

    def test_numeric_only_and_short_tokens_are_refused(self):
        for models in (("6500", "8000"), ("2018",), ("NG3500i", "20"), ("12",), ("1-2",)):
            with self.assertRaises(ValueError, msg=models) as cm:
                load_kb(self.kb_file(self.entry(models=models)))
            self.assertIn("could fire on the wrong unit", str(cm.exception))

    def test_a_group_without_makes_or_models_is_refused(self):
        for e in (self.entry(makes=()), self.entry(models=())):
            with self.assertRaises(ValueError):
                load_kb(self.kb_file(e))

    def test_the_false_positive_that_motivated_this(self):
        weak = {"entries": [{"id": "w", "category": "generator", "match": [{"makes": ["northgate"], "models": ["6500"]}]}]}
        listing = {"category": "generator", "normalized": {"title": "Northgate 6500 watt generator (NG6500, not the recalled unit)"}}
        self.assertEqual([e["id"] for e in match_entries(listing, weak)], ["w"])          # the matcher alone cannot tell...
        with self.assertRaises(ValueError):                                              # ...so the loader never lets it in
            load_kb(self.kb_file(self.entry(models=("6500",))))

    def test_shipped_kb_passes_the_rule(self):
        from mbos_economics.valueadd import weak_match_problems
        for e in KB["entries"]:
            self.assertEqual(weak_match_problems(e), [], e["id"])
