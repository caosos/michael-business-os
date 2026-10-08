"""D-26a: the workflow login mbos_dbos holds agent_write + gateway ONLY; Michael's decisions come from the owner login."""

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import AGENT, GATEWAY, MICHAEL, key, make_areq, make_item, payload_hash, to_pending
from mbos_state.provision import provision
from mbos_state.store import StateStore
from test_campaigns import EXAMPLE
from test_human_only_owner_paths import MISSION, N, _calls
from test_operator_notes import bundle

HUMAN = {"type": "human", "id": "michael"}


@pytest.fixture
def prov(cluster):
    n = next(N)
    admin = f"{cluster['base']} dbname=postgres user=postgres"
    p = provision(admin, app_db=f"d26_app_{n}", sys_db=f"d26_sys_{n}")
    yield p
    with psycopg.connect(admin, autocommit=True) as c:
        for db in (f"d26_app_{n}", f"d26_sys_{n}"):
            c.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")


def test_provision_returns_both_urls_and_exact_role_sets(prov):
    assert prov.app_url.startswith("postgresql://mbos_dbos@") and prov.owner_app_url.startswith("postgresql://mbos_operator_ui@")
    with psycopg.connect(prov.app_conninfo.replace("user=mbos_dbos", "user=postgres"), autocommit=True) as su:
        def groups(login):
            return {r[0] for r in su.execute("""SELECT g.rolname FROM pg_auth_members a JOIN pg_roles g ON g.oid=a.roleid
                                                JOIN pg_roles m ON m.oid=a.member WHERE m.rolname=%s""", (login,))}
        assert groups("mbos_dbos") == {"agent_write", "gateway"}
        assert groups("mbos_operator_ui") == {"approver", "owner_channel"}
    with psycopg.connect(prov.owner_app_url) as c:
        assert c.execute("SELECT current_user").fetchone()[0] == "mbos_operator_ui"


def test_dbos_refused_decide_note_owner_paths_owner_allowed_gateway_settles(prov):
    wf = StateStore(psycopg.connect(prov.app_conninfo, autocommit=True))
    owner = StateStore(psycopg.connect(prov.owner_app_url, autocommit=True))
    item_id, pid = make_item(wf, "AWAITING_APPROVAL")
    areq = make_areq(wf, item_id, pid)
    to_pending(wf, areq, pid)
    yes = {"action_request_id": areq, "decision": "YES", "decider": "michael", "channel": "web",
           "payload_hash_seen": payload_hash(wf, areq), "scope": "once", "auth_context": {"method": "webauthn", "step_up": True}}
    # decide / approval: refused by ROLE for the workflow login
    with pytest.raises(errors.InsufficientPrivilege):
        wf.record_approval(yes, MICHAEL, "forged YES", key())
    # operator note: refused
    with pytest.raises(errors.InsufficientPrivilege):
        wf.record_operator_note(bundle())
    # fund / mission / set_campaign / cancel_campaign / withdraw: refused
    for sql, args in _calls(HUMAN, pid):
        with pytest.raises(errors.InsufficientPrivilege):
            wf.conn.execute(sql, args)
    # the owner login does all of them
    appr = owner.record_approval(yes, MICHAEL, "Michael: YES", key())
    owner.transition_item(item_id, "APPROVED", MICHAEL, "approved", [pid], key())
    owner.record_operator_note(bundle())
    owner.conn.execute("SELECT mbos.capital_fund(5::numeric,%s,'x',%s,%s)", (Jsonb(HUMAN), [pid], key()))
    owner.conn.execute("SELECT mbos.set_campaign(%s,%s,'x',%s,%s)", (Jsonb(EXAMPLE), Jsonb(HUMAN), [pid], key()))
    # gateway settlement of the approved request as the real mbos_dbos still works
    wf.transition_item(item_id, "ACTING", GATEWAY, "executing", [pid], key())
    wf.set_action_status(areq, "executing", "ACTION_EXECUTING", GATEWAY, "guard passed", [pid], key(),
                         extra={"approval_id": appr})
    wf.set_action_status(areq, "executed", "ACTION_EXECUTED", GATEWAY, "dry-run send", [pid], key(),
                         extra={"approval_id": appr, "effect": "send", "tool_name": "comms-mock 0.1",
                                "effector_response": {"provider": "mock", "status": "accepted", "dry_run": True},
                                "details": {"kind": "comms"}})
    assert wf.conn.execute("SELECT status FROM mbos.action_requests WHERE action_request_id=%s", (areq,)).fetchone()[0] == "executed"
    assert wf.verify_chain().ok


def test_item_approved_edge_needs_approval_receipt_and_role(prov):
    wf = StateStore(psycopg.connect(prov.app_conninfo, autocommit=True))
    owner = StateStore(psycopg.connect(prov.owner_app_url, autocommit=True))
    item_id, pid = make_item(wf, "AWAITING_APPROVAL")
    areq = make_areq(wf, item_id, pid)
    to_pending(wf, areq, pid)
    # no approval yet: the workflow login (and the owner login) are refused
    for s in (wf, owner):
        with pytest.raises(errors.Error) as e:
            s.transition_item(item_id, "APPROVED", MICHAEL, "no approval", [pid], key())
        assert getattr(e.value, "sqlstate", None) == "MB005"
    # a NO is not an approval
    owner.record_approval({"action_request_id": areq, "decision": "NO", "decider": "michael", "channel": "web",
                           "payload_hash_seen": payload_hash(wf, areq), "scope": "once", "reason": "no",
                           "auth_context": {"method": "webauthn", "step_up": True}}, MICHAEL, "NO", key())
    with pytest.raises(errors.Error):
        wf.transition_item(item_id, "APPROVED", MICHAEL, "after NO", [pid], key())
    # normal YES path end to end
    item2, pid2 = make_item(wf, "AWAITING_APPROVAL")
    areq2 = make_areq(wf, item2, pid2)
    to_pending(wf, areq2, pid2)
    owner.record_approval({"action_request_id": areq2, "decision": "YES", "decider": "michael", "channel": "web",
                           "payload_hash_seen": payload_hash(wf, areq2), "scope": "once",
                           "auth_context": {"method": "webauthn", "step_up": True}}, MICHAEL, "YES", key())
    wf.transition_item(item2, "APPROVED", GATEWAY, "approved by receipt", [pid2], key())
    assert wf.conn.execute("SELECT state FROM mbos.items WHERE item_id=%s", (item2,)).fetchone()[0] == "APPROVED"
    assert wf.verify_chain().ok
