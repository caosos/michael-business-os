"""Pydantic models must stay aligned with the FROZEN JSON Schemas: same fields, same examples."""

import json
import subprocess
import sys

import pytest

from mbos.contracts import ContractViolation, schemas
from mbos.contracts.models import MODELS, Item, Normalized, Recommendation, Scores
from tests.helpers.common import ROOT

CONTRACTS = ROOT / "docs" / "research" / "contracts"


@pytest.mark.parametrize("kind", sorted(MODELS))
def test_top_level_fields_match_schema(kind):
    assert set(MODELS[kind].model_fields) == set(schemas.schema(kind)["properties"]), kind


@pytest.mark.parametrize("model,path", [
    (Normalized, ["properties", "normalized"]), (Scores, ["properties", "scores"]),
    (Recommendation, ["properties", "recommendation"]),
])
def test_nested_item_blocks_match_schema(model, path):
    node = schemas.schema("item")
    for p in path:
        node = node[p]
    assert set(model.model_fields) == set(node["properties"])


@pytest.mark.parametrize("example", sorted(p.name for p in (CONTRACTS / "examples").glob("*.json")))
def test_examples_round_trip_byte_equal(example):
    doc = json.loads((CONTRACTS / "examples" / example).read_text())
    kind = next(k for k in sorted(MODELS, key=len, reverse=True) if example.startswith(k + "-"))
    assert MODELS[kind].from_doc(doc).to_doc() == doc


def test_models_enforce_schema_only_rules():
    doc = json.loads((CONTRACTS / "examples" / "item-flip-trailer.example.json").read_text())
    doc["category"] = "drywall_repair"  # flip with a service category: only the schema's allOf catches this
    with pytest.raises(ContractViolation):
        Item.from_doc(doc)


def test_frozen_contract_validator_still_passes():
    cp = subprocess.run([sys.executable, "-I", str(CONTRACTS / "validate_contracts.py"), str(CONTRACTS)],
                        capture_output=True, text=True)
    assert cp.returncode == 0, cp.stdout + cp.stderr
    assert "negative invariant tests: PASS" in cp.stdout
