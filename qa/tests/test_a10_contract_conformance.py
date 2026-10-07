"""A10 — every stored Item, ActionRequest, Approval, Receipt, Provenance and Outcome validates against
contracts/ (pinned, frozen v1.0.0)."""
import copy
from collections import Counter

import pytest

from mbos_qa.contracts import ContractViolation, run_contract_checks, run_gap_probes

KINDS = {"item", "action-request", "approval", "receipt", "provenance", "outcome"}


def test_pinned_contracts_are_intact_and_examples_and_invariants_hold():
    rep = run_contract_checks()
    failed = [f"{c.name}: {c.detail}" for c in rep.checks if not c.passed]
    assert not failed, failed


def test_every_stored_document_conforms(ran):
    seen = Counter()
    bad = []
    for kind, doc in ran.store.all_documents():
        seen[kind] += 1
        errs = ran.contracts.errors(kind, doc)
        if errs:
            bad.append((kind, errs[:2]))
    assert not bad, bad
    assert set(seen) == KINDS, f"conformance must cover all six contracts, saw {dict(seen)}"


def test_both_lanes_covered(ran):
    types = {doc["type"] for kind, doc in ran.store.all_documents() if kind == "item"}
    assert types == {"flip", "service"}


def test_store_refuses_nonconforming_documents(ran):
    item = copy.deepcopy(next(d for k, d in ran.store.all_documents() if k == "item" and d["type"] == "flip"))
    item["item_id"] = ran.ids.new("itm")
    item["category"] = "drywall_repair"
    n = ran.store.count("items")
    with pytest.raises(ContractViolation):
        with ran.store.tx() as t:
            t.put_item(item)
    assert ran.store.count("items") == n


def test_contract_gaps_are_enforced_at_runtime_even_though_schema_accepts():
    """Gap probes document schema holes (reported to Agent 01); the runtime must still enforce each one.
    Enforcement is covered by: MODIFY/HOLD → test_a06; step-up → test_a06; dry_run → test_a07; prev_hash → test_a03."""
    probes = run_gap_probes()
    assert len(probes) == 5
