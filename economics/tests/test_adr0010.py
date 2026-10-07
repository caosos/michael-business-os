"""C-02: ADR-0010 conformance (MBOS-CJSON-1 / MBOS-RH-1).

Acceptance (READY_QUEUE C-02): interop row 03 = 10/10; the 13 goldens replay.
"""

import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from helpers import CFG, HERE, case, run

from mbos_economics import canonical
from mbos_economics.inputs import InputError

REF = HERE / "contracts" / "canonical" / "mbos_canonical.py"
VEC = json.loads((HERE / "contracts" / "canonical" / "vectors.json").read_text())
SRC = HERE.parent / "src" / "mbos_economics" / "canonical.py"


class TestReferenceVendored(unittest.TestCase):
    def test_canonical_py_begins_with_reference_byte_identical(self):
        ref, ours = REF.read_bytes(), SRC.read_bytes()
        self.assertTrue(ours.startswith(ref), "canonical.py must begin with mbos_canonical.py byte-for-byte")
        self.assertIn(b"Agent 03 lane additions", ours[len(ref):])


class TestVectors(unittest.TestCase):
    def test_cjson_10_of_10(self):
        for c in VEC["cjson"]:
            with self.subTest(c["name"]):
                obj = json.loads(c["input"])
                self.assertEqual(canonical.canonical_json(obj), c["canonical"])
                self.assertEqual(canonical.content_hash(obj), c["sha256"])
        self.assertEqual(len(VEC["cjson"]), 10)

    def test_rejections(self):
        for c in VEC["reject"]:
            with self.subTest(c["name"]):
                with self.assertRaises(canonical.CanonicalError):
                    canonical.canonical_json(json.loads(c["input"]))

    def test_receipt_chain_mbos_rh_1(self):
        ok, msg = canonical.verify_chain(VEC["receipt_chain"])
        self.assertTrue(ok, msg)

    def test_interop_style_isolated_load(self):
        """Exactly how agent-01 tools/interop_check.py loads lane 03: the file alone, outside the package."""
        with tempfile.TemporaryDirectory() as td:
            f = Path(td) / "research_agent-03-economics.py"
            shutil.copy(SRC, f)
            spec = importlib.util.spec_from_file_location(f.stem, f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            got = sum(mod.content_hash(json.loads(c["input"])) == c["sha256"] for c in VEC["cjson"])
        self.assertEqual(got, 10)

    def test_decimal_hashes_as_nearest_double(self):
        from decimal import Decimal
        self.assertEqual(canonical.content_hash({"x": Decimal("850.00")}), canonical.content_hash({"x": 850}))
        self.assertEqual(canonical.content_hash({"x": Decimal("0.4578")}), canonical.content_hash({"x": 0.4578}))


class TestEngineRefusesUnhashable(unittest.TestCase):
    def test_nul_in_skill_name_is_input_error(self):
        it = case("drywall_basement")
        it["economics"]["job"]["required_skills"] = ["drywall\x00"]
        with self.assertRaises(InputError):
            run(it)


class TestGoldensRebaselined(unittest.TestCase):
    """Re-baseline note (docs/receipts/2026-10-07-c02-adr0010.md): under MBOS-CJSON-1 every golden
    inputs_hash and config_hash is UNCHANGED; only engine_version 0.1.0 -> 0.2.0 and the ids seeded
    by it (scorecard_id, rec_, prov_) and dependent payload hashes changed."""

    def test_inputs_hashes_pinned(self):
        pinned = {
            "drywall_basement": "sha256:9c53ec57112d7",
            "drywall_patch_coordinator": "sha256:c0459b98477a8",
            "equipment_repair_zero_turn": "sha256:ac2b9f9d9380d",
        }
        for name, prefix in pinned.items():
            self.assertTrue(run(case(name))["scores"]["inputs_hash"].startswith(prefix), name)

    def test_goldens_are_current_engine_and_replay(self):
        from mbos_economics import __version__
        from mbos_economics.replay import replay_item
        for p in sorted((HERE.parent / "examples").glob("*.scored.json")):
            doc = json.loads(p.read_text())
            self.assertEqual(doc["item"]["scores"]["scorecard"]["engine_version"], __version__, p.name)
            self.assertTrue(replay_item(doc["item"])["match"], p.name)
        self.assertEqual(CFG.version, "2026.10.1")


if __name__ == "__main__":
    unittest.main()
