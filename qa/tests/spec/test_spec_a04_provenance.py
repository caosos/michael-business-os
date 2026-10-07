"""A4 (real spine): every receipt's provenance_ids resolve under provenance.schema.json's anyOf rule —
checked independently (pinned contracts + this lane's resolver), and by 01's own audit."""
from mbos_qa.contracts import Contracts
from mbos_qa.report import provenance_resolution


def test_every_receipt_provenance_resolves_independently(qa, led):
    led.seed()
    c = Contracts()
    receipts = qa.receipts(led.engine)
    assert receipts
    for r in receipts:
        assert r["provenance_ids"], r["receipt_id"]
        for pid in r["provenance_ids"]:
            p = qa.find_provenance(pid, led.engine)
            assert p is not None, f"{r['type']} seq {r['seq']} cites missing {pid}"
            assert not c.errors("provenance", p), (pid, c.errors("provenance", p)[:2])
            assert "UNRESOLVED" not in provenance_resolution(p)


def test_spine_audit_agrees(qa, led):
    from mbos import audit

    led.seed()
    with led.engine.connect() as conn:
        res = audit.provenance_resolution(conn)
    assert res["ok"], res


def test_human_provenance_points_at_a_real_approval(qa, led):
    out = led.seed()
    prov = [p for kind, p in qa.documents(led.engine) if kind == "provenance" and p.get("approval_id")]
    assert any(p["approval_id"] == out["approval"]["approval_id"] for p in prov)
