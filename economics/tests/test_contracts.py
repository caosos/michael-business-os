"""Contract conformance (A10 / C23): engine output plugs into frozen Item v1 and Provenance v1.

Requires ``jsonschema>=4.18``; skipped (not failed) when it is not installed.
"""

import json
import unittest
from pathlib import Path

from helpers import HERE, case, run
from worked_cases import ALL_CASES

from mbos_economics.replay import replay_item

try:
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
except ImportError:  # pragma: no cover
    Draft202012Validator = None

REPO = HERE.parents[1]
EXAMPLES = HERE.parent / "examples"


def _validators():
    schemas = {}
    for p in [HERE / "contracts" / "item.schema.json", HERE / "contracts" / "provenance.schema.json",
              *sorted((REPO / "docs" / "research" / "schemas").glob("*.schema.json"))]:
        s = json.loads(p.read_text())
        Draft202012Validator.check_schema(s)
        schemas[p.name] = s
    reg = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in schemas.values()])
    return (Draft202012Validator(schemas["item.schema.json"], registry=reg),
            Draft202012Validator(schemas["provenance.schema.json"], registry=reg))


@unittest.skipIf(Draft202012Validator is None, "jsonschema not installed")
class TestContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.item_v, cls.prov_v = _validators()

    def errors(self, v, doc):
        return [f"{list(e.absolute_path)}: {e.message[:160]}" for e in v.iter_errors(doc)]

    def test_scored_items_validate(self):
        for name in ALL_CASES:
            with self.subTest(name):
                it = case(name)
                out = run(it)
                it["scores"], it["recommendation"] = out["scores"], out["recommendation"]
                it["provenance_ids"] = sorted({s["provenance_id"] for s in it["sources"]}
                                              | {out["provenance"]["provenance_id"]})
                it["state"] = "RECOMMENDED"
                self.assertEqual(self.errors(self.item_v, it), [])
                self.assertEqual(self.errors(self.prov_v, out["provenance"]), [])

    def test_every_receipt_draft_has_provenance(self):
        for name in ALL_CASES:
            out = run(case(name))
            for r in out["receipt_drafts"]:
                self.assertEqual(r["provenance_ids"], [out["provenance"]["provenance_id"]])
                self.assertRegex(r["payload_hash"], r"^sha256:[0-9a-f]{64}$")

    def test_golden_examples_validate_and_replay(self):
        files = sorted(EXAMPLES.glob("*.scored.json"))
        self.assertEqual(len(files), len(ALL_CASES))
        for p in files:
            with self.subTest(p.name):
                doc = json.loads(p.read_text())
                self.assertEqual(self.errors(self.item_v, doc["item"]), [])
                self.assertEqual(self.errors(self.prov_v, doc["provenance"]), [])
                r = replay_item(doc["item"])
                self.assertTrue(r["match"], r["diffs"])


if __name__ == "__main__":
    unittest.main()
