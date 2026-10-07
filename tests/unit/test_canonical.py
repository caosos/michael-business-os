"""ADR-0010 MBOS-CJSON-1: the runtime hashes exactly like the normative reference vectors."""

import json

import pytest

from mbos.hashing import canonical_json, reference, sha256_of
from tests.helpers.common import ROOT

VECTORS = json.loads((ROOT / "docs/research/contracts/canonical/vectors.json").read_text())


@pytest.mark.parametrize("case", VECTORS["cjson"], ids=lambda c: c["name"])
def test_runtime_matches_vectors(case):
    obj = json.loads(case["input"])
    assert canonical_json(obj).decode() == case["canonical"]
    assert sha256_of(obj) == case["sha256"]


@pytest.mark.parametrize("case", VECTORS["reject"], ids=lambda c: c["name"])
def test_rejections(case):
    with pytest.raises(reference().CanonicalError):
        canonical_json(json.loads(case["input"]))


def test_f14_850_point_0_equals_850():
    assert sha256_of({"offer": 850.0}) == sha256_of({"offer": 850})


def test_receipt_vectors_verify():
    ok, msg = reference().verify_chain(VECTORS["receipt_chain"])
    assert ok, msg
