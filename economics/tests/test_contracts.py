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


V11 = "https://michael-business-os/schemas/agent-03/v1.1.0/"


def _registry():
    """Frozen Item v1.0.0 resolves Agent 03's v1.0.0 schemas (vendored copies); this branch's v1.1.0
    schemas sit beside them under versioned $ids (C-03)."""
    docs = [HERE / "contracts" / "item.schema.json", HERE / "contracts" / "provenance.schema.json",
            *sorted((HERE / "contracts" / "vendor" / "agent-03").glob("*.schema.json")),
            *sorted((REPO / "docs" / "research" / "schemas").glob("*.schema.json"))]
    schemas = {}
    for p in docs:
        s = json.loads(p.read_text())
        Draft202012Validator.check_schema(s)
        schemas[s["$id"]] = s
    return schemas, Registry().with_resources([(i, Resource.from_contents(s)) for i, s in schemas.items()])


def _validators():
    schemas, reg = _registry()
    return (Draft202012Validator(schemas["https://michael-business-os/contracts/item.schema.json"], registry=reg),
            Draft202012Validator(schemas["https://michael-business-os/contracts/provenance.schema.json"], registry=reg))


def economics_v11_errors(item: dict) -> list[str]:
    """Validate each economics block against this branch's v1.1.0 schemas (versioned $ids)."""
    _, reg = _registry()
    doc = "opportunity" if item["type"] == "flip" else "service-job"
    errs = []
    for block, value in item["economics"].items():
        v = Draft202012Validator({"$ref": f"{V11}{doc}.schema.json#/properties/{block}"}, registry=reg)
        errs += [f"{block}{list(e.absolute_path)}: {e.message[:160]}" for e in v.iter_errors(value)]
    if "scores" in item:
        v = Draft202012Validator({"$ref": f"{V11}scorecard.schema.json"}, registry=reg)
        errs += [f"scorecard{list(e.absolute_path)}: {e.message[:160]}" for e in v.iter_errors(item["scores"]["scorecard"])]
    return errs


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
                self.assertEqual(economics_v11_errors(doc["item"]), [])

    def test_schema_ids_versioned(self):
        for p in sorted((REPO / "docs" / "research" / "schemas").glob("*.schema.json")):
            sid = json.loads(p.read_text())["$id"]
            self.assertEqual(sid, f"{V11}{p.name}")
            vendored = json.loads((HERE / "contracts" / "vendor" / "agent-03" / p.name).read_text())["$id"]
            self.assertNotEqual(sid, vendored)              # v1.0.0 and v1.1.0 can coexist in one registry


if __name__ == "__main__":
    unittest.main()
