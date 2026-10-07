"""ADR-0010 conformance (E-01): MBOS-CJSON-1 payload_hash and MBOS-RH-1 row_hash.

tests/data/vectors.json is a byte-identical copy of
docs/research/contracts/canonical/vectors.json @ agent-01-coordinator 99e9ec0 (sha256 pinned below).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

from mbos_governance import ids

DATA = Path(__file__).parent / "data" / "vectors.json"
VECTORS_SHA256 = "4ff072e400a8517af73b3d38062cf9538629b9adca14d35031bebab385069082"
VEC = json.loads(DATA.read_text("utf-8"))


def test_vectors_file_is_pinned():
    assert hashlib.sha256(DATA.read_bytes()).hexdigest() == VECTORS_SHA256


@pytest.mark.parametrize("case", VEC["cjson"], ids=[c["name"] for c in VEC["cjson"]])
def test_cjson_vectors(case):
    obj = json.loads(case["input"])
    assert ids.canonical_json(obj) == case["canonical"]
    assert ids.payload_hash(obj) == case["sha256"]


@pytest.mark.parametrize("case", VEC["reject"], ids=[c["name"] for c in VEC["reject"]])
def test_rejections(case):
    with pytest.raises(ids.CanonicalError):
        ids.payload_hash(json.loads(case["input"]))


def test_receipt_chain_vector_verifies_with_05_code():
    prev = None
    for r in VEC["receipt_chain"]:
        assert r["prev_hash"] == prev
        assert ids.receipt_row_hash(r) == r["row_hash"]
        prev = r["row_hash"]


def test_receipt_chain_vector_verifies_in_05_store(env):
    """Load the vector chain into the stand-in store and run its verify_chain."""
    conn = sqlite3.connect(env.store.path)
    for r in VEC["receipt_chain"]:
        conn.execute("INSERT INTO receipts (seq, receipt_id, idempotency_key, type, action_request_id, body, prev_hash, row_hash)"
                     " VALUES (?,?,?,?,?,?,?,?)", (r["seq"], r["receipt_id"], r["idempotency_key"], r["type"],
                                                   r.get("action_request_id"), json.dumps(r), r["prev_hash"], r["row_hash"]))
    conn.commit()
    ok, msg = env.store.verify_chain()
    assert ok, msg


def test_integral_float_and_int_hash_equal():
    """F-14 closed: 850.0 == 850."""
    assert ids.payload_hash({"offer": 850.0}) == ids.payload_hash({"offer": 850})


def test_receipts_written_by_gateway_follow_rh1(env):
    env.gw.execute(env.approved("email")["action_request_id"])
    rs = env.store.receipts()
    assert rs and all(ids.receipt_row_hash(r) == r["row_hash"] for r in rs)
    assert all(len(r["ts"]) == 27 and r["ts"].endswith("Z") and r["ts"][19] == "." for r in rs)  # 6 digits


def test_ids_module_loads_standalone_like_interop_check(tmp_path):
    """tools/interop_check.py imports ids.py in isolation; it must not need the package."""
    src = Path(ids.__file__).read_text("utf-8")
    f = tmp_path / "isolated_ids.py"
    f.write_text(src)
    spec = importlib.util.spec_from_file_location("isolated_ids", f)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert sum(mod.payload_hash(json.loads(c["input"])) == c["sha256"] for c in VEC["cjson"]) == len(VEC["cjson"]) == 10
