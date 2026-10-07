"""D-06: the State MCP server is the only agent write path; identity/scope reach provenance; every call is
logged and every successful write call is receipted."""

import asyncio
import json

import psycopg
import pytest
from psycopg import errors

from mbos_state import mbos_canonical
from mbos_state.mcp_server import build_server
from mbos_state.mcp_tools import Caller, StateTools, ToolFailed, ToolRefused
from conftest import key

AGENT_ID = "agent-02-opportunity"


@pytest.fixture
def tools(db):
    return StateTools(db.connect("agent_write"), Caller(AGENT_ID))


def _item(**over):
    return {"type": "flip", "category": "trailer", "dedup_key": key("blk"), "sources": [],
            "normalized": {"title": "6x12 trailer"}, **over}


SOURCE = {"basis": "FACT", "source_uri": "https://example.test/listing/9", "fetched_at": "2026-10-07T12:00:00Z"}


def _counts(conn):
    return conn.execute("SELECT (SELECT count(*) FROM mbos.receipts), (SELECT count(*) FROM mbos.items)").fetchone()


def test_catalogue_is_narrow_and_profile_scoped(db):
    agent = StateTools(db.connect("agent_write"), Caller(AGENT_ID))
    names = agent.tools()
    assert "record_approval" not in names
    assert not any(w in n for n in names for w in ("sql", "query", "exec", "raw"))
    op = StateTools(db.connect("approver"), Caller("operator-ui", "operator"))
    assert "record_approval" in op.tools()
    scoped = StateTools(db.connect("agent_write"), Caller("agent-07-marketing", scope=frozenset({"get_item", "propose_action"})))
    assert scoped.tools() == ["get_item", "propose_action"]
    server_tools = asyncio.run(build_server(agent).list_tools())
    assert sorted(t.name for t in server_tools) == sorted(names)


def test_agent_flow_over_mcp_protocol_is_fully_receipted(db, tools):
    server = build_server(tools)

    async def call(name, args):
        res = await server.call_tool(name, args)
        assert not res.is_error, res
        return json.loads(res.content[0].text)

    async def flow():
        c = await call("create_item", {"item": _item(), "intent": "ingest listing", "idempotency_key": key(),
                                       "evidence": [SOURCE]})
        item_id = c["item_id"]
        for st in ("NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL"):
            await call("transition_item", {"item_id": item_id, "to_state": st, "intent": st, "idempotency_key": key()})
        await call("patch_item", {"item_id": item_id, "patch": {"research": [{"note": "comps found"}]},
                                  "intent": "research", "idempotency_key": key()})
        p = await call("propose_action", {"action_request": {
            "item_id": item_id, "proposed_by": "michael",                      # spoof attempt: ignored
            "capability": "comms.email.send", "category": "email",
            "payload": {"to_ref": "party_1", "body": "Still available?", "offer": 850.0},
            "idempotency_key": key("eff"), "reversibility": "irreversible", "tier": 0,
            "expires_at": "2099-01-01T00:00:00Z"}, "intent": "ask seller", "idempotency_key": key()})
        o = await call("record_outcome", {"outcome": {"item_id": item_id, "kind": "message_no_reply"},
                                          "intent": "no reply", "idempotency_key": key()})
        g = await call("get_item", {"item_id": item_id})
        return c, p, o, g

    c, p, o, g = asyncio.run(flow())
    conn = db.connect()
    assert conn.execute("SELECT proposed_by FROM mbos.action_requests WHERE action_request_id=%s",
                        (p["action_request_id"],)).fetchone()[0] == AGENT_ID
    assert g["item"]["state"] == "AWAITING_APPROVAL" and p["action_request_id"] in g["item"]["action_request_ids"]

    # every write call: ok row, >= 1 receipt, each receipt cites the call's provenance, actor = caller
    rows = conn.execute("""SELECT tool, outcome, provenance_id, receipt_ids FROM mbos.mcp_calls
                           WHERE tool_kind = 'write' ORDER BY seq""").fetchall()
    assert [r[0] for r in rows] == ["create_item"] + ["transition_item"] * 5 + ["patch_item", "propose_action",
                                                                                 "record_outcome"]
    for tool, outcome, prov, rids in rows:
        assert outcome == "ok" and rids, tool
        for rid in rids:
            pids, actor = conn.execute("SELECT provenance_ids, actor FROM mbos.receipts WHERE receipt_id=%s",
                                       (rid,)).fetchone()
            assert prov in pids and actor == {"type": "agent", "id": AGENT_ID}
    # caller identity + scope + argument hash are in the call's provenance
    inputs = conn.execute("SELECT agent_name, tool_name, inputs_used FROM mbos.provenance WHERE provenance_id=%s",
                          (rows[0][2],)).fetchone()
    assert inputs[0] == AGENT_ID and inputs[1] == "mbos-state-mcp/create_item"
    assert {"ref": "mcp:caller", "agent_id": AGENT_ID, "profile": "agent", "scope": ["*"]} in inputs[2]
    # evidence provenance is attached and identity-forced
    ev = conn.execute("""SELECT p.agent_name, p.actor_type FROM mbos.receipts r
                         JOIN mbos.provenance p ON p.provenance_id = ANY (r.provenance_ids)
                         WHERE r.receipt_id = %s AND p.source_uri IS NOT NULL""", (rows[0][3][0],)).fetchone()
    assert ev == (AGENT_ID, "external")
    assert conn.execute("SELECT count(*) FROM mbos.mcp_calls WHERE tool_kind='read' AND outcome='ok'").fetchone()[0] == 1
    assert conn.execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]


def test_args_hash_is_mbos_cjson(db, tools):
    args = {"item": _item(), "intent": "x", "idempotency_key": key()}
    tools.call("create_item", args)
    h = db.connect().execute("SELECT args_hash FROM mbos.mcp_calls ORDER BY seq DESC LIMIT 1").fetchone()[0]
    assert h == mbos_canonical.sha256_of(args)


def test_identity_cannot_be_spoofed_through_evidence(db, tools):
    before = _counts(db.connect())
    for bad in ({**SOURCE, "human_actor": "michael"}, {**SOURCE, "approval_id": "appr_" + "0" * 26},
                {**SOURCE, "actor_type": "human"}):
        with pytest.raises(ToolRefused):
            tools.call("create_item", {"item": _item(), "intent": "x", "idempotency_key": key(), "evidence": [bad]})
    assert _counts(db.connect()) == before
    n = db.connect().execute("SELECT count(*) FROM mbos.mcp_calls WHERE outcome='refused'").fetchone()[0]
    assert n == 3


def test_scope_and_profile_refusals_are_logged_and_write_nothing(db):
    t = StateTools(db.connect("agent_write"), Caller("agent-07-marketing", scope=frozenset({"get_item"})))
    before = _counts(db.connect())
    with pytest.raises(ToolRefused):
        t.call("create_item", {"item": _item(), "intent": "x", "idempotency_key": key()})
    with pytest.raises(ToolRefused):
        StateTools(db.connect("agent_write"), Caller(AGENT_ID)).call("record_approval", {"approval": {}})
    assert _counts(db.connect()) == before
    rows = db.connect().execute("SELECT agent_id, tool, error_code FROM mbos.mcp_calls ORDER BY seq").fetchall()
    assert rows == [("agent-07-marketing", "create_item", "MCP403"), (AGENT_ID, "record_approval", "MCP403")]


def test_db_refusal_writes_nothing_but_is_logged(db, tools):
    item_id = tools.call("create_item", {"item": _item(), "intent": "x", "idempotency_key": key()})["item_id"]
    before = _counts(db.connect())
    with pytest.raises(ToolFailed) as ei:
        tools.call("transition_item", {"item_id": item_id, "to_state": "ACTING", "intent": "skip", "idempotency_key": key()})
    assert ei.value.code == "MB004"
    assert _counts(db.connect()) == before
    assert db.connect().execute("SELECT outcome, error_code FROM mbos.mcp_calls ORDER BY seq DESC LIMIT 1"
                                ).fetchone() == ("error", "MB004")


def test_replay_is_a_noop_and_still_linked_to_its_receipt(db, tools):
    k = key("replay")
    first = tools.call("create_item", {"item": _item(dedup_key="blk-r"), "intent": "x", "idempotency_key": k})
    n = _counts(db.connect())[0]
    again = tools.call("create_item", {"item": _item(dedup_key="blk-r"), "intent": "x", "idempotency_key": k})
    assert again["item_id"] == first["item_id"] and again["replayed"] and again["receipt_ids"] == first["receipt_ids"]
    assert _counts(db.connect())[0] == n


def test_injection_strings_are_just_data(db, tools):
    evil = "x'); DELETE FROM mbos.receipts; --"
    r = tools.call("create_item", {"item": _item(subcategory=evil), "intent": evil, "idempotency_key": key()})
    assert db.connect().execute("SELECT intent FROM mbos.receipts WHERE receipt_id=%s",
                                (r["receipt_ids"][0],)).fetchone()[0] == evil
    assert db.connect().execute("SELECT ok FROM mbos.verify_chain()").fetchone()[0]


def test_agent_without_the_mcp_cannot_write(db):
    """Agent processes get only the read credential (mbos_reader); the write login lives in the MCP server."""
    agent = db.connect("reader")
    for sql, params in (
            ("SELECT mbos.create_item(%s::jsonb, '{\"type\":\"agent\",\"id\":\"x\"}', 'x', '{}', 'k')", (json.dumps(_item()),)),
            ("INSERT INTO mbos.items (type, category, dedup_key, doc) VALUES ('flip','trailer','d','{}')", ()),
            ("INSERT INTO mbos.provenance (actor_type, basis, tool_name, tool_version) VALUES ('agent','FACT','t','1')", ()),
            ("SELECT mbos.append_receipt('{}'::jsonb)", ()),
            ("INSERT INTO mbos.mcp_calls (agent_id, profile, tool, tool_kind, args_hash, outcome) "
             "VALUES ('a','agent','t','read','sha256:" + "0" * 64 + "','ok')", ())):
        with pytest.raises(errors.InsufficientPrivilege):
            agent.execute(sql, params)


def test_mcp_role_itself_cannot_approve_execute_or_spend(db, tools):
    conn = db.connect("agent_write")
    for fn in ("mbos.record_approval('{}'::jsonb, '{}'::jsonb, 'x', 'k')",
               "mbos.set_action_status('a','b','c','{}'::jsonb,'x','{}','k')",
               "mbos.budget_reserve('a', 1, 'USD', 1, '{}'::jsonb, 'x', '{}', 'k')",
               "mbos.panic_set('L3', NULL, false, '{}'::jsonb, 'x', '{}', 'k')",
               "mbos.effector_claim('a')"):
        with pytest.raises(errors.InsufficientPrivilege):
            conn.execute(f"SELECT {fn}")


def test_mcp_calls_ledger_rules(db, tools):
    tools.call("list_items", {})          # a real row, so the row-level append-only trigger has something to guard
    owner = db.connect("owner")
    with pytest.raises(errors.CheckViolation):    # an ok write call without a receipt cannot exist
        owner.execute("INSERT INTO mbos.mcp_calls (agent_id, profile, tool, tool_kind, args_hash, outcome) "
                      "VALUES ('a','agent','create_item','write','sha256:" + "0" * 64 + "','ok')")
    with pytest.raises(psycopg.Error) as ei:
        owner.execute("INSERT INTO mbos.mcp_calls (agent_id, profile, tool, tool_kind, args_hash, outcome, receipt_ids) "
                      "VALUES ('a','agent','create_item','write','sha256:" + "0" * 64 + "','ok', ARRAY['rcpt_x'])")
    assert ei.value.sqlstate == "MB003"
    for sql in ("UPDATE mbos.mcp_calls SET tool='x'", "DELETE FROM mbos.mcp_calls"):
        with pytest.raises(psycopg.Error) as ei:
            owner.execute(sql)
        assert ei.value.sqlstate == "MB001"


def test_operator_profile_records_michaels_decision(db, tools):
    from conftest import GATEWAY, payload_hash, to_pending
    item_id = tools.call("create_item", {"item": _item(), "intent": "x", "idempotency_key": key()})["item_id"]
    for st in ("NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL"):
        tools.call("transition_item", {"item_id": item_id, "to_state": st, "intent": st, "idempotency_key": key()})
    areq = tools.call("propose_action", {"action_request": {
        "item_id": item_id, "capability": "comms.email.send", "category": "email", "payload": {"b": 1},
        "idempotency_key": key("e"), "reversibility": "reversible", "tier": 0, "expires_at": "2099-01-01T00:00:00Z"},
        "intent": "p", "idempotency_key": key()})["action_request_id"]
    gw = db.store("gateway")
    pid = gw.record_provenance(actor_type="system", basis="FACT", tool_name="t", tool_version="1")
    to_pending(gw, areq, pid)
    op = StateTools(db.connect("approver"), Caller("operator-ui", "operator"))
    r = op.call("record_approval", {"approval": {
        "action_request_id": areq, "decision": "NO", "decider": "michael", "channel": "web",
        "payload_hash_seen": payload_hash(gw, areq), "scope": "once", "reason": "not worth the drive"},
        "intent": "Michael: NO", "idempotency_key": key()})
    actor = db.connect().execute("SELECT actor FROM mbos.receipts WHERE receipt_id=%s", (r["receipt_ids"][0],)).fetchone()[0]
    assert actor == {"type": "human", "id": "michael"} and r["approval_id"].startswith("appr_")


def test_real_stdio_server_process(db):
    """Launch `python -m mbos_state.mcp_server` as a subprocess and drive it with the MCP client over stdio."""
    import os
    import sys
    from pathlib import Path

    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    state_dir = Path(__file__).resolve().parent.parent
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "mbos_state.mcp_server"], cwd=str(state_dir),
        env={**os.environ, "PYTHONPATH": str(state_dir), "MBOS_DSN": db.dsn("agent_write"),
             "MBOS_MCP_AGENT_ID": "agent-03-economics", "MBOS_MCP_SCOPE": "get_item,list_items,create_item"})

    async def run():
        async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            names = sorted(t.name for t in (await s.list_tools()).tools)
            created = await s.call_tool("create_item", {"item": _item(), "intent": "stdio", "idempotency_key": key()})
            denied = await s.call_tool("transition_item", {"item_id": "x", "to_state": "y", "intent": "z",
                                                           "idempotency_key": key()})
            return names, created, denied

    names, created, denied = asyncio.run(run())
    assert names == ["create_item", "get_item", "list_items"]          # scope applied at registration
    assert not created.is_error and json.loads(created.content[0].text)["receipt_ids"]
    assert denied.is_error                                              # out-of-scope tool does not exist
    row = db.connect().execute("SELECT agent_id, outcome FROM mbos.mcp_calls WHERE tool='create_item'").fetchone()
    assert row == ("agent-03-economics", "ok")
