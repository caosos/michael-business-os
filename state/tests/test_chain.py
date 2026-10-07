"""A3 / verify_chain: monotonic gapless seq, prev_hash linkage, tamper detection (in-DB and offline)."""

import json
import threading

import psycopg
import pytest

from mbos_state import chain
from conftest import AGENT, key, make_item, tool_prov


def _fill(store, n=10):
    item_id, pid = make_item(store, "RESEARCHING")
    for i in range(n):
        state = "SCORED" if i % 2 == 0 else "RESEARCHING"
        store.transition_item(item_id, state, AGENT, f"loop {i}", [pid], key("loop"))
    return item_id, pid


def _tamper(db, sql, params=()):
    """Simulate an attacker with superuser rights: replica mode skips every trigger and FK check."""
    su = db.connect("superuser")
    with su.transaction():
        su.execute("SET LOCAL session_replication_role = replica")
        su.execute(sql, params)


def test_chain_ok_and_seq_monotonic(db):
    s = db.store()
    _fill(s, 20)
    st = s.verify_chain()
    assert st.ok, st
    seqs = [r[0] for r in s.conn.execute("SELECT seq FROM mbos.receipts ORDER BY seq")]
    assert seqs == list(range(1, len(seqs) + 1))
    rows = s.conn.execute("SELECT seq, prev_hash, row_hash FROM mbos.receipts ORDER BY seq").fetchall()
    assert rows[0][1] is None
    for (_, _, prev_row), (_, prev, _) in zip(rows, rows[1:]):
        assert prev == prev_row


def test_writer_cannot_choose_chain_fields(db):
    s = db.store("agent_write")
    pid = tool_prov(s)
    doc = s.append_receipt({"type": "INJECTION_SUSPECTED", "actor": {"type": "agent", "id": "x"}, "intent": "probe",
                            "idempotency_key": key(), "provenance_ids": [pid], "seq": 999999,
                            "prev_hash": "sha256:" + "00" * 32, "row_hash": "sha256:" + "11" * 32})
    head = s.chain_head()
    assert doc["seq"] == head["seq"] != 999999
    assert doc["row_hash"] == head["row_hash"] != "sha256:" + "11" * 32
    assert s.verify_chain().ok


def test_concurrent_writers_never_fork(db):
    s = db.store()
    item_ids = [make_item(s, "RESEARCHING") for _ in range(8)]
    errors = []

    def worker(item_id, pid):
        try:
            w = db.store("agent_write")
            for i in range(15):
                w.transition_item(item_id, "SCORED" if i % 2 == 0 else "RESEARCHING", AGENT, "race", [pid], key("c"))
        except Exception as e:  # pragma: no cover - surfaced below
            errors.append(e)

    threads = [threading.Thread(target=worker, args=ip) for ip in item_ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, errors
    st = s.verify_chain()
    assert st.ok, st
    n, mx = s.conn.execute("SELECT count(*), max(seq) FROM mbos.receipts").fetchone()
    assert n == mx  # gapless under concurrency


@pytest.mark.parametrize("label,sql,reason", [
    ("column edit", "UPDATE mbos.receipts SET intent = 'innocent' WHERE seq = %s", "stored columns differ"),
    ("canonical edit", "UPDATE mbos.receipts SET canonical = replace(canonical, 'loop', 'LOOP') WHERE seq = %s",
     "row_hash does not match"),
    ("consistent rewrite",
     """UPDATE mbos.receipts SET intent = 'innocent',
            canonical = mbos.cjson(mbos.receipt_canonical(receipts) || '{"intent":"innocent"}'),
            row_hash = mbos.cjson_sha256(mbos.receipt_canonical(receipts) || '{"intent":"innocent"}')
        WHERE seq = %s""",
     "prev_hash does not match"),
    ("deleted row", "DELETE FROM mbos.receipts WHERE seq = %s", "seq gap"),
])
def test_tamper_detected(db, label, sql, reason):
    s = db.store()
    _fill(s, 10)
    target = s.conn.execute("SELECT max(seq) - 3 FROM mbos.receipts").fetchone()[0]
    _tamper(db, sql, (target,))
    st = s.verify_chain()
    assert not st.ok, label
    assert reason in st.reason, (label, st)
    assert st.first_bad_seq in (target, target + 1)


def test_single_byte_flip_detected(db):
    s = db.store()
    _fill(s, 5)
    _tamper(db, """UPDATE mbos.receipts SET row_hash = overlay(row_hash placing
              CASE WHEN substr(row_hash, 20, 1) = 'f' THEN 'e' ELSE 'f' END from 20 for 1) WHERE seq = 3""")
    st = s.verify_chain()
    assert not st.ok and st.first_bad_seq in (3, 4)


def test_tail_truncation_needs_anchor(db, tmp_path):
    s = db.store()
    _fill(s, 6)
    anchor = chain.write_anchor(s.conn, tmp_path / "anchors.jsonl")
    assert s.verify_chain(anchor=anchor).ok
    _tamper(db, "DELETE FROM mbos.receipts WHERE seq >= %s", (anchor["seq"] - 1,))
    assert s.verify_chain().ok  # a self-consistent shorter chain: undetectable without an anchor
    st = s.verify_chain(anchor=anchor)
    assert not st.ok and "anchored receipt is missing" in st.reason


def test_offline_export_verify_and_tamper(db, tmp_path):
    s = db.store()
    _fill(s, 8)
    out = tmp_path / "chain.jsonl"
    anchors = tmp_path / "anchors.jsonl"
    n = chain.export_chain(s.conn, out)
    chain.write_anchor(s.conn, anchors)
    ok, checked, problem = chain.verify_export(out, anchors)
    assert ok and checked == n, problem

    lines = out.read_text().splitlines()
    i = next(n for n, line in enumerate(lines) if "loop 3" in line)
    rec = json.loads(lines[i])
    rec["intent"] = "loop 4"
    bad = tmp_path / "bad.jsonl"
    bad.write_text("\n".join(lines[:i] + [json.dumps(rec)] + lines[i + 1:]) + "\n")
    ok, _, problem = chain.verify_export(bad)
    assert not ok and "row_hash" in problem

    truncated = tmp_path / "trunc.jsonl"
    truncated.write_text("\n".join(lines[:-2]) + "\n")
    assert chain.verify_export(truncated)[0]               # consistent prefix...
    assert not chain.verify_export(truncated, anchors)[0]  # ...but the anchor catches it


def test_db_canonical_matches_python_hash(db):
    s = db.store()
    _fill(s, 3)
    for canonical, row_hash in s.conn.execute("SELECT canonical, row_hash FROM mbos.receipts"):
        assert chain.sha256_text(canonical) == row_hash


def test_verify_chain_from_offset(db):
    s = db.store()
    _fill(s, 6)
    st = s.verify_chain(from_seq=4)
    assert st.ok and st.receipts_checked == s.chain_head()["seq"] - 3


def test_db_chain_verifies_with_adr0010_reference(db, tmp_path):
    """D-02 acceptance: a chain exported from this DB verifies with mbos_canonical.verify_chain."""
    from mbos_state import mbos_canonical
    s = db.store()
    item_id, pid = _fill(s, 5)
    s.update_item_doc(item_id, {"economics": {"offer": 850.0, "rate": 3.20, "tiny": 1e-7, "neg": -0.0}},
                      "SCORE_RECORDED", AGENT, "floats per ADR-0010", [pid], key())
    out = tmp_path / "chain.jsonl"
    chain.export_chain(s.conn, out)
    docs = [json.loads(x) for x in out.read_text().splitlines()]
    ok, msg = mbos_canonical.verify_chain(docs)
    assert ok, msg
    for canonical, doc in s.conn.execute(
            "SELECT r.canonical, mbos.receipt_document(r) FROM mbos.receipts r ORDER BY seq"):
        assert canonical == mbos_canonical.canonical_json(mbos_canonical.receipt_hash_document(doc))
