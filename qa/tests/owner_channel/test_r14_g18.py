"""G-18: R14 in the database. Lane D (04 @ lane_d_04_numbers = 23060eb: 0021 owner_channel, 0022 APPROVED gate) attacked as the REAL logins:
`mbos_dbos` (workflow: agent_write + gateway) and `mbos_operator_ui` (owner: approver + owner_channel), over a real PostgreSQL, with lane D's own
StateStore. Every forgery states the correct behaviour (refused by ROLE); the YES path must still work end to end."""
from __future__ import annotations

import itertools
import json
import sys
import uuid

import psycopg
import pytest
import sqlalchemy as sa
from psycopg import errors
from psycopg.types.json import Jsonb
from sqlalchemy.engine import make_url

HUMAN = {"type": "human", "id": "michael"}
_k = itertools.count()
key = lambda l="k": f"g18:{l}:{uuid.uuid4().hex[:8]}:{next(_k)}"  # noqa: E731


@pytest.fixture(scope="module")
def lane():
    from mbos_qa import impl_spine

    url = impl_spine.new_lane_d_database("qa_g18", pin="lane_d_04_numbers")
    src = impl_spine.lane_d_src("lane_d_04_numbers")
    sys.path.insert(0, str(src / "state"))
    for m in [m for m in sys.modules if m.startswith("mbos_state")]:
        del sys.modules[m]
    import mbos_state.store as store

    yield url, store
    sys.path.remove(str(src / "state"))
    for m in [m for m in sys.modules if m.startswith("mbos_state")]:
        del sys.modules[m]


def dsn(url, role):
    u = make_url(url).set(username=role, password=None)
    return u.render_as_string(hide_password=False).replace("postgresql+psycopg2://", "postgresql://").replace("postgresql+psycopg://", "postgresql://")


@pytest.fixture
def S(lane):
    url, store = lane
    conns = {}

    def get(role):
        if role not in conns:
            conns[role] = store.StateStore(psycopg.connect(dsn(url, role), autocommit=True))
        return conns[role]

    yield get
    for s in conns.values():
        s.conn.close()


def actors(store):
    return store.Actor("agent", "agent-02-discovery"), store.Actor("system", "action-gateway"), store.Actor("human", "michael")


def make_item(S, store, state="AWAITING_APPROVAL"):
    AGENT, _, _ = actors(store)
    wf = S("mbos_dbos")
    pid = wf.record_provenance(actor_type="external", basis="FACT", source_uri="https://example.test/l/1", fetched_at="2026-10-07T12:00:00Z")
    doc = {"type": "flip", "category": "trailer", "subcategory": "t", "dedup_key": key("dd"),
           "sources": [{"source": "craigslist", "url": "https://example.test/l/1", "ingestion_method": "api",
                        "first_seen_at": "2026-10-07T12:00:00Z", "provenance_id": pid}], "normalized": {"title": "trailer"}}
    iid = wf.create_item(doc, AGENT, "ingest", [pid], key("c"))
    for s in ["NORMALIZED", "RESEARCHING", "SCORED", "RECOMMENDED", "AWAITING_APPROVAL"]:
        wf.transition_item(iid, s, AGENT, s, [pid], key("t"))
    return iid, pid


def make_areq(S, store, iid, pid):
    AGENT, GW, _ = actors(store)
    wf = S("mbos_dbos")
    areq = wf.propose_action({"item_id": iid, "proposed_by": "agent-06-comms", "capability": "comms.email.send", "category": "email",
                              "payload": {"to_ref": "party_1", "template": "seller_question_v1", "body": "still available?"},
                              "idempotency_key": key("e"), "reversibility": "irreversible", "tier": 0, "expires_at": "2099-01-01T00:00:00Z",
                              "provenance_ids": [pid]}, AGENT, "ask", key("p"))
    wf.set_action_status(areq, "classified", "POLICY_DECIDED", GW, "tier 0", [pid], key("cl"), extra={"policy_decision_ref": "pol:t"})
    wf.set_action_status(areq, "pending_approval", "APPROVAL_REQUESTED", GW, "ask", [pid], key("rq"))
    return areq


def yes(S, areq, decision="YES"):
    h = S("mbos_dbos").conn.execute("SELECT payload_hash FROM mbos.action_requests WHERE action_request_id=%s", (areq,)).fetchone()[0]
    return {"action_request_id": areq, "decision": decision, "decider": "michael", "channel": "web", "payload_hash_seen": h, "scope": "once",
            "auth_context": {"method": "webauthn", "step_up": True}, **({"reason": "no"} if decision == "NO" else {})}


def n_receipts(S):
    return S("mbos_operator_ui").conn.execute("SELECT count(*) FROM mbos.receipts").fetchone()[0]


# ---- role membership is what the provision promises ---------------------------------------------------------------------------
def test_login_role_sets_are_exactly_workflow_vs_owner(lane):
    url, _ = lane
    with psycopg.connect(dsn(url, "postgres")) as su:
        g = lambda login: {r[0] for r in su.execute("SELECT g.rolname FROM pg_auth_members a JOIN pg_roles g ON g.oid=a.roleid "  # noqa: E731
                                                     "JOIN pg_roles m ON m.oid=a.member WHERE m.rolname=%s", (login,))}
        assert g("mbos_dbos") == {"agent_write", "gateway"}
        assert g("mbos_operator_ui") == {"approver", "owner_channel"}
        # nothing else may hold owner_channel, even transitively
        holders = {r[0] for r in su.execute("SELECT m.rolname FROM pg_roles m WHERE pg_has_role(m.oid,'owner_channel','MEMBER') AND NOT m.rolsuper")}
        assert holders == {"owner_channel", "mbos_operator_ui"} or holders == {"mbos_operator_ui", "owner_channel", "mbos_owner"} or holders <= {
            "owner_channel", "mbos_operator_ui", "mbos_owner", "mbos_migrator"}, holders
        assert "mbos_dbos" not in holders and not any(r in holders for r in ("agent_write", "gateway", "agent_read", "policy_admin"))


@pytest.mark.parametrize("claim", [HUMAN, {"type": "human", "id": "michael", "role": "approver"}, {"type": "human", "id": "Michael"}])
def test_dbos_cannot_forge_approval_with_a_human_claim(lane, S, claim):
    _, store = lane
    wf = S("mbos_dbos")
    iid, pid = make_item(S, store)
    areq = make_areq(S, store, iid, pid)
    before = n_receipts(S)
    with pytest.raises(errors.InsufficientPrivilege):
        wf.record_approval(yes(S, areq), store.Actor(claim["type"], claim["id"]), "forged YES", key())
    with pytest.raises(errors.InsufficientPrivilege):   # raw function too, claim in the JSON
        wf.conn.execute("SELECT mbos.record_approval(%s,%s,'forged',%s,%s)", (Jsonb(yes(S, areq)), Jsonb(claim), key(), [pid]))
    assert n_receipts(S) == before
    assert wf.conn.execute("SELECT status FROM mbos.action_requests WHERE action_request_id=%s", (areq,)).fetchone()[0] == "pending_approval"


def test_dbos_cannot_become_the_owner_by_set_role_or_session_authorization(lane, S):
    wf = S("mbos_dbos")
    for stmt in ("SET ROLE approver", "SET ROLE owner_channel", "SET ROLE mbos_operator_ui", "SET ROLE mbos_owner", "SET SESSION AUTHORIZATION mbos_operator_ui"):
        with pytest.raises((errors.InsufficientPrivilege, errors.Error)):
            wf.conn.execute(stmt)
    # a SECURITY DEFINER / grant escape: it may not grant itself anything either
    with pytest.raises(errors.InsufficientPrivilege):
        wf.conn.execute("GRANT approver TO mbos_dbos")


def test_dbos_cannot_fund_set_mission_set_or_cancel_campaign_even_claiming_human(lane, S):
    _, store = lane
    wf = S("mbos_dbos")
    pid = make_item(S, store)[1]
    before = n_receipts(S)
    calls = [("SELECT mbos.capital_fund(5::numeric,%s,'x',%s,%s)", (Jsonb(HUMAN), [pid], key())),
             ("SELECT mbos.capital_withdraw(1::numeric,%s,'x',%s,%s)", (Jsonb(HUMAN), [pid], key())),
             ("SELECT mbos.set_campaign(%s,%s,'x',%s,%s)", (Jsonb({"campaign_id": "cmp_x", "title": "t", "owner": "michael"}), Jsonb(HUMAN), [pid], key())),
             ("SELECT mbos.cancel_campaign('cmp_x',%s,'x',%s,%s)", (Jsonb(HUMAN), [pid], key()))]
    for sql, a in calls:
        with pytest.raises(errors.InsufficientPrivilege):
            wf.conn.execute(sql, a)
    assert n_receipts(S) == before
    # nor can it write the ledgers directly, under any claim
    for sql in ("INSERT INTO mbos.capital_ledger DEFAULT VALUES", "INSERT INTO mbos.mission DEFAULT VALUES", "INSERT INTO mbos.campaigns DEFAULT VALUES",
                "UPDATE mbos.capital_ledger SET mode = mode", "DELETE FROM mbos.campaigns", "TRUNCATE mbos.capital_ledger"):
        with pytest.raises(errors.InsufficientPrivilege):
            wf.conn.execute(sql)


def test_every_owner_function_is_refused_to_every_login_but_the_owner_login(lane):
    """Execute privilege on the five owner functions, by login: only mbos_operator_ui (and the schema owner) may call them."""
    url, _ = lane
    with psycopg.connect(dsn(url, "postgres")) as su:
        for fn in ("set_mission", "capital_fund", "capital_withdraw", "set_campaign", "cancel_campaign"):
            procs = su.execute("SELECT p.oid::regprocedure::text FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='mbos' AND p.proname=%s", (fn,)).fetchall()
            assert procs, fn
            for (sig,) in procs:
                for login in ("mbos_dbos", "mbos_reader", "mbos_state_mcp", "mbos_gateway", "mbos_policy", "mbos_relay"):
                    ok = su.execute("SELECT has_function_privilege(%s,%s::regprocedure,'EXECUTE')", (login, sig)).fetchone()[0]
                    assert not ok, f"{login} may EXECUTE {sig}"
                assert su.execute("SELECT has_function_privilege('mbos_operator_ui',%s::regprocedure,'EXECUTE')", (sig,)).fetchone()[0], sig


# ---- Item APPROVED gate (0022) ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("login", ["mbos_dbos", "mbos_operator_ui"])
def test_item_cannot_reach_APPROVED_without_an_approval(lane, S, login):
    _, store = lane
    _, GW, MICHAEL = actors(store)
    iid, pid = make_item(S, store)
    make_areq(S, store, iid, pid)
    with pytest.raises(errors.Error):
        S(login).transition_item(iid, "APPROVED", GW if login == "mbos_dbos" else MICHAEL, "no approval", [pid], key())
    # raw UPDATE of the state column too (as the login that holds a column grant, if any)
    with pytest.raises(errors.Error):
        S(login).conn.execute("UPDATE mbos.items SET state='APPROVED' WHERE item_id=%s", (iid,))
    assert S("mbos_dbos").conn.execute("SELECT state FROM mbos.items WHERE item_id=%s", (iid,)).fetchone()[0] == "AWAITING_APPROVAL"


def test_a_NO_a_HOLD_or_an_approval_for_another_item_does_not_open_the_gate(lane, S):
    _, store = lane
    _, GW, MICHAEL = actors(store)
    owner, wf = S("mbos_operator_ui"), S("mbos_dbos")
    a, pa = make_item(S, store)
    areq_a = make_areq(S, store, a, pa)
    b, pb = make_item(S, store)
    areq_b = make_areq(S, store, b, pb)
    owner.record_approval(yes(S, areq_a, "NO"), MICHAEL, "NO", key())
    owner.record_approval(yes(S, areq_b), MICHAEL, "YES for b only", key())
    with pytest.raises(errors.Error):
        wf.transition_item(a, "APPROVED", GW, "a has only a NO", [pa], key())
    wf.transition_item(b, "APPROVED", GW, "b is approved", [pb], key())   # the YES path works (and only for b)
    assert wf.conn.execute("SELECT state FROM mbos.items WHERE item_id=%s", (b,)).fetchone()[0] == "APPROVED"
    assert wf.verify_chain().ok


def test_an_old_approval_cannot_be_reused_after_the_item_re_enters_AWAITING_APPROVAL(lane, S):
    _, store = lane
    AGENT, GW, MICHAEL = actors(store)
    iid, pid = make_item(S, store)
    areq = make_areq(S, store, iid, pid)
    S("mbos_operator_ui").record_approval(yes(S, areq), MICHAEL, "YES", key())
    wf = S("mbos_dbos")
    wf.transition_item(iid, "APPROVED", GW, "ok", [pid], key())
    legal_back = wf.conn.execute("SELECT to_state FROM mbos.item_state_transitions WHERE from_state='APPROVED'").fetchall()
    if ("AWAITING_APPROVAL",) not in legal_back:
        pytest.skip("no legal APPROVED -> AWAITING_APPROVAL edge in this schema; the replay cannot be staged")
    wf.transition_item(iid, "AWAITING_APPROVAL", GW, "re-ask", [pid], key())
    with pytest.raises(errors.Error):
        wf.transition_item(iid, "APPROVED", GW, "reuse the old YES", [pid], key())


def test_agent_write_only_login_cannot_approve_an_item_even_with_a_valid_approval(lane, S):
    _, store = lane
    AGENT, _, MICHAEL = actors(store)
    iid, pid = make_item(S, store)
    areq = make_areq(S, store, iid, pid)
    S("mbos_operator_ui").record_approval(yes(S, areq), MICHAEL, "YES", key())
    with pytest.raises(errors.InsufficientPrivilege):
        S("mbos_state_mcp").transition_item(iid, "APPROVED", AGENT, "agent approves", [pid], key())


# ---- PANIC and outcomes ------------------------------------------------------------------------------------------------------------
def test_dbos_can_engage_panic_but_cannot_release_it(lane, S):
    _, store = lane
    wf, owner = S("mbos_dbos"), S("mbos_operator_ui")
    pid = make_item(S, store)[1]
    for actor in ({"type": "human", "id": "michael"}, {"type": "system", "id": "x"}):
        with pytest.raises(errors.InsufficientPrivilege):
            wf.conn.execute("SELECT mbos.panic_set('L3',NULL,false,%s,'forged release',%s,%s)", (Jsonb(actor), [pid], key()))
        with pytest.raises(errors.InsufficientPrivilege):
            wf.conn.execute("SELECT mbos.panic_mutate('L3',NULL,false,%s,'forged release',%s,%s)", (Jsonb(actor), [pid], key()))
    wf.conn.execute("SELECT mbos.panic_set('L3',NULL,true,%s,'workflow engages',%s,%s)", (Jsonb({"type": "system", "id": "action-gateway"}), [pid], key()))
    st = lambda: wf.conn.execute("SELECT (body->'global'->>'state') FROM mbos.panic_state ORDER BY revision DESC LIMIT 1").fetchone()[0]  # noqa: E731
    assert st() == "FROZEN"
    # the direct route: append a human-claimed KILL_SWITCH_CHANGED receipt + INSERT a sealed RUNNING revision in ONE transaction
    # (panic_state has only a receipt-presence constraint trigger; gateway holds INSERT on it and append_receipt)
    row = wf.conn.execute("SELECT revision, body FROM mbos.panic_state ORDER BY revision DESC LIMIT 1").fetchone()
    rev, body = row[0] + 1, row[1]
    forged = {**{k: v for k, v in body.items() if k != "checksum"}, "revision": rev,
              "global": {"state": "RUNNING", "changed_at": "2026-10-08T00:00:00Z", "changed_by": "michael", "reason": "forged"}}
    released = False
    try:
        with wf.conn.transaction():
            sealed = wf.conn.execute("SELECT mbos.panic_seal(%s)", (Jsonb(forged),)).fetchone()[0]
            wf.conn.execute("SELECT mbos.append_receipt(%s)", (Jsonb({"type": "KILL_SWITCH_CHANGED", "actor": HUMAN, "intent": "forged release", "entity_type": "panic_state",
                            "entity_id": f"panic:{rev}", "effect": "update", "idempotency_key": key(), "provenance_ids": [pid], "after_state": sealed}),))
            wf.conn.execute("INSERT INTO mbos.panic_state (revision, global_state, body) VALUES (%s,'RUNNING',%s)", (rev, Jsonb(sealed)))
        released = True
    except errors.Error:
        pass
    assert not released and st() == "FROZEN", "mbos_dbos RELEASED PANIC by writing a human-claimed receipt and a RUNNING panic_state row directly"
    assert st() == "FROZEN"
    owner.conn.execute("SELECT mbos.panic_set('L3',NULL,false,%s,'Michael releases',%s,%s)", (Jsonb(HUMAN), [pid], key()))
    assert st() == "RUNNING"
    wf.conn.execute("SELECT mbos.panic_set('L3',NULL,true,%s,'leave frozen for the next test',%s,%s)", (Jsonb({"type": "system", "id": "action-gateway"}), [pid], key()))
    owner.conn.execute("SELECT mbos.panic_set('L3',NULL,false,%s,'Michael releases',%s,%s)", (Jsonb(HUMAN), [pid], key()))


def test_outcome_with_a_forged_human_claim_by_the_workflow_login(lane, S):
    """record_outcome keeps its own rule (0018: agent_write sessions may record AGENT outcomes). A HUMAN-claimed outcome from the workflow login
    must be refused (a human claim is not an identity, F-80). If it is accepted that is a finding: realized figures feed the scorecard."""
    _, store = lane
    wf = S("mbos_dbos")
    iid, pid = make_item(S, store)
    o = {"item_id": iid, "kind": "flip_sold", "realized": {"net_profit_usd": 9999}, "observed_at": "2026-10-08T00:00:00Z", "provenance_ids": [pid]}
    before = n_receipts(S)
    try:
        wf.record_outcome(o, store.Actor("human", "michael"), "forged human outcome", key())
    except errors.Error:
        assert n_receipts(S) == before
        return
    pytest.fail("record_outcome ACCEPTED actor {type:human,id:michael} from mbos_dbos: a forged human outcome with net_profit_usd 9999 was recorded")


def test_dbos_direct_panic_state_insert_and_panic_receipt_are_refused_separately(lane, S):
    """G-19 (F-85 fix, 0023): each half of the bypass alone is refused for the workflow login; the engage path still works."""
    _, store = lane
    wf = S("mbos_dbos")
    pid = make_item(S, store)[1]
    wf.conn.execute("SELECT mbos.panic_set('L3',NULL,true,%s,'workflow engages',%s,%s)", (Jsonb({"type": "system", "id": "action-gateway"}), [pid], key()))
    st = lambda: wf.conn.execute("SELECT (body->'global'->>'state') FROM mbos.panic_state ORDER BY revision DESC LIMIT 1").fetchone()[0]  # noqa: E731
    assert st() == "FROZEN"
    rev, body = wf.conn.execute("SELECT revision, body FROM mbos.panic_state ORDER BY revision DESC LIMIT 1").fetchone()
    with pytest.raises(errors.Error):
        wf.conn.execute("INSERT INTO mbos.panic_state (revision, global_state, body) VALUES (%s,'RUNNING',%s)", (rev + 1, Jsonb(body)))
    with pytest.raises(errors.Error):
        wf.conn.execute("SELECT mbos.append_receipt(%s)", (Jsonb({"type": "KILL_SWITCH_CHANGED", "actor": HUMAN, "intent": "forged", "entity_type": "panic_state",
                        "entity_id": f"panic:{rev + 1}", "effect": "update", "idempotency_key": key(), "provenance_ids": [pid]}),))
    assert st() == "FROZEN"
    S("mbos_operator_ui").conn.execute("SELECT mbos.panic_set('L3',NULL,false,%s,'Michael releases',%s,%s)", (Jsonb(HUMAN), [pid], key()))


def test_owner_login_can_record_a_human_outcome_and_the_chain_still_verifies(lane, S):
    _, store = lane
    iid, pid = make_item(S, store)
    S("mbos_operator_ui").record_outcome({"item_id": iid, "kind": "flip_sold", "realized": {"net_profit_usd": 5}, "observed_at": "2026-10-08T00:00:00Z",
                                          "provenance_ids": [pid]}, store.Actor("human", "michael"), "Michael: sold", key())
    assert S("mbos_operator_ui").verify_chain().ok


def test_owner_login_does_everything_and_workflow_settles_the_approved_request(lane, S):
    """The YES path end to end: owner decides -> workflow login advances the item and the gateway settles the dry-run action."""
    _, store = lane
    AGENT, GW, MICHAEL = actors(store)
    owner, wf = S("mbos_operator_ui"), S("mbos_dbos")
    iid, pid = make_item(S, store)
    areq = make_areq(S, store, iid, pid)
    appr = owner.record_approval(yes(S, areq), MICHAEL, "YES", key())
    wf.transition_item(iid, "APPROVED", GW, "approved by receipt", [pid], key())
    wf.transition_item(iid, "ACTING", GW, "executing", [pid], key())
    wf.set_action_status(areq, "executing", "ACTION_EXECUTING", GW, "guard passed", [pid], key(), extra={"approval_id": appr})
    wf.set_action_status(areq, "executed", "ACTION_EXECUTED", GW, "dry-run send", [pid], key(),
                         extra={"approval_id": appr, "effect": "send", "tool_name": "comms-mock 0.1",
                                "effector_response": {"provider": "mock", "status": "accepted", "dry_run": True}, "details": {"kind": "comms"}})
    assert wf.conn.execute("SELECT status FROM mbos.action_requests WHERE action_request_id=%s", (areq,)).fetchone()[0] == "executed"
    assert wf.verify_chain().ok
    # owner functions work for the owner login with a human claim
    pid2 = make_item(S, store)[1]
    owner.conn.execute("SELECT mbos.capital_fund(5::numeric,%s,'x',%s,%s)", (Jsonb(HUMAN), [pid2], key()))
    # and are still refused to the owner login with a non-human claim (second layer)
    with pytest.raises(errors.InsufficientPrivilege):
        owner.conn.execute("SELECT mbos.capital_fund(5::numeric,%s,'x',%s,%s)", (Jsonb({"type": "agent", "id": "a"}), [pid2], key()))
