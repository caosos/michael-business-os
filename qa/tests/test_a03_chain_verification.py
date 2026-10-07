"""A3 — verify_chain passes, and fails after a single byte is tampered with."""
from mbos_qa.core import receipt_row_hash


def test_chain_passes_after_full_run(ran):
    res = ran.store.verify_chain()
    assert res.ok, res.errors
    assert res.checked == ran.store.count("receipts") > 20


def test_one_byte_tamper_detected(ran):
    def flip_one_char(doc):
        doc["intent"] = doc["intent"][:-1] + ("X" if doc["intent"][-1] != "X" else "Y")
    ran.store.qa_tamper_receipt(5, flip_one_char)
    res = ran.store.verify_chain()
    assert not res.ok
    assert any(e.startswith("seq 5:") and "row_hash" in e for e in res.errors)


def test_tamper_with_recomputed_hash_breaks_the_next_link(ran):
    """An attacker who also recomputes row_hash for the edited row is caught by seq+1's prev_hash."""
    def forge(doc):
        doc["intent"] = "forged"
        doc["row_hash"] = receipt_row_hash(doc)
    ran.store.qa_tamper_receipt(7, forge)
    res = ran.store.verify_chain()
    assert not res.ok
    assert not any(e.startswith("seq 7:") for e in res.errors)  # the forged row is self-consistent…
    assert any(e.startswith("seq 8:") and "prev_hash" in e for e in res.errors)  # …but no longer linked


def test_tampered_effector_flag_detected(ran):
    executed = ran.store.receipts(type="ACTION_EXECUTED")[0]
    ran.store.qa_tamper_receipt(executed["seq"], lambda d: d["effector_response"].update(dry_run=False))
    assert not ran.store.verify_chain().ok


def test_deleted_row_detected_as_seq_gap(ran):
    conn = ran.store.conn
    conn.execute("DROP TRIGGER receipts_no_delete")
    conn.execute("DELETE FROM receipts WHERE seq=10")
    errors = ran.store.verify_chain().errors
    assert any("seq gap" in e for e in errors)


import pytest  # noqa: E402


@pytest.mark.xfail(strict=True, reason="KNOWN GAP F-6: a hash chain alone cannot detect deletion of the newest rows; "
                                       "needs an external head anchor (Agent 04)")
def test_tail_truncation_detected(ran):
    conn = ran.store.conn
    conn.execute("DROP TRIGGER receipts_no_delete")
    last = conn.execute("SELECT max(seq) FROM receipts").fetchone()[0]
    conn.execute("DELETE FROM receipts WHERE seq > ?", (last - 3,))
    assert not ran.store.verify_chain().ok


def test_chain_verifies_with_the_adr0010_reference_alone(ran):
    """An exported chain must verify with ONLY the normative reference (MBOS-RH-1), not with this lane's code."""
    from mbos_qa.core import mbos_canonical
    ok, msg = mbos_canonical.verify_chain(ran.store.receipts())
    assert ok, msg
    assert all(r["ts"].endswith("Z") and len(r["ts"].split(".")[1]) == 7 for r in ran.store.receipts()), \
        "ADR-0010: receipt ts must carry exactly 6 fractional digits"
