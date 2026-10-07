"""A3 (real spine): the chain verifies — with 01's verifier AND with the pinned ADR-0010 reference alone — and a
single tampered byte is detected by both."""
import json

from mbos_qa.core import mbos_canonical


def test_chain_verifies_with_spine_and_with_reference_only(qa, led):
    led.seed()
    assert qa.verify_chain(led.engine)["ok"]
    ok, msg = mbos_canonical.verify_chain(qa.receipts(led.engine))
    assert ok, f"MBOS-RH-1 reference rejects the spine's chain: {msg}"


def test_shared_runtime_chain_verifies_with_reference(qa, pending_flip):
    item_id, areq = pending_flip
    qa.decide(areq["action_request_id"], "YES")
    qa.wait_state(item_id, {"ACTED", "FAILED"})
    ok, msg = mbos_canonical.verify_chain(qa.receipts())
    assert ok and qa.verify_chain()["ok"], msg


def _tamper(led, seq, mutate):
    body = led.qa.scalar("SELECT body FROM mbos.receipts WHERE seq = :s", led.engine, s=seq)
    mutate(body)
    led.superuser_sql("ALTER TABLE mbos.receipts DISABLE TRIGGER USER")  # QA HOOK: a superuser bypass
    led.superuser_sql("UPDATE mbos.receipts SET body = CAST(:b AS jsonb) WHERE seq = :s", b=json.dumps(body), s=seq)
    led.superuser_sql("ALTER TABLE mbos.receipts ENABLE TRIGGER USER")


def test_one_byte_tamper_detected_by_both_verifiers(qa, led):
    led.seed()
    _tamper(led, 3, lambda b: b.update(intent=b["intent"][:-1] + ("X" if b["intent"][-1] != "X" else "Y")))
    assert not qa.verify_chain(led.engine)["ok"]
    assert not mbos_canonical.verify_chain(qa.receipts(led.engine))[0]


def test_forged_dry_run_flag_cannot_go_unnoticed(qa, led, record_property):
    """Either the database refuses the forgery outright, or both verifiers detect it. Never silent."""
    import sqlalchemy as sa

    led.seed()
    seq = next(r["seq"] for r in qa.receipts(led.engine) if r["type"] == "ACTION_EXECUTED")
    try:
        _tamper(led, seq, lambda b: b["effector_response"].update(dry_run=False))
    except sa.exc.IntegrityError as e:
        led.superuser_sql("ALTER TABLE mbos.receipts ENABLE TRIGGER USER")
        record_property("defence", "refused at write: " + str(e.orig).splitlines()[0])
        assert "dry_run" in str(e.orig)
        assert qa.verify_chain(led.engine)["ok"]  # nothing was written
        return
    record_property("defence", "detected by verification")
    assert not qa.verify_chain(led.engine)["ok"]
    assert not mbos_canonical.verify_chain(qa.receipts(led.engine))[0]
