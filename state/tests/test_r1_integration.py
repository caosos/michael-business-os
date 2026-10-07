"""Migration 0005: Agent 01 integration rulings R1 (tables), R3 (canonical hash), R5 (PANIC), R8 (dedup),
plus the DBOS role answer."""

import hashlib
import json
import threading

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import AGENT, GATEWAY, MICHAEL, key, make_areq, make_item, payload_hash, to_pending, tool_prov


from mbos_state import mbos_canonical

py_canonical = mbos_canonical.canonical_json   # ADR-0010 reference (MBOS-CJSON-1)
py_hash = mbos_canonical.sha256_of


CORPUS = [
    {},
    [],
    {"b": 1, "a": [3, 2, {"z": None, "y": True, "x": False}]},
    {"to_ref": "party_1", "template": "seller_question_v1", "body": "Is the 6x12 trailer still available?"},
    {"amount": 450.0, "price": 1234.56, "qty": 3, "neg": -7, "small": 0.25, "big": 123456789012345},
    {"rate": 3.20, "tiny": 1e-7, "micro": 0.000001, "negzero": -0.0, "third": 1 / 3},
    {"unicode": "Señor — café ✓ 日本 😀", "quote": "he said \"hi\"", "slash": "a/b\\c"},
    {"ctrl": "line1\nline2\ttab\r\b\f\u0001\u001f", "del": "\u007f", "ls": " "},
    {"Z": 1, "a": 2, "_": 3, "ä": 4, "aa": 5, "B": 6, "é": 8},
    {"nested": {"k2": {"k1": [{"b": [], "a": {}}]}}},
    "plain string", 42, 3.5, True, None,
]


@pytest.mark.parametrize("obj", CORPUS, ids=range(len(CORPUS)))
def test_sql_canonical_json_matches_python(db, obj):
    c = db.connect()
    sql_text, sql_hash = c.execute("SELECT mbos.cjson(%s), mbos.payload_hash(%s)",
                                   (Jsonb(obj), Jsonb(obj))).fetchone()
    assert sql_text == py_canonical(obj)
    assert sql_hash == py_hash(obj)


def test_propose_rejects_non_canonical_payload_hash(db):
    s = db.store()
    item_id, pid = make_item(s)
    payload = {"body": "hello", "to_ref": "party_9"}
    areq = make_areq(s, item_id, pid, payload=payload, payload_hash=py_hash(payload))
    assert payload_hash(s, areq) == py_hash(payload)
    old_style = "sha256:" + hashlib.sha256(json.dumps(payload).encode()).hexdigest()   # jsonb::text-like
    with pytest.raises(psycopg.Error) as ei:
        make_areq(s, item_id, pid, payload=payload, payload_hash=old_style)
    assert ei.value.sqlstate == "MB007"


def test_dedup_key_is_a_blocking_key(db):
    s = db.store()
    a, pid = make_item(s)
    block = s.conn.execute("SELECT dedup_key FROM mbos.items WHERE item_id=%s", (a,)).fetchone()[0]
    b = s.create_item({"type": "flip", "category": "trailer", "dedup_key": block, "sources": [], "normalized": {}},
                      AGENT, "same block, different listing", [pid], key())
    assert a != b
    hit = s.conn.execute("SELECT item_id FROM mbos.items WHERE doc->'sources' @> %s",
                         (Jsonb([{"source": "craigslist"}]),)).fetchall()
    assert (a,) in hit


def test_r12_strict_item_edges(db):
    """D-05: the strict ADR-0004 set is canonical (R12); 0006 removed the 0005 accommodations."""
    s = db.store()
    item_id, pid = make_item(s, "NORMALIZED")
    with pytest.raises(psycopg.Error) as ei:
        s.transition_item(item_id, "SCORED", AGENT, "skip research", [pid], key())
    assert ei.value.sqlstate == "MB004"
    edges = {tuple(r) for r in s.conn.execute("SELECT from_state, to_state FROM mbos.item_state_transitions")}
    assert not edges & {("NORMALIZED", "SCORED"), ("HELD", "APPROVED"), ("LEARNED", "ARCHIVED"), ("LEARNED", "FAILED")}
    assert ("ACTED", "AWAITING_APPROVAL") in edges and ("HELD", "AWAITING_APPROVAL") in edges
    assert s.conn.execute("SELECT terminal FROM mbos.item_states WHERE state='LEARNED'").fetchone()[0]


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------
def test_artifacts_content_addressed_and_insert_only(db):
    w = db.connect("agent_write")
    blob = b'{"raw":"listing bytes"}'
    h = w.execute("SELECT mbos.put_artifact(%s, 'application/json')", (blob,)).fetchone()[0]
    assert h == "sha256:" + hashlib.sha256(blob).hexdigest()
    assert w.execute("SELECT mbos.put_artifact(%s, 'application/json')", (blob,)).fetchone()[0] == h  # idempotent
    with pytest.raises(errors.CheckViolation):
        w.execute("INSERT INTO mbos.artifacts (sha256, media_type, byte_size, content) VALUES (%s,'x',1,'\\x00')",
                  ("sha256:" + "0" * 64,))
    with pytest.raises(errors.InsufficientPrivilege):
        w.execute("UPDATE mbos.artifacts SET media_type='x'")
    with pytest.raises(psycopg.Error) as ei:
        db.connect("owner").execute("DELETE FROM mbos.artifacts")
    assert ei.value.sqlstate == "MB001"


# ---------------------------------------------------------------------------
# effector_calls
# ---------------------------------------------------------------------------
def _approved(s):
    item_id, pid = make_item(s, "AWAITING_APPROVAL")
    areq = make_areq(s, item_id, pid)
    to_pending(s, areq, pid)
    appr = s.record_approval({"action_request_id": areq, "decision": "YES", "decider": "michael", "channel": "cli",
                              "payload_hash_seen": payload_hash(s, areq), "scope": "once",
                              "auth_context": {"method": "cli", "step_up": True}}, MICHAEL, "YES", key())
    return areq, appr, pid


def test_effector_call_requires_executing_receipt_and_is_exactly_once(db):
    s = db.store()
    areq, appr, pid = _approved(s)
    gw = db.connect("gateway")
    resp = {"provider": "dry-run:comms.email.send", "provider_msg_id": "dry_1", "status": "simulated", "dry_run": True}
    with pytest.raises(psycopg.Error) as ei:   # still `approved`: no ACTION_EXECUTING receipt yet
        gw.execute("SELECT * FROM mbos.record_effector_call(%s,'dry-run','dry_1',%s,%s)",
                   (areq, Jsonb({}), Jsonb(resp)))
    assert ei.value.sqlstate == "MB004"
    db.store("gateway").set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "guard ok", [pid], key(),
                                          extra={"approval_id": appr})
    first = gw.execute("SELECT * FROM mbos.record_effector_call(%s,'dry-run','dry_1',%s,%s)",
                       (areq, Jsonb({"body": "x"}), Jsonb(resp))).fetchone()
    again = gw.execute("SELECT * FROM mbos.record_effector_call(%s,'dry-run','dry_2',%s,%s)",
                       (areq, Jsonb({"body": "x"}), Jsonb({**resp, "provider_msg_id": "dry_2"}))).fetchone()
    assert first == (resp, False) and again == (resp, True)
    assert gw.execute("SELECT count(*) FROM mbos.effector_calls").fetchone()[0] == 1


def test_effector_calls_dry_run_only_and_gateway_only(db):
    s = db.store()
    areq, appr, pid = _approved(s)
    s.set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "go", [pid], key(), extra={"approval_id": appr})
    with pytest.raises(errors.CheckViolation):
        s.conn.execute("SELECT * FROM mbos.record_effector_call(%s,'postmark','pm_1','{}',%s)",
                       (areq, Jsonb({"provider": "postmark", "dry_run": False})))
    with pytest.raises(errors.InsufficientPrivilege):
        db.connect("agent_write").execute("SELECT * FROM mbos.record_effector_call(%s,'x','y','{}','{}')", (areq,))
    with pytest.raises(errors.InsufficientPrivilege):
        db.connect("approver").execute("SELECT * FROM mbos.record_effector_call(%s,'x','y','{}','{}')", (areq,))


# ---------------------------------------------------------------------------
# llm_spend
# ---------------------------------------------------------------------------
def test_llm_cap_never_exceeded_under_concurrency(db):
    results = []

    def call():
        c = db.connect("agent_write", autocommit=False)
        try:
            with c.transaction():
                c.execute("SELECT mbos.llm_spend_authorize('agent-03-economics', 0.10, 1.00)")
                c.execute("INSERT INTO mbos.llm_spend (agent_id, usd) VALUES ('agent-03-economics', 0.10)")
            results.append(True)
        except psycopg.Error as e:
            assert e.sqlstate == "MB006"
            results.append(False)

    threads = [threading.Thread(target=call) for _ in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    total = db.connect().execute("SELECT sum(usd) FROM mbos.llm_spend").fetchone()[0]
    assert results.count(True) == 10 and float(total) == pytest.approx(1.0)
    with pytest.raises(psycopg.Error) as ei:
        db.connect("agent_write").execute("SELECT mbos.llm_spend_authorize('x', 0, NULL)")
    assert ei.value.sqlstate == "MB006"
    with pytest.raises(psycopg.Error) as ei:
        db.connect("owner").execute("DELETE FROM mbos.llm_spend")
    assert ei.value.sqlstate == "MB001"


# ---------------------------------------------------------------------------
# PANIC (R5)
# ---------------------------------------------------------------------------
def _read(c):
    return c.execute("SELECT global_state, readable, error FROM mbos.panic_read()").fetchone()


def test_panic_checksum_matches_agent05_seal_and_tamper_reads_frozen(db):
    ui = db.store("approver")
    pid = tool_prov(ui)
    ui.conn.execute("SELECT mbos.panic_set('L3',NULL,false,%s,'Michael releases',%s,%s)", (MICHAEL.as_json(), [pid], key()))
    body = ui.conn.execute("SELECT body FROM mbos.panic_state ORDER BY revision DESC LIMIT 1").fetchone()[0]
    unsealed = {k: v for k, v in body.items() if k != "checksum"}
    assert body["checksum"] == py_hash(unsealed)    # = 05 _seal(): sha256 of MBOS-CJSON-1(body)
    assert _read(ui.conn) == ("RUNNING", True, None)
    su = db.connect("superuser")
    with su.transaction():
        su.execute("SET LOCAL session_replication_role = replica")
        su.execute("""UPDATE mbos.panic_state SET body = jsonb_set(body, '{agents}', '{"x":{}}')
                      WHERE revision = (SELECT max(revision) FROM mbos.panic_state)""")
    assert _read(ui.conn) == ("FROZEN", False, "checksum mismatch")
    # a mutation never repairs an unreadable state into RUNNING
    ui.conn.execute("SELECT mbos.panic_set('L1','agent-x',false,%s,'cleanup',%s,%s)", (MICHAEL.as_json(), [pid], key()))
    assert _read(ui.conn)[:2] == ("FROZEN", True)


# ---------------------------------------------------------------------------
# DBOS role (answer to ROUND_TWO_INTEGRATION §3 D)
# ---------------------------------------------------------------------------
def test_dbos_role_can_run_the_spine_and_own_its_checkpoint_schema(db):
    d = db.store("dbos")
    d.conn.execute("CREATE TABLE IF NOT EXISTS dbos.transaction_outputs (workflow_uuid text, function_id int, output text)")
    with d.transaction():   # a DBOS @transaction: checkpoint + state + receipt in one commit
        item_id, pid = make_item(d, "AWAITING_APPROVAL")
        d.conn.execute("INSERT INTO dbos.transaction_outputs VALUES ('wf1', 1, %s)", (item_id,))
    areq = make_areq(d, item_id, pid)
    to_pending(d, areq, pid)
    d.record_approval({"action_request_id": areq, "decision": "NO", "decider": "michael", "channel": "web",
                       "payload_hash_seen": payload_hash(d, areq), "scope": "once", "reason": "no"},
                      MICHAEL, "NO", key())
    with pytest.raises(psycopg.Error):   # still cannot rewrite history
        d.conn.execute("UPDATE mbos.receipts SET intent = 'x'")
    with pytest.raises(errors.InsufficientPrivilege):
        d.conn.execute("INSERT INTO mbos.policy (policy_key, version, decision, created_by, reason, provenance_ids) "
                       "VALUES ('k', 1, 'deny', 'x', 'x', ARRAY[%s])", (pid,))


VECTORS = json.loads((__import__("pathlib").Path(__file__).parent / "canonical" / "vectors.json").read_text())


@pytest.mark.parametrize("v", VECTORS["cjson"], ids=[v["name"] for v in VECTORS["cjson"]])
def test_adr0010_vectors_in_postgres(db, v):
    c = db.connect()
    text, h = c.execute("SELECT mbos.cjson(%s::jsonb), mbos.payload_hash(%s::jsonb)", (v["input"], v["input"])).fetchone()
    assert text == v["canonical"] and h == v["sha256"]


@pytest.mark.parametrize("v", VECTORS["reject"], ids=[v["name"] for v in VECTORS["reject"]])
def test_adr0010_rejections_in_postgres(db, v):
    with pytest.raises(psycopg.Error):   # jsonb parse or MBOS-CJSON-1 profile error
        db.connect().execute("SELECT mbos.cjson(%s::jsonb)", (v["input"],))


def test_adr0010_receipt_chain_vectors_in_postgres(db):
    c = db.connect()
    for doc, d_text in zip(VECTORS["receipt_chain"], VECTORS["receipt_chain_hash_documents"]):
        got_d, got_h = c.execute("SELECT mbos.cjson(mbos.rh1_hash_document(%s)), mbos.rh1_row_hash(%s)",
                                 (Jsonb(doc), Jsonb(doc))).fetchone()
        assert got_d == d_text and got_h == doc["row_hash"]
