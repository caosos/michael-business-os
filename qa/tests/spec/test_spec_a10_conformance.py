"""A10 (real spine): every stored Item, ActionRequest, Approval, Receipt, Provenance and Outcome validates against
the PINNED frozen contracts with this lane's stricter validator (format checks on) — independent of 01's validator."""
from collections import Counter

from mbos_qa.contracts import Contracts
from mbos_qa.impl_spine import LANE_D

KINDS = {"item", "action-request", "approval", "receipt", "provenance", "outcome"}


def test_every_stored_document_conforms(qa, led):
    for listing in ("FIX-TRAILER-1", "FIX-LEAD-SMARTHOME-1", "FIX-LEAD-DRYWALL-1", "FIX-MOWER-1"):
        led.seed(listing)
    c = Contracts()
    seen, bad = Counter(), []
    for kind, doc in qa.documents(led.engine):
        seen[kind] += 1
        errs = c.errors(kind, doc)
        if errs:
            bad.append((kind, errs[:2]))
    assert not bad, bad[:5]
    assert set(seen) == KINDS, dict(seen)
    types = {d["type"] for k, d in qa.documents(led.engine) if k == "item"}
    assert types == {"flip", "service"}


def test_shared_runtime_documents_conform(qa):
    c = Contracts()
    bad = [(k, c.errors(k, d)[:1]) for k, d in qa.documents() if c.errors(k, d)]
    assert not bad, bad[:5]


def test_chain_and_dry_run_audit_agree(qa, led):
    led.seed()
    assert qa.verify_chain(led.engine)["ok"]
    if not LANE_D:  # 01's own audit targets the reference DDL; lane D has its own A7 view (checked below)
        from mbos import audit

        with led.engine.connect() as conn:
            res = audit.full_audit(conn)
        assert res["conformance"]["ok"] and res["chain"]["ok"] and res["dry_run"]["ok"], res
    else:
        assert qa.scalar("SELECT count(*) FROM mbos.v_a7_live_effects", led.engine) == 0
