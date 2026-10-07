"""A4 — every receipt's provenance_ids resolve under provenance.schema.json's anyOf rule
(source URI + time | model + version + prompt hash | approval id | tool + version)."""
import pytest

from mbos_qa.mocks.store import InvariantViolation
from mbos_qa.report import provenance_resolution


def _resolves(p: dict) -> bool:
    return any([
        p.get("source_uri") and p.get("fetched_at"),
        p.get("model_id") and p.get("model_version") and p.get("prompt_hash"),
        p.get("approval_id"),
        p.get("tool_name") and p.get("tool_version"),
    ])


def test_every_receipt_provenance_resolves(ran):
    receipts = ran.store.receipts()
    assert receipts
    for r in receipts:
        assert r["provenance_ids"], r["receipt_id"]
        for pid in r["provenance_ids"]:
            p = ran.store.find_provenance(pid)
            assert p is not None, f"{r['type']} seq {r['seq']} cites missing {pid}"
            assert not ran.contracts.errors("provenance", p)
            assert _resolves(p) and "UNRESOLVED" not in provenance_resolution(p)


def test_human_provenance_points_at_a_real_approval(ran):
    humans = [p for kind, p in ran.store.all_documents() if kind == "provenance" and p.get("approval_id")]
    assert humans
    for p in humans:
        appr = ran.store.get("approval", p["approval_id"])
        assert appr["decider"] == "michael"


def test_derived_from_chains_resolve(ran):
    for kind, p in ran.store.all_documents():
        if kind == "provenance":
            for parent in p.get("derived_from", []):
                assert ran.store.find_provenance(parent) is not None


def test_every_item_action_and_outcome_provenance_resolves(ran):
    for kind, doc in ran.store.all_documents():
        ids = list(doc.get("provenance_ids", [])) if kind in ("item", "action-request", "outcome") else []
        ids += [s["provenance_id"] for s in doc.get("sources", [])] + [x["provenance_id"] for x in doc.get("research", [])]
        if kind == "item" and doc.get("recommendation"):
            ids.append(doc["recommendation"]["provenance_id"])
        for pid in ids:
            assert ran.store.find_provenance(pid) is not None, f"{kind} cites missing {pid}"


@pytest.mark.parametrize("ids", [[], ["prov_01ZZZZZZZZZZZZZZZZZZZZZZZZ"]])
def test_store_refuses_receipt_without_resolvable_provenance(h, ids):
    n = h.store.count("receipts")
    with pytest.raises(InvariantViolation):
        with h.store.tx() as t:
            t.receipt(type="ITEM_STATE_CHANGED", actor={"type": "system", "id": "qa"}, intent="no provenance",
                      provenance_ids=ids, idempotency_key="qa-noprov")
    assert h.store.count("receipts") == n
