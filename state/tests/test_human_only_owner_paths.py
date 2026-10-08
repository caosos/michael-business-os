"""D-24: the five owner paths refuse a non-human actor for EVERY session, including the real mbos_dbos login."""

import json
from pathlib import Path

import psycopg
import pytest
from psycopg import errors
from psycopg.types.json import Jsonb

from conftest import key
from mbos_state.provision import provision
from test_campaigns import EXAMPLE
from test_capital_ledger import Cap

MISSION = json.loads((Path(__file__).parent / "contracts-additive/examples/mission/mission-unknown-target.example.json").read_text())
N = iter(range(10_000))
BAD = [{"type": "agent", "id": "agent-x"}, {"type": "system", "id": "gw"}, {"type": "human", "id": " "},
       {"type": "human"}, {}]


@pytest.fixture
def real_dbos(cluster):
    n = next(N)
    admin = f"{cluster['base']} dbname=postgres user=postgres"
    p = provision(admin, app_db=f"h24_app_{n}", sys_db=f"h24_sys_{n}")
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:
        pid = c.execute("""SELECT mbos.record_provenance('{"actor_type":"system","basis":"FACT",
                           "tool_name":"t","tool_version":"1"}')""").fetchone()[0]
    yield p, pid
    with psycopg.connect(admin, autocommit=True) as c:
        for db in (f"h24_app_{n}", f"h24_sys_{n}"):
            c.execute(f"DROP DATABASE IF EXISTS {db} WITH (FORCE)")


def _calls(a, pid):
    j = Jsonb(a)
    return [("SELECT mbos.set_mission(%s,%s,'x',%s,%s)", (Jsonb(MISSION), j, [pid], key())),
            ("SELECT mbos.capital_fund(5::numeric,%s,'x',%s,%s)", (j, [pid], key())),
            ("SELECT mbos.capital_withdraw(5::numeric,%s,'x',%s,%s)", (j, [pid], key())),
            ("SELECT mbos.set_campaign(%s,%s,'x',%s,%s)", (Jsonb(EXAMPLE), j, [pid], key())),
            ("SELECT mbos.cancel_campaign(%s,%s,'x',%s,%s)", (EXAMPLE["campaign_id"], j, [pid], key()))]


@pytest.mark.parametrize("actor", BAD)
def test_real_mbos_dbos_refuses_non_human_on_all_five(real_dbos, actor):
    p, pid = real_dbos
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:
        assert c.execute("SELECT session_user").fetchone()[0] == "mbos_dbos"
        for sql, args in _calls(actor, pid):
            with pytest.raises(errors.InsufficientPrivilege, match="as a human"):
                c.execute(sql, args)
        assert c.execute("SELECT count(*) FROM mbos.capital_ledger").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM mbos.campaigns").fetchone()[0] == 0


def test_real_mbos_dbos_with_human_actor_passes_the_guard(real_dbos):
    p, pid = real_dbos
    with psycopg.connect(p.app_conninfo, autocommit=True) as c:      # approver member: a human actor is accepted
        c.execute("SELECT mbos.capital_fund(5::numeric,%s,'x',%s,%s)", (Jsonb({"type": "human", "id": "michael"}), [pid], key()))


def test_ui_login_human_path_and_chain_still_ok(db):
    cap = Cap(db)
    assert cap.owner.conn.execute("SELECT session_user").fetchone()[0] == "mbos_operator_ui"
    cap.fund(10)
    cap.owner.conn.execute("SELECT mbos.set_campaign(%s,%s,'x',%s,%s)", (Jsonb(EXAMPLE), cap.human, [cap.pid], key()))
    assert cap.owner.verify_chain().ok
