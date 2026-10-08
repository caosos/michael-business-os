"""Determinism, canonicalization, ids, config validation, input refusal."""

import json
import re
import shutil
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from helpers import CFG, case, run

from mbos_economics.canonical import canonical_json, derived_ulid
from mbos_economics.config import CONFIG_DIR, ConfigError, load_config, load_config_file
from mbos_economics.engine import compute, score_item
from mbos_economics.inputs import InputError, build_engine_input


class TestCanonical(unittest.TestCase):
    def test_number_forms_are_equal(self):
        self.assertEqual(canonical_json({"a": 3.2}), canonical_json({"a": Decimal("3.20")}))
        self.assertEqual(canonical_json({"a": 1850}), canonical_json({"a": 1850.0}))
        self.assertEqual(canonical_json({"b": 1, "a": [0.10, -0.0]}), '{"a":[0.1,0],"b":1}')

    def test_strings_stay_strings(self):
        self.assertNotEqual(canonical_json({"a": "3.2"}), canonical_json({"a": 3.2}))


class TestIds(unittest.TestCase):
    def test_shape_and_determinism(self):
        a = derived_ulid("scr", "2026-10-07T12:00:00Z", "seed")
        self.assertRegex(a, r"^scr_[0-9A-HJKMNP-TV-Z]{26}$")
        self.assertEqual(a, derived_ulid("scr", "2026-10-07T12:00:00+00:00", "seed"))
        self.assertNotEqual(a, derived_ulid("scr", "2026-10-07T12:00:00Z", "seed2"))
        later = derived_ulid("scr", "2026-10-07T12:00:01Z", "seed")
        self.assertLess(a, later)                                   # time-ordered like a ULID

    def test_naive_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            derived_ulid("scr", "2026-10-07T12:00:00", "seed")


class TestNoClock(unittest.TestCase):
    def test_only_scored_at_changes(self):
        a = score_item(case("drywall_basement"), CFG, "2026-10-07T12:00:00Z")
        b = score_item(case("drywall_basement"), CFG, "2026-10-08T09:30:00Z")
        self.assertEqual(a["scores"]["inputs_hash"], b["scores"]["inputs_hash"])
        self.assertNotEqual(a["scores"]["scorecard_id"], b["scores"]["scorecard_id"])
        sa, sb = dict(a["scores"]["scorecard"]), dict(b["scores"]["scorecard"])
        sa.pop("computed_at"), sb.pop("computed_at")
        self.assertEqual(sa, sb)

    def test_engine_source_never_reads_clock_or_random(self):
        src = Path(__file__).resolve().parents[1] / "src" / "mbos_economics"
        for p in src.glob("*.py"):
            text = p.read_text()
            for bad in (r"\bdatetime\.now\b", r"\btime\.time\(", r"\bimport random\b", r"\buuid4?\(", r"\bos\.urandom\b"):
                self.assertIsNone(re.search(bad, text), f"{p.name}: {bad}")


class TestInputRefusal(unittest.TestCase):
    def problems(self, item):
        with self.assertRaises(InputError) as cm:
            compute(build_engine_input(item), CFG)
        return cm.exception.problems

    def test_missing_required(self):
        it = case("trailer_utility")
        del it["economics"]["resale"]["sale_prob"]
        self.assertIn("economics.resale.sale_prob is required", self.problems(it))

    def test_string_number_rejected(self):
        it = case("drywall_basement")
        it["economics"]["job"]["quoted_revenue"] = "1850"
        self.assertIn("economics.job.quoted_revenue must be a number", self.problems(it))

    def test_probability_range(self):
        it = case("drywall_basement")
        it["economics"]["job"]["win_prob"] = 1.2
        self.assertIn("economics.job.win_prob must be <= 1", self.problems(it))

    def test_salvage_cannot_beat_sale(self):
        it = case("trailer_utility")
        it["economics"]["downside"]["salvage_if_unsold"] = 1200
        self.assertTrue(any("salvage_if_unsold exceeds net resale" in p for p in self.problems(it)))

    def test_wrong_lane_category(self):
        it = case("trailer_utility")
        it["category"] = "drywall_repair"
        self.assertIn("category 'drywall_repair' is not a flip category", self.problems(it))

    def test_bool_is_not_a_number(self):
        it = case("trailer_utility")
        it["economics"]["acquisition"]["buy_fees"] = True
        self.assertIn("economics.acquisition.buy_fees must be a number", self.problems(it))


class TestConfig(unittest.TestCase):
    def test_round_one_config_not_executable(self):
        with self.assertRaises(ConfigError):
            load_config("2026.10.0")

    def test_current_version(self):
        self.assertEqual(CFG.version, "2026.10.2")
        self.assertEqual(load_config("2026.10.2").hash, CFG.hash)

    def test_coordinator_defaults_are_config(self):
        self.assertEqual(CFG.get("capital_and_risk.risk_capital_per_deal_cap"), 1500)
        self.assertEqual(CFG.get("capital_and_risk.max_loss_cap"), 800)
        self.assertEqual(CFG.get("time_value.w_min_per_hour"), 40)
        self.assertEqual(CFG.get("time_value.w_target_flip_per_hour"), 65)
        self.assertEqual(CFG.get("time_value.w_target_service_per_hour"), 75)

    def test_weights_must_sum_to_one(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            raw = json.loads((CONFIG_DIR / "scoring-config.json").read_text())
            raw["composite_weights"]["flip"]["ev"] = 0.30
            p = tmp / "c.json"
            p.write_text(json.dumps(raw))
            with self.assertRaises(ConfigError):
                load_config_file(p)
        finally:
            shutil.rmtree(tmp)

    def test_policy_change_is_config_not_code(self):
        """Changing a coordinator default changes the verdict without touching code."""
        tmp = Path(tempfile.mkdtemp())
        try:
            raw = json.loads((CONFIG_DIR / "scoring-config.json").read_text())
            raw["capital_and_risk"]["risk_capital_per_deal_cap"]["value"] = 3000
            raw["scoring_config_version"] = "2026.10.99"
            p = tmp / "c.json"
            p.write_text(json.dumps(raw))
            loose = load_config_file(p)
            out = run(case("project_vehicle_truck_over_cap"), cfg=loose)["scores"]["scorecard"]
            self.assertTrue(out["gates"]["cash_ok"])
            self.assertEqual(out["scoring_config_version"], "2026.10.99")
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()


class TestConfigShipsAsPackageData(unittest.TestCase):
    """P-03-03 (reported by Agent 02): an installed wheel must carry its config."""

    def test_config_inside_package_and_declared(self):
        import mbos_economics
        pkg = Path(mbos_economics.__file__).resolve().parent
        self.assertEqual(CONFIG_DIR, pkg / "config")
        for f in ("scoring-config.json", "estimation-priors.json", "history/scoring-config-2026.10.0.json"):
            self.assertTrue((CONFIG_DIR / f).exists(), f)
        toml = (pkg.parents[1] / "pyproject.toml").read_text()
        self.assertIn('mbos_economics = ["config/*.json", "config/history/*.json"]', toml)


class TestNoBuildArtifactsTracked(unittest.TestCase):
    """Agent 02 report: a committed economics/build/ made `git archive` installs ship stale code
    (setuptools saw build/lib as up to date). Build output must never be tracked."""

    def test_git_tracks_no_build_output(self):
        import subprocess
        root = Path(__file__).resolve().parents[2]
        try:
            out = subprocess.run(["git", "ls-files", "economics"], cwd=root, capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.skipTest("not a git checkout")
        bad = [f for f in out.splitlines() if f.startswith(("economics/build/", "economics/dist/")) or ".egg-info/" in f]
        self.assertEqual(bad, [])
