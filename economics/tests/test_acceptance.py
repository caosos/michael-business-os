"""Acceptance suite C (integration doc §8): AT-1..AT-21 (AT-14 corrected for C14), C22, C23."""

import copy
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from helpers import CFG, case, run, sc_of
from worked_cases import ALL_CASES, FLIP_CASES, SCORED_AT

from mbos_economics.comps import aggregate_sold_comps
from mbos_economics.config import CONFIG_DIR, dump_config, load_config, load_config_file
from mbos_economics.engine import compute, score_item
from mbos_economics.inputs import build_engine_input
from mbos_economics.learn import brier, mape, propose_config_bump, shrink_toward_base_rate
from mbos_economics.replay import replay_item

RANK = {"PASS": 0, "MAYBE": 1, "YES": 2}


def scored(name):
    it = case(name)
    out = run(it)
    it["scores"], it["recommendation"] = out["scores"], out["recommendation"]
    return it


def core(item, cfg=CFG):
    return compute(build_engine_input(item), cfg)


# ------------------------------------------------------------------ 18.1 reconstructability

class AT01_Replay(unittest.TestCase):
    def test_replay_every_case(self):
        for name in ALL_CASES:
            with self.subTest(name):
                r = replay_item(scored(name))
                self.assertTrue(r["match"], r["diffs"])

    def test_composite_by_hand(self):
        for name in ALL_CASES:
            sc = sc_of(case(name))
            key = {"ev": "ev_score", "pph": "pph_score", "roi": "roi_score", "ttc": "ttc_score",
                   "risk": "risk_score", "conf": "conf_score", "skill": "skill_score", "scarcity": "scarcity_score"}
            by_hand = sum(sc["weights_used"][k] * sc["sub_scores"][v] for k, v in key.items())
            self.assertAlmostEqual(by_hand, sc["composite"], delta=0.01, msg=name)


class AT02_BasisTags(unittest.TestCase):
    """Config side: every scalar constant carries a basis tag. (Item-side tagging of
    estimates is Agent 02's normalization contract; see AGENT_STATUS UNKNOWNs.)"""

    def test_config_leaves_tagged(self):
        tags = {"FACT", "INFER", "REC", "UNK"}

        def walk(node, path, inherited):
            if isinstance(node, dict):
                basis = node.get("basis", inherited)
                if "value" in node:
                    self.assertIn(node.get("basis"), tags, path)
                    return
                if any(isinstance(v, Decimal) for v in node.values()):
                    self.assertIn(basis, tags, path)
                for k, v in node.items():
                    if not k.startswith("_") and k not in ("basis", "note", "source"):
                        walk(v, f"{path}.{k}", basis)
        for k, v in CFG.raw.items():
            if isinstance(v, dict):
                walk(v, k, None)


class AT03_CompsRule(unittest.TestCase):
    def test_trimmed_median(self):
        comps = [{"sold_price": p} for p in (2300, 2450, 2600, 2700, 2900, 5000)]
        agg = aggregate_sold_comps(comps, CFG)
        # trim 1 each side -> 2450, 2600, 2700, 2900 ; median 2650 ; p25 2562.5 ; p75 2750
        self.assertEqual(agg["n_used"], 4)
        self.assertEqual(agg["comp_price_expected"], Decimal("2650.00"))
        self.assertEqual(agg["comp_price_low"], Decimal("2562.50"))
        self.assertEqual(agg["comp_price_high"], Decimal("2750.00"))

    def test_removing_one_comp_moves_only_by_rule(self):
        comps = [{"sold_price": p} for p in (2300, 2450, 2600, 2700, 2900)]
        self.assertEqual(aggregate_sold_comps(comps, CFG)["comp_price_expected"], Decimal("2600.00"))
        self.assertEqual(aggregate_sold_comps(comps[:-1], CFG)["comp_price_expected"], Decimal("2525.00"))

    def test_no_comps_is_unknown(self):
        self.assertIsNone(aggregate_sold_comps([], CFG))


# ------------------------------------------------------------------ 18.2 economic correctness

class AT04_LaborNotACashCost(unittest.TestCase):
    def test(self):
        base = case("project_vehicle_civic")
        more = copy.deepcopy(base)
        more["economics"]["rehab"]["labor_hours"] = 20
        a, b = sc_of(base)["derived"], sc_of(more)["derived"]
        self.assertEqual(a["net_profit_deterministic"], b["net_profit_deterministic"])
        self.assertGreater(a["profit_per_hour_deterministic"], b["profit_per_hour_deterministic"])


class AT05_TreeCollapses(unittest.TestCase):
    def test(self):
        for name in FLIP_CASES:
            it = case(name)
            it["economics"]["rehab"]["repair_success_prob"] = 1
            it["economics"]["resale"]["sale_prob"] = 1
            d = sc_of(it)["derived"]
            self.assertEqual(d["ev_net_profit"], d["net_profit_deterministic"], name)


class AT06_UncertaintyNeverRaisesEV(unittest.TestCase):
    def test(self):
        for name in ALL_CASES:
            d = sc_of(case(name))["derived"]
            self.assertLessEqual(d["ev_net_profit"], d["net_profit_deterministic"], name)


class AT07_MaxLoss(unittest.TestCase):
    def test(self):
        for name in ALL_CASES:
            d = sc_of(case(name))["derived"]
            live_neg = [b["value"] for b in d["branches"] if b["prob"] > 0 and b["value"] < 0]
            self.assertEqual(d["max_loss"], -min(live_neg) if live_neg else 0, name)


# ------------------------------------------------------------------ 18.3 monotonicity

class AT08_BuyPriceMonotone(unittest.TestCase):
    def test(self):
        for name in FLIP_CASES:
            it = case(name)
            a0 = it["economics"]["acquisition"]["expected_buy_price"]
            prev = None
            for delta in range(0, 600, 50):
                it["economics"]["acquisition"]["expected_buy_price"] = a0 + delta
                c = core(it)
                if prev:
                    self.assertLessEqual(c["composite"], prev["composite"], (name, delta))
                    self.assertLessEqual(RANK[c["decision"]], RANK[prev["decision"]], (name, delta))
                prev = c


class AT09_DistanceMonotone(unittest.TestCase):
    def test(self):
        for name in ALL_CASES:
            base = case(name)
            prev = None
            for extra in (0, 10, 40, 80, 150):
                it = copy.deepcopy(base)
                it["normalized"]["location"]["road_miles_one_way"] += extra
                for t in it["economics"]["logistics"]["trips"]:
                    t["round_trip_miles"] += 2 * extra
                c = core(it)
                if prev:
                    self.assertLessEqual(c["composite"], prev["composite"], (name, extra))
                    self.assertLessEqual(c["derived"]["profit_per_hour_deterministic"],
                                         prev["derived"]["profit_per_hour_deterministic"], (name, extra))
                    self.assertLessEqual(RANK[c["decision"]], RANK[prev["decision"]], (name, extra))
                prev = c


class AT10_ProbabilityMonotone(unittest.TestCase):
    def test(self):
        for name in FLIP_CASES:
            for field, block in (("repair_success_prob", "rehab"), ("sale_prob", "resale")):
                it = case(name)
                prev = None
                for p in (0.1, 0.3, 0.5, 0.7, 0.9, 1):
                    it["economics"][block][field] = p
                    ev = core(it)["derived"]["ev_net_profit"]
                    if prev is not None:
                        self.assertGreaterEqual(ev, prev, (name, field, p))
                    prev = ev


class AT11_EvidenceMonotone(unittest.TestCase):
    def test_adding_evidence_never_lowers_confidence(self):
        for name in ALL_CASES:
            base = core(case(name))
            lane = base["lane"]
            for k in CFG.get(f"evidence_search.{lane}_order"):
                it = case(name)
                ev = it["economics"].setdefault("estimates_meta", {}).setdefault("evidence", {})
                ev[k] = True
                if k == "three_sold_comps":
                    ev.pop(k)
                    ev["sold_comps_count"] = 3
                c = core(it)
                self.assertGreaterEqual(c["derived"]["confidence"], base["derived"]["confidence"], (name, k))

    def test_low_confidence_only_downgrades(self):
        for name in ALL_CASES:
            it = case(name)
            before = core(it)
            meta = it["economics"].setdefault("estimates_meta", {})
            meta["evidence"] = {}
            if it["type"] == "flip":
                it["economics"]["rehab"]["repair_scope_known"] = False
                it["economics"]["resale"].pop("comp_price_low", None)
                meta.pop("comps", None)
            after = core(it)
            self.assertLess(after["derived"]["confidence"], 0.6, name)
            self.assertLessEqual(RANK[after["decision"]], RANK[before["decision"]], name)
            self.assertNotEqual(after["decision"], "YES", name)


# ------------------------------------------------------------------ 18.4 gates & decisions

class AT12_GatesForcePass(unittest.TestCase):
    def assert_pass_on(self, item, gate):
        c = core(item)
        self.assertEqual(c["decision"], "PASS")
        self.assertFalse(c["gates"][gate])

    def test_license(self):
        self.assert_pass_on(case("smart_home_needs_new_circuit"), "license_ok")

    def test_explicit_license_flag(self):
        it = case("drywall_basement")
        it["economics"]["job"]["requires_license_he_lacks"] = True
        self.assert_pass_on(it, "license_ok")

    def test_max_loss(self):
        it = case("project_vehicle_civic")
        it["economics"]["downside"]["salvage_if_repair_fails"] = 0      # B3 = -1145.89
        self.assert_pass_on(it, "max_loss_ok")

    def test_skill_floor(self):
        it = case("project_vehicle_civic")
        it["economics"]["rehab"]["required_skills"] = ["transmission_rebuild", "auto_body", "upholstery"]
        self.assert_pass_on(it, "skill_ok")

    def test_ev_not_positive(self):
        it = case("trailer_utility")
        it["economics"]["resale"]["target_sell_price"] = 520
        it["economics"]["downside"].update({"salvage_if_unsold": 400, "salvage_if_repair_fails": 200})
        self.assert_pass_on(it, "ev_positive")

    def test_gate_beats_high_composite(self):
        c = core(case("project_vehicle_truck_over_cap"))
        self.assertGreater(c["composite"], 60)
        self.assertEqual(c["decision"], "PASS")


class AT13_NoYesWithoutConfidence(unittest.TestCase):
    def test(self):
        it = case("project_vehicle_civic")
        ev = it["economics"]["estimates_meta"]["evidence"]
        for k in ("condition_verified", "seller_screened", "demand_evidence"):
            ev.pop(k)
        out = run(it)["scores"]["scorecard"]
        # .93 - .20 condition - .08 seller - .10 demand = .55
        self.assertEqual(out["derived"]["confidence"], 0.55)
        self.assertEqual(out["decision"], "MAYBE")
        self.assertEqual([k for k, v in out["yes_conditions"].items() if not v], ["confidence_ok"])
        # cheapest first: a phone screen (+.08 -> .63) is enough
        self.assertEqual(out["cheapest_decisive_evidence"], "seller_screened -> YES")


class AT14_WorkedExamplesCorrected(unittest.TestCase):
    """C14 fix. Round one asserted Trailer=YES+ALERT at EV $62/h, contradicting its own §12.4
    YES rule. The rule is kept; the expectations below are what the rule produces."""

    EXPECT = {
        "trailer_utility": ("MAYBE", False),            # EV $62.02/h < $65; walk-away $227
        "trailer_utility_at_walkaway": ("YES", True),   # same trailer bought at $225
        "mower_no_start": ("PASS", False),              # det. $39.84/h < $40 floor
        "mower_compression_confirmed": ("PASS", False),
        "generator_far": ("PASS", False),               # distance ratio gate
        "project_vehicle_civic": ("YES", False),
        "project_vehicle_truck_over_cap": ("PASS", False),
        "drywall_basement": ("YES", False),
        "smart_home_install": ("YES", True),
        "smart_home_needs_new_circuit": ("PASS", False),
        "equipment_repair_zero_turn": ("MAYBE", False),
        "trailer_enclosed_coordinator": ("PASS", False),
        "drywall_patch_coordinator": ("MAYBE", False),
        "welder_estimated_from_comps": ("PASS", False),   # C-06 golden: floor PASS on prior repair costs
    }

    def test(self):
        self.assertEqual(set(self.EXPECT), set(ALL_CASES))
        for name, (verdict, alert) in self.EXPECT.items():
            sc = sc_of(case(name))
            self.assertEqual((sc["decision"], sc["alert"]), (verdict, alert), name)

    def test_yes_requires_target(self):
        for name in ALL_CASES:
            sc = sc_of(case(name))
            if sc["decision"] == "YES":
                target = 65 if sc["lane"] == "flip" else 75
                self.assertGreaterEqual(sc["derived"]["ev_profit_per_hour"], target, name)


class AT15_NoAlertWhenStale(unittest.TestCase):
    def test(self):
        it = case("trailer_utility_at_walkaway")
        it["economics"]["acquisition"]["listing_age_hours"] = 72
        it["economics"]["resale"]["active_comparable_listings"] = 12   # 6 listings = tightness .70 = perishable
        sc = sc_of(it)
        self.assertEqual(sc["decision"], "YES")
        self.assertFalse(sc["alert"])
        self.assertFalse(sc["alert_checks"]["perishable"])


class AT16_DistanceIsEconomic(unittest.TestCase):
    def test(self):
        sc = sc_of(case("generator_far"))
        self.assertGreater(sc["derived"]["profit_per_hour_deterministic"], 65)
        self.assertFalse(sc["gates"]["distance_ratio_ok"])
        self.assertEqual(sc["decision"], "PASS")


# ------------------------------------------------------------------ 18.5 learning loop

class _TempConfigDir(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        shutil.copytree(CONFIG_DIR, self.tmp / "config")
        self.dir = self.tmp / "config"

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def activate(self, proposal):
        """What the State lane does on Michael's YES: archive current, write new."""
        cur = self.dir / "scoring-config.json"
        shutil.move(cur, self.dir / "history" / f"scoring-config-{proposal['from_version']}.json")
        cur.write_text(dump_config(proposal["config"]))


class AT17_LearnNeverMutatesHistory(_TempConfigDir):
    def test(self):
        old = scored("trailer_utility")
        frozen = copy.deepcopy(old["scores"])
        prop = propose_config_bump(CFG, {"time_value.w_target_flip_per_hour": 60},
                                   "trailers realized plan in 12/12 outcomes", ["outc_01JB0000000000000000000001"],
                                   "2026-11-01T00:00:00Z")
        self.assertEqual(prop["to_version"], "2026.10.2")
        self.assertEqual(prop["action_request_draft"]["tier"], 0)
        self.assertEqual(CFG.get("time_value.w_target_flip_per_hour"), 65)    # proposal writes nothing
        self.activate(prop)
        new_cfg = load_config(config_dir=self.dir)
        self.assertEqual(new_cfg.version, "2026.10.2")
        rescored = score_item(case("trailer_utility"), new_cfg, "2026-11-01T00:00:00Z")["scores"]["scorecard"]
        self.assertEqual(rescored["decision"], "YES")                          # new policy, new verdict
        self.assertEqual(old["scores"], frozen)                                # old scorecard untouched
        self.assertTrue(replay_item(old, config_dir=self.dir)["match"])        # and still replays (AT-18)

    def test_metrics(self):
        self.assertEqual(brier([(0.9, 1), (0.7, 0), (0.95, 1)]), Decimal("0.1675"))   # (.01 + .49 + .0025) / 3
        self.assertEqual(mape([(1050, 1000), (650, 520)]), Decimal("0.1500"))


class AT18_ConfigEditWithoutBumpIsDetected(_TempConfigDir):
    def test(self):
        old = scored("drywall_basement")
        p = self.dir / "scoring-config.json"
        p.write_text(p.read_text().replace('"min_profit_service": { "value": 100',
                                           '"min_profit_service": { "value": 90'))
        r = replay_item(old, config_dir=self.dir)
        self.assertTrue(any("without a version bump" in n for n in r["notes"]))

    def test_bump_requires_provenance(self):
        with self.assertRaises(ValueError):
            propose_config_bump(CFG, {"time_value.w_min_per_hour": 45}, "x", [], SCORED_AT)


class AT19_CalibrationMoves(unittest.TestCase):
    def test(self):
        # prior p_repair .9 for mowers; outcomes: 6 of 10 repairs succeeded
        post = shrink_toward_base_rate(0.9, 6, 10)
        self.assertEqual(post, Decimal("0.7500"))
        self.assertLess(post, Decimal("0.9"))
        self.assertGreater(post, Decimal("0.6"))


# ------------------------------------------------------------------ 18.6 service-specific

class AT20_ServiceCashAndGoverningMetric(unittest.TestCase):
    def test(self):
        sc = sc_of(case("equipment_repair_zero_turn"))
        d = sc["derived"]
        self.assertEqual(d["cash_tied_up"], max(0, round(d["cost_out"] - d["deposit"], 2)))
        self.assertEqual(sc["weights_used"]["roi"], 0)
        self.assertEqual(sc["decision"], "MAYBE")                  # ROI is huge, $/h governs
        self.assertGreater(d["roi_deterministic"], 20)


class AT21_QuoteCostOnlyWhenCompetitive(unittest.TestCase):
    def test(self):
        won = case("equipment_repair_zero_turn")
        won["economics"]["job"].update({"win_prob": 1, "completion_prob": 1})
        bid = copy.deepcopy(won)
        bid["economics"]["job"]["win_prob"] = 0.5
        dw, db = sc_of(won)["derived"], sc_of(bid)["derived"]
        lost = [b for b in db["branches"] if b["name"] == "lost_bid"][0]
        self.assertEqual(lost["value"], -db["sunk_cash"])
        self.assertEqual(lost["prob"], 0.5)
        self.assertEqual([b["prob"] for b in dw["branches"] if b["name"] == "lost_bid"], [0])
        self.assertEqual(dw["ev_net_profit"], dw["net_profit_deterministic"])
        self.assertEqual(db["ev_net_profit"], round(0.5 * dw["net_profit_deterministic"] - 0.5 * db["sunk_cash"], 2))


# ------------------------------------------------------------------ C22 / C23

class C22_InputsHash(unittest.TestCase):
    def test_present_and_stable(self):
        for name in ALL_CASES:
            a, b = run(case(name)), run(case(name))
            self.assertRegex(a["scores"]["inputs_hash"], r"^sha256:[0-9a-f]{64}$")
            self.assertRegex(a["scores"]["scorecard_id"], r"^scr_[0-9A-HJKMNP-TV-Z]{26}$")
            self.assertEqual(a, b, name)

    def test_formatting_does_not_change_hash(self):
        a = case("drywall_basement")
        b = case("drywall_basement")
        b["economics"]["job"]["quoted_revenue"] = Decimal("1850.00")
        b["economics"]["job"]["win_prob"] = 1.0
        self.assertEqual(run(a)["scores"]["inputs_hash"], run(b)["scores"]["inputs_hash"])

    def test_any_input_change_changes_hash(self):
        a = case("drywall_basement")
        b = case("drywall_basement")
        b["economics"]["job"]["labor_hours"] = 14.5
        self.assertNotEqual(run(a)["scores"]["inputs_hash"], run(b)["scores"]["inputs_hash"])
        c = case("drywall_basement")
        c["normalized"]["location"]["road_miles_one_way"] = 9
        self.assertNotEqual(run(a)["scores"]["inputs_hash"], run(c)["scores"]["inputs_hash"])

    def test_tampered_scorecard_fails_replay(self):
        it = scored("smart_home_install")
        it["scores"]["scorecard"]["composite"] = 99
        r = replay_item(it)
        self.assertFalse(r["match"])
        self.assertIn("composite", r["diffs"][0])

    def test_tampered_input_fails_replay(self):
        it = scored("smart_home_install")
        it["economics"]["job"]["quoted_revenue"] = 950
        r = replay_item(it)
        self.assertFalse(r["inputs_hash_match"])


class C23_CoordinatorExamples(unittest.TestCase):
    """Agent 01's illustrative examples, scored for real. Drywall agrees (MAYBE). The trailer
    example's recorded YES/61.6 was illustrative and does not reproduce: with no evidence block
    its confidence is 0.20 and EV $/h is $44.95. Reported to Agent 01 with a corrected example."""

    def test_drywall_agrees(self):
        self.assertEqual(sc_of(case("drywall_patch_coordinator"))["decision"], "MAYBE")

    def test_trailer_corrected(self):
        sc = sc_of(case("trailer_enclosed_coordinator"))
        self.assertEqual(sc["decision"], "PASS")
        self.assertEqual(sc["derived"]["confidence"], 0.2)
        self.assertEqual(sc["derived"]["ev_profit_per_hour"], 44.95)
        self.assertTrue(any("2026.10.0" in r for r in sc["reasons"]))   # stale estimates version flagged


if __name__ == "__main__":
    unittest.main()
