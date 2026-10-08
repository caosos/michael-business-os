"""D-28 (G-18 F-85 + F-86): the workflow login mbos_dbos can engage PANIC but cannot release it, and cannot record a human outcome."""

import itertools

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import AGENT, MICHAEL, key, make_item
from mbos_state.provision import provision
from mbos_state.store import StateStore

HUMAN = {"type": "human", "id": "michael"}
SYSTEM = {"type": "system", "id": "action-gateway"}
N = itertools.count()


@pytest.fixture
def prov(cluster):
    n = next(N)
    admin = f"{cluster['base']} dbname=postgres user=postgres"
    p = provision(admin, app_db=f"d28_app_{n}", sys_db=f"d28_sys_{n}")
    yield p
    with psycopg.connect(admin, autocommit=True) as c:
        for db in (f"d28_app_{n}", f"d28_sys_{n}"):
            c.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")


def _state(c):
    return c.execute("SELECT global_state FROM mbos.panic_state ORDER BY revision DESC LIMIT 1").fetchone()[0]


def test_dbos_engages_but_cannot_release_panic_by_any_route(prov):
    wf = StateStore(psycopg.connect(prov.app_conninfo, autocommit=True))
    owner = StateStore(psycopg.connect(prov.owner_app_url, autocommit=True))
    pid = make_item(wf, "AWAITING_APPROVAL")[1]
    c = wf.conn
    for fn in ("panic_set", "panic_mutate"):
        for actor in (HUMAN, SYSTEM):
            with pytest.raises(errors.InsufficientPrivilege):
                c.execute(f"SELECT mbos.{fn}('L3',NULL,false,%s,'forged release',%s,%s)", (Jsonb(actor), [pid], key()))
    c.execute("SELECT mbos.panic_set('L3',NULL,true,%s,'workflow engages',%s,%s)", (Jsonb(SYSTEM), [pid], key()))
    assert _state(c) == "FROZEN"
    with pytest.raises(errors.InsufficientPrivilege):
        c.execute("INSERT INTO mbos.panic_state (revision, global_state, body) VALUES (99,'RUNNING','{}')")
    rev, body = c.execute("SELECT revision, body FROM mbos.panic_state ORDER BY revision DESC LIMIT 1").fetchone()
    forged = {**{k: v for k, v in body.items() if k != "checksum"}, "revision": rev + 1,
              "global": {"state": "RUNNING", "changed_at": "2026-10-08T00:00:00Z", "changed_by": "michael", "reason": "forged"}}
    with pytest.raises(errors.InsufficientPrivilege):
        with c.transaction():
            sealed = c.execute("SELECT mbos.panic_seal(%s)", (Jsonb(forged),)).fetchone()[0]
            c.execute("SELECT mbos.append_receipt(%s)", (Jsonb({"type": "KILL_SWITCH_CHANGED", "actor": HUMAN, "intent": "forged", "entity_type": "panic_state",
                      "entity_id": f"panic:{rev + 1}", "effect": "update", "idempotency_key": key(), "provenance_ids": [pid], "after_state": sealed}),))
    with pytest.raises(errors.InsufficientPrivilege):
        c.execute("SELECT mbos._panic_write(%s,NULL,%s,'x',%s,%s)", (Jsonb(forged), Jsonb(HUMAN), [pid], key()))
    assert _state(c) == "FROZEN"
    owner.conn.execute("SELECT mbos.panic_set('L3',NULL,false,%s,'Michael releases',%s,%s)", (Jsonb(HUMAN), [pid], key()))
    assert _state(c) == "RUNNING"
    assert owner.verify_chain().ok


def test_forged_human_outcome_refused_agent_outcome_and_owner_human_outcome_allowed(prov):
    wf = StateStore(psycopg.connect(prov.app_conninfo, autocommit=True))
    owner = StateStore(psycopg.connect(prov.owner_app_url, autocommit=True))
    iid, pid = make_item(wf, "AWAITING_APPROVAL")
    o = {"item_id": iid, "kind": "flip_sold", "realized": {"net_profit_usd": 9999}, "observed_at": "2026-10-08T00:00:00Z", "provenance_ids": [pid]}
    with pytest.raises(errors.InsufficientPrivilege):
        wf.record_outcome(o, MICHAEL, "forged human outcome", key())
    wf.record_outcome(o, AGENT, "agent outcome", key())
    owner.record_outcome(o, MICHAEL, "Michael: sold", key())
    assert owner.verify_chain().ok
