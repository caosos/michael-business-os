"""B-02 (ADR-0010): lane B hashes with MBOS-CJSON-1, byte-identical to the normative reference."""

from __future__ import annotations

import importlib.util
import json
import math
import random
import shutil
from importlib import resources
from pathlib import Path

import pytest

from conftest import FIX
from mbos_discovery import ids
from mbos_discovery.contracts.canonical import mbos_canonical as ref

VEC = json.loads((resources.files("mbos_discovery") / "contracts" / "canonical" / "vectors.json").read_text())


@pytest.mark.parametrize("case", VEC["cjson"], ids=lambda c: c["name"])
def test_cjson_vectors(case):
    obj = json.loads(case["input"])
    assert ids.canonical_json(obj).decode() == case["canonical"]
    assert ids.sha256_ref(ids.canonical_json(obj)) == case["sha256"]


@pytest.mark.parametrize("case", VEC["reject"], ids=lambda c: c["name"])
def test_reject_vectors(case):
    with pytest.raises(ValueError):
        # the reference parses with object_pairs_hook to see duplicate names; mirror its input handling
        ids.canonical_json(json.loads(case["input"], object_pairs_hook=_pairs))


def _pairs(pairs):
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError("duplicate member names")
        d[k] = v
    return d


def test_850_point_0_hashes_as_850():
    assert ids.canonical_json({"offer": 850.0}) == ids.canonical_json({"offer": 850}) == b'{"offer":850}'


def test_matches_reference_on_every_fixture_payload():
    n = 0
    for p in sorted(FIX.rglob("*.json")):
        try:
            obj = json.loads(p.read_bytes())
        except ValueError:
            continue
        assert ids.canonical_json(obj) == ref.canonical_bytes(obj), p
        n += 1
    assert n >= 10


def test_matches_reference_on_random_numbers():
    rng = random.Random(20261007)
    for _ in range(5000):
        x = rng.choice([rng.uniform(-1e6, 1e6), rng.random() * 10 ** rng.randint(-12, 15),
                        float(rng.randint(-2**53 + 1, 2**53 - 1)), round(rng.uniform(0, 5000), 2)])
        if math.isfinite(x):
            assert ids.canonical_json([x]) == ref.canonical_bytes([x])


def test_ids_module_loads_standalone_like_interop_check(tmp_path):
    """tools/interop_check.py copies ids.py alone into a temp dir and imports it."""
    f = tmp_path / "lane02.py"
    shutil.copy(Path(ids.__file__), f)
    spec = importlib.util.spec_from_file_location("lane02", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for case in VEC["cjson"]:
        assert mod.sha256_ref(mod.canonical_json(json.loads(case["input"]))) == case["sha256"]


def test_raw_retention_and_content_hash_use_the_same_encoder():
    from mbos_discovery.canonical import raw_json_bytes
    from mbos_discovery.dedup import content_hash
    obj = {"title": "t", "price": {"amount": 850.0, "type": "fixed"}}
    assert raw_json_bytes(obj) == ref.canonical_bytes(obj)
    assert content_hash(obj) == ref.sha256_of({k: obj.get(k) for k in
                                               ("title", "description", "condition", "price", "ends_at",
                                                "bid_count", "location", "listing_status")})
